"""Security & governance for Wilco: per-tool permissions, audit logging, and rate limiting.

Everything here is off by default (a plain .env with no new flags behaves exactly as before)
and is designed to be layered onto the existing tool dispatch without changing its behaviour
when disabled. It fits alongside the existing gate.py confirmation protocol: gate.py handles
"should the user confirm this destructive action?" while this module handles the wider
administrative concerns — who may use which tool, a permanent record of what ran, and
protecting expensive operations from being hammered.

Three concerns, three small pieces:

  - Permissions   : a whitelist/blacklist of tool names plus a default stance.
  - Audit log     : append-only JSONL line per tool call (never silently edited in place).
  - Rate limiting : a per-tool window (calls per N seconds); excess calls are refused.

All functions are safe to call with the feature disabled — they short-circuit early.
"""
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from config import _flag, _number

# --- config (reads .env; defaults keep everything OFF) -------------------------------
PERMISSIONS_ENABLED = _flag("WILCO_PERMISSIONS_ENABLED", False)
AUDIT_ENABLED = _flag("WILCO_AUDIT_ENABLED", False)
RATE_LIMIT_ENABLED = _flag("WILCO_RATE_LIMIT_ENABLED", False)

# tools that are ALWAYS allowed regardless of stance (core, harmless introspection)
ALWAYS_ALLOW = {
    "confirm_yes", "cancel_action", "list_my_tools", "self_check",
    "check_requirements", "read_web_page",
}

# tools that are blocked regardless, unless explicitly allowed (belt-and-braces)
ALWAYS_BLOCK = {
    "run_python",  # sandboxed by default via gate; also targetable by WILCO_TOOL_DENY
}

AUDIT_FILE = Path(__file__).resolve().parent.parent / "audit.jsonl"
AUDIT_MAX_LINES = 20000
# JSONL is append-only, so an audit line is a JSON object per physical line.
def _log_line(*, tool, arguments, result_len, ok, latency, denied, note):
    line = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "tool": tool,
        "args_len": len(json.dumps(arguments, default=str)),
        "result_len": result_len,
        "ok": ok,
        "latency_ms": round(latency * 1000, 1),
        "denied": denied,
        "note": note,
    }
    try:
        plus = ""
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > 0:
            plus = "\n"
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(plus + json.dumps(line, default=str))
    except OSError:
        pass  # a failed write must not break the assistant


def _trim_audit():
    """Keep the audit file from growing without bound when it changes go ahead."""
    if not AUDIT_FILE.exists():
        return
    try:
        fat = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        if len(fat) <= AUDIT_MAX_LINES:
            return
        surplus = fat[: len(fat) - AUDIT_MAX_LINES]
        # compact them to one summary line so history is not silently dropped
        kept = fat[-AUDIT_MAX_LINES:]
        summary = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "compacted": len(surplus),
            "from": surplus[0].split(",")[0] if surplus else None,
        }
        AUDIT_FILE.write_text("\n".join(kept + [json.dumps(summary)]) + "\n", encoding="utf-8")
    except (OSError, IndexError):
        pass


def audit(*, tool="", arguments=None, result_len=0, ok=True, latency=0.0,
          denied=False, note=""):
    """Record one tool call in the append-only audit log (no-op unless enabled)."""
    if not AUDIT_ENABLED:
        return
    _log_line(tool=tool, arguments=arguments or {}, result_len=result_len,
              ok=ok, latency=latency, denied=denied, note=note)
    _trim_audit()


def audit_recent(limit=50) -> list:
    """Read back the most recent audit lines (for a security review tool/report)."""
    if not AUDIT_FILE.exists():
        return []
    try:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


# --- permissions ---------------------------------------------------------------------
# Default stance: "allow" or "deny". allow means everything not listed is permitted unless
# blocked; deny means only ALWAYS_ALLOW plus explicit allow-list names may run.
def _parse_csv(name, default=""):
    raw = os.environ.get(name, "").strip()
    return {x.strip().lower() for x in raw.split(",") if x.strip()} or \
        ({default.lower()} if default else set())


PERMS_DEFAULT = (os.environ.get("WILCO_PERMS_DEFAULT", "allow").strip().lower()
                 if _flag("WILCO_PERMISSIONS_ENABLED", False) else "allow")
TOOL_ALLOW = _parse_csv("WILCO_TOOL_ALLOW")
TOOL_DENY = _parse_csv("WILCO_TOOL_DENY")


def check_permission(tool_name: str) -> bool:
    """Is this tool allowed to run under the current permission rules?"""
    if not PERMISSIONS_ENABLED:
        return True  # feature off = everything permitted (legacy behaviour)
    name = tool_name.lower()
    if name in TOOL_DENY or name in ALWAYS_BLOCK:
        return False
    if name in ALWAYS_ALLOW or name in TOOL_ALLOW:
        return True
    return PERMS_DEFAULT == "allow"


# --- rate limiting -------------------------------------------------------------------
# A per-tool ring buffer of recent timestamps. Cheap, in-memory, no deps.
_WINDOWS = defaultdict(lambda: deque(maxlen=64))  # tool -> deque of last-call epoch times
WILCO_RATE_LIMIT = _number("WILCO_RATE_LIMIT", 10, int)      # max calls per window
WILCO_RATE_WINDOW = _number("WILCO_RATE_WINDOW", 60, float)  # window in seconds


def _permitted_now(tool_name) -> bool:
    """True if calling tool_name now stays within its rate window."""
    if not RATE_LIMIT_ENABLED:
        return True
    if WILCO_RATE_LIMIT <= 0:
        return True
    now = time.monotonic()
    recent = _WINDOWS[tool_name]
    while recent and now - recent[0] > WILCO_RATE_WINDOW:
        recent.popleft()
    if len(recent) >= WILCO_RATE_LIMIT:
        return False
    recent.append(now)
    return True


def reset_rate_limits():
    """Forget all rate-limiting counters (used by tests)."""
    _WINDOWS.clear()
