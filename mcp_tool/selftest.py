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
    "powershell": ["Remove-Item C:\\x -Recurse", "Stop-Service spooler", "Get-Date > out.txt"],
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


def _round_trip():
    """Really create, read, edit, confirm and back up a file — in a temp folder that is
    deleted afterwards. Classifying a command correctly is not the same as the tool working,
    and only one of those two things was being checked before.
    """
    from mcp_tool import gate, pc

    # The user may have a real action waiting on a spoken yes. This test calls confirm_yes,
    # which would otherwise fire THEIR pending action — so theirs is lifted out first and put
    # back afterwards, whatever happens in between.
    key = gate.session.get()
    theirs = gate._pending.pop(key, None)
    problems, folder = [], tempfile.mkdtemp(prefix="wilco-check-")
    try:
        path = os.path.join(folder, "check.txt")
        Path(path).write_text("port = 8080\nname = wilco\n", encoding="utf-8")

        if "8080" not in pc.read_file(path):
            problems.append("read_file didn't return the contents")
        if not pc.edit_file(path, "8080", "9090").startswith("NOT DONE"):
            problems.append("edit_file did not stop to ask")
        if "8080" not in Path(path).read_text(encoding="utf-8"):
            problems.append("edit_file wrote to disk before being confirmed")

        gate.confirm_yes()
        if "9090" not in Path(path).read_text(encoding="utf-8"):
            problems.append("confirming an edit did not apply it")
        if not os.path.isfile(path + ".bak"):
            problems.append("no .bak backup was kept")
        if "doesn't contain" not in pc.edit_file(path, "zzz-absent", "x"):
            problems.append("editing text that isn't there was not reported")
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    finally:
        gate._pending.pop(key, None)          # drop anything this test parked
        if theirs is not None:
            gate._pending[key] = theirs       # and hand the user's back untouched
        shutil.rmtree(folder, ignore_errors=True)
    return problems


def _gates_hold():
    """Do the read/write classifiers still sort the samples correctly?"""
    from mcp_tool import shell_tool

    tests = [("powershell", shell_tool._is_read_only),
             ("bash", shell_tool._is_plain_read),
             ("python", lambda c: not shell_tool.PY_MUTATES.search(c))]
    wrong = []
    for label, is_safe in tests:
        wrong += [f"{label}:{c}" for c in SAFE_SAMPLES[label] if not is_safe(c)]
        wrong += [f"{label}:{c}" for c in RISKY_SAMPLES[label] if is_safe(c)]
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

    configured = [k for k in ("COHERE_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
                              "ANTHROPIC_API_KEY", "HUGGINGFACE_API_KEY")
                  if os.environ.get(k)]
    if "HUGGINGFACE_API_KEY" not in configured:
        problems += 1
        lines.append("speech-to-text key: MISSING — HUGGINGFACE_API_KEY is required")
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
