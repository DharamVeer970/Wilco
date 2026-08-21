"""Governance tools the model can call: audit review, permission status, rate limits.

These expose the core/safety.py and core/analytics.py layers as callable tools so Wilco can
answer "what have you done today", "which tools are disallowed", and "how's the system
performing" without any special-casing. They are read-only and harmless.
"""

from core.safety import audit_recent, ALWAYS_ALLOW, ALWAYS_BLOCK
from core.analytics import analytics


def review_audit_log(how_many=20):
    """Review the most recent tool executions from the audit log — what ran, when, and whether it succeeded. Pass how_many (default 20) for how many recent entries to show. Best for answering 'what have you done recently'."""
    entries = audit_recent(how_many)
    if not entries:
        return "The audit log is empty (audit logging may be off — set WILCO_AUDIT_ENABLED=1)."
    lines = []
    for e in entries:
        if e.get("compacted"):
            lines.append(f"[{e['ts']}] compacted {e['compacted']} older entries")
            continue
        if e.get("ok"):
            state = "ok"
        elif e.get("denied"):
            state = "denied"
        else:
            state = "error"
        lines.append(f"{e.get('ts', '?')} | {state:6s} | {e.get('tool', '?')} | "
                     f"args {e.get('args_len', 0)} chars, result {e.get('result_len', 0)} chars, "
                     f"{e.get('latency_ms', 0):.0f}ms")
    return "\n".join(lines)


def permission_status():
    """Report the current permission posture: default stance, which tools are always allowed, always blocked, or explicitly allowed/denied."""
    lines = [f"Permissions enabled: {_enabled()}", "Default stance: allow"]
    lines.append("Always allowed: " + (", ".join(sorted(ALWAYS_ALLOW)) or "none"))
    lines.append("Always blocked: " + (", ".join(sorted(ALWAYS_BLOCK)) or "none"))
    return "\n".join(lines)


def _enabled():
    from core import safety as _s
    return bool(_s.PERMISSIONS_ENABLED)


def system_performance(limit=6):
    """Summarise tool performance from analytics: which tools ran, their success rate and average duration. Pass limit (default 6) to cap how many tools are listed."""
    stats = analytics.get_all_stats()
    if not stats:
        return "No performance data recorded yet."
    ordered = sorted(stats.values(), key=lambda s: s.total_calls, reverse=True)[:limit]
    lines = ["Performance summary (most-used first):"]
    for s in ordered:
        lines.append(f"  {s.name}: {s.total_calls} calls, "
                     f"{s.success_rate:.0%} success, avg {s.avg_duration:.2f}s")
    return "\n".join(lines)
