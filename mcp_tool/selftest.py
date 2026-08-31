"""Wilco checking itself: what it can do, and whether it still works.

Everything here was a terminal command run by hand while debugging — parse every file, count
the tools, confirm the dangerous-command gates still catch what they should. Left as loose
commands they get run once and forgotten; as tools they can be asked for out loud, and the
safety check in particular is worth being able to repeat after any change.

Nothing outside a throwaway temp folder is ever written, and a real action waiting on the
user's yes is preserved across the check rather than being fired by it.
"""
import ast
import os
import shutil
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", "venv", ".venv"}

# samples the gates must get right — reads must pass through, writes must be held
SAFE_SAMPLES = {
    "powershell": ["Get-Process | Select -First 3", "ipconfig /all", "systeminfo"],
    "bash": ["find . -name '*.py' | head -5", "grep -ril key --include=*.py .", "du -sh *"],
    "python": ["print(sum(range(10)))", "import windows.apps as ap; print(ap.index())"],
}
RISKY_SAMPLES = {
    "powershell": ["Remove-Item C:\\x -Recurse", "Clear-Disk -Number 1", "Get-Date > out.txt"],
    "bash": ["rm -rf /c/Users", "find . -name '*.tmp' -delete", "ls; rm -rf x"],
    "python": ['import os; os.remove("x")', 'open("f","w").write("x")', "import shutil; shutil.rmtree('d')"],
}


def list_my_tools(filter_text=""):
    """Everything Wilco can do, by name. Use this when the user asks what you can do, what
    you're capable of, or whether you can do some particular thing. filter_text narrows it —
    'file', 'window', 'music'. Describe the useful ones in plain words; never read a bare
    list of function names out loud."""
    from mcp_tool import REGISTRY  # imported here: mcp_tool imports this module in turn

    names = sorted(REGISTRY)
    if filter_text.strip():
        wanted = filter_text.strip().lower()
        names = [n for n in names if wanted in n or wanted in (REGISTRY[n].__doc__ or "").lower()]
    if not names:
        return f"Nothing matching {filter_text}."
    grouped = {}
    for name in names:
        grouped.setdefault(REGISTRY[name].__module__.rsplit(".", 1)[-1], []).append(name)
    parts = [f"{area}: {', '.join(tools)}" for area, tools in sorted(grouped.items())]
    return f"{len(names)} tools. " + " | ".join(parts)


def _python_files():
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                yield Path(root) / name


def _check_edit_result(result, path, problems):
    """Verify edit_file result for current ALWAYS_ACT mode, append problems."""
    from mcp_tool import gate, pc
    from config import ALWAYS_ACT

    if ALWAYS_ACT:
        if result.startswith("NOT DONE"):
            problems.append("edit_file parked in all-access mode")
        if "9090" not in Path(path).read_text(encoding="utf-8"):
            problems.append("edit_file didn't apply the change in all-access mode")
    else:
        if not result.startswith("NOT DONE"):
            problems.append("edit_file did not stop to ask")
        if "8080" not in Path(path).read_text(encoding="utf-8"):
            problems.append("edit_file wrote to disk before being confirmed")
        gate.confirm_yes()
        if "9090" not in Path(path).read_text(encoding="utf-8"):
            problems.append("confirming an edit did not apply it")


def _round_trip():
    """Really create, read, edit, and back up a file in a temp folder that is deleted
    afterwards. All-access mode is exercised too: edits still apply and keep a .bak,
    just without the confirm-yes round.
    """
    from mcp_tool import gate, pc

    key = gate.session.get()
    theirs = gate._pending.pop(key, None)
    problems, folder = [], tempfile.mkdtemp(prefix="wilco-check-")
    try:
        path = os.path.join(folder, "check.txt")
        Path(path).write_text("port = 8080" + chr(10) + "name = wilco" + chr(10), encoding="utf-8")

        if "8080" not in pc.read_file(path):
            problems.append("read_file didn't return the contents")
        result = pc.edit_file(path, "8080", "9090")
        _check_edit_result(result, path, problems)
        if not os.path.isfile(path + ".bak"):
            problems.append("no .bak backup was kept")
        if "doesn't contain" not in pc.edit_file(path, "zzz-absent", "x"):
            problems.append("editing text that isn't there was not reported")
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    finally:
        gate._pending.pop(key, None)
        if theirs is not None:
            gate._pending[key] = theirs
        shutil.rmtree(folder, ignore_errors=True)
    return problems


def _gates_hold():
    """Do the critical-action classifiers still sort the samples correctly?"""
    from mcp_tool import shell_tool

    tests = [("powershell", shell_tool._powershell_needs_confirmation),
             ("bash", shell_tool._bash_needs_confirmation),
             ("python", lambda c: bool(shell_tool.PY_CRITICAL.search(c)))]
    wrong = []
    for label, is_critical in tests:
        wrong += [f"{label}:{c}" for c in SAFE_SAMPLES[label] if is_critical(c)]
        wrong += [f"{label}:{c}" for c in RISKY_SAMPLES[label] if not is_critical(c)]
    return wrong


def self_check():
    """Check Wilco's own health and report what's wrong. Use when the user asks if you're
    working properly, whether something is broken, or after they've changed the code.

    Covers: every source file still parsing, the tool registry, the three command runners,
    whether Git Bash is present, which credentials are configured, and — most importantly —
    whether the safety gates still refuse to run dangerous commands."""
    from mcp_tool import REGISTRY, shell_tool

    lines, problems = [], 0

    broken = []
    for path in _python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            broken.append(f"{path.relative_to(PROJECT)} line {e.lineno}")
    problems += len(broken)
    lines.append(f"source files: {'all parse' if not broken else 'BROKEN — ' + '; '.join(broken)}")

    lines.append(f"tools registered: {len(REGISTRY)}")

    runners = [n for n in ("run_powershell", "run_bash", "run_python") if n in REGISTRY]
    if len(runners) < 3:
        problems += 1
    lines.append(f"command runners: {', '.join(runners) or 'NONE'}")

    bash = shell_tool._bash_exe()
    if not bash:
        problems += 1
    lines.append(f"git bash: {bash or 'MISSING — file searching will not work'}")

    configured = [k for k in ("COHERE_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY",
                              "ANTHROPIC_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
                              "HUGGINGFACE_API_KEY")
                  if os.environ.get(k)]
    if not any(os.environ.get(k) for k in ("GROQ_API_KEY", "OPENROUTER_API_KEY",
                                           "HUGGINGFACE_API_KEY", "NVIDIA_API_KEY")):
        problems += 1
        lines.append("speech-to-text key: MISSING — set GROQ_API_KEY (fallbacks: "
                     "OPENROUTER_API_KEY, HUGGINGFACE_API_KEY)")
    else:
        # names only, never values
        lines.append(f"keys set: {', '.join(configured)}")
    lines.append(f"email configured: {'yes' if os.environ.get('WILCO_EMAIL') else 'no'}")
    lines.append(f"contacts file: {'yes' if (PROJECT / 'contacts.json').is_file() else 'no'}")

    wrong = _gates_hold()
    problems += len(wrong)
    lines.append("safety gates: " + ("holding — dangerous commands are still held for "
                                     "confirmation" if not wrong else
                                     f"FAILING on {'; '.join(wrong)}"))

    failed = _round_trip()
    problems += len(failed)
    lines.append("file tools: " + ("read, edit, confirm and backup all work end to end"
                                   if not failed else "FAILING — " + "; ".join(failed)))

    headline = "Everything checks out." if not problems else f"{problems} problem(s) found."
    return headline + "\n" + "\n".join(lines)


def self_heal():
    """Safely repair Wilco's recoverable in-memory state: refresh cached file/app indexes and
    remove incomplete conversation tool-call history. It never changes user files, installs
    anything, or alters Windows settings. Use after repeated stale search results, an app that
    was just installed, or a conversation error; run self_check afterwards for verification."""
    import windows.apps as apps
    import windows.files as files
    from core import agent

    repaired = []
    for label, cached in (("file library", files._scan),
                          ("app list", apps.index),
                          ("file opener list", apps.openers)):
        clear = getattr(cached, "cache_clear", None)
        if clear:
            clear()
            repaired.append(label)

    before = len(agent.history)
    agent._repair()
    if len(agent.history) != before:
        repaired.append("incomplete conversation history")
    return "Self-heal completed: refreshed " + ", ".join(repaired) + "."
