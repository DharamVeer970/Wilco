"""Coding, debugging and workflow automation — the three jobs the other tools make awkward.

Three gaps, not two frameworks. run_bash has no git in its read list, so even `git status`
had to be confirmed out loud. Nothing ran a test suite. And press_key taps one combination,
so a sequence of them had no name to call it by.

A macro is a list of plain lines — "focus Notepad", "key ctrl+s", "type hello", "wait 0.5" —
played through windows/system.py, which already sends keys, text and focus. That is the
whole execution layer, so there is no second scripting language to install and no bridge to
keep in step with it.
"""
import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    # `python mcp_tool/workflow.py` runs the self-test block at the bottom; without this
    # the project's own packages aren't importable because sys.path[0] is the mcp_tool dir.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import windows.shell as shell
import windows.system as system
from config import MAX_OUTPUT
from mcp_tool.gate import _park
from mcp_tool.pc import _resolve

PROJECT = Path(__file__).resolve().parent.parent
MACROS = PROJECT / "macros.json"

GIT_READS = ("status", "diff", "log", "show", "branch", "remote", "blame", "shortlog",
             "describe", "ls-files", "stash list", "config --get", "rev-parse", "tag")
# a read subcommand still destroys with the right flag: `branch -D old`, `tag -d v1`
GIT_DESTROYS = re.compile(r"(?:^|\s)(?:-[dDmMf]|--delete|--move|--force|--prune|prune)\b")

VERBS = ("key", "type", "focus", "wait")
STEP_HELP = "a step is 'key ctrl+s', 'type hello', 'focus Notepad' or 'wait 0.5'"


def _output(done):
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    if not text:
        return "It ran, with no output."
    return text[:MAX_OUTPUT] + ("\n...(truncated)" if len(text) > MAX_OUTPUT else "")


def _run(args, folder, timeout):
    try:
        return _output(subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                      cwd=folder, creationflags=shell.NO_WINDOW,
                                      encoding="utf-8", errors="replace"))
    except subprocess.TimeoutExpired:
        return f"It ran over {timeout} seconds and was stopped."
    except OSError as e:
        return f"Couldn't start it: {e.strerror or e}"


def _folder(folder):
    """The project to work in — the one named, or Wilco's own. None if it isn't there."""
    where = _resolve(folder) if folder.strip() else str(PROJECT)
    return where if Path(where).is_dir() else None


def git(command, folder=""):
    """Run git in a project. Reading — status, diff, log, show, branch, blame — runs at once
    and returns the output; committing, pushing, resetting, checking out, stashing or
    deleting comes back asking first. command: the git part without the word git, like
    'status -s' or 'log --oneline -10'. folder: the repository, defaults to Wilco's own."""
    command = command.strip().removeprefix("git").strip()
    if not command:
        return "No git command given."
    where = _folder(folder)
    if not where:
        return f"There's no folder at {folder}."
    try:
        args = ["git", *shlex.split(command)]
    except ValueError as e:
        return f"Couldn't read that command: {e}"
    if command.startswith(GIT_READS) and not GIT_DESTROYS.search(command):
        return _run(args, where, 60)
    return _park(f"run git {command} in {where}", lambda: _run(args, where, 120))


def run_tests(folder="", target=""):
    """Run a project's tests and read back what failed — npm test where there is a
    package.json, pytest otherwise. This is the tool for "run my tests" and "did that break
    anything". target: one file or test name to narrow it to. folder: the project, defaults
    to Wilco's own."""
    where = _folder(folder)
    if not where:
        return f"There's no folder at {folder}."
    narrow = target.strip()
    if (Path(where) / "package.json").is_file():
        npm = shutil.which("npm")
        if not npm:
            return "That looks like a Node project, but npm isn't on PATH."
        args = [npm, "test", *(["--", narrow] if narrow else [])]
    else:
        args = [sys.executable, "-m", "pytest", "-q", *([narrow] if narrow else [])]
    return _run(args, where, 300)


def _saved():
    try:
        return json.loads(MACROS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _play(step):
    """Play one line of a macro. ValueError when the line isn't a step."""
    verb, _, rest = step.strip().partition(" ")
    verb, rest = verb.lower(), rest.strip()
    if verb == "key":
        return f"pressed {rest}" if system.press_key(rest) else f"no such key as {rest}"
    if verb == "type":
        system.type_text(rest)
        return f"typed {rest!r}"
    if verb == "focus":
        found = system.focus_window(rest)
        return f"focused {found}" if found else f"no window matching {rest}"
    if verb == "wait":
        try:
            seconds = min(abs(float(rest or 0.3)), 10)
        except ValueError:
            raise ValueError(f"{step!r} — wait needs a number of seconds") from None
        time.sleep(seconds)
        return f"waited {seconds}s"
    raise ValueError(f"{step!r} — {STEP_HELP}")


def list_macros():
    """Every saved macro and the steps it plays. Check here before run_macro when the name
    the user said might not be the one it was saved under."""
    saved = _saved()
    if not saved:
        return "No macros saved yet. Use save_macro to record one."
    return "; ".join(f"{name}: {' then '.join(steps)}" for name, steps in sorted(saved.items()))


def run_macro(name):
    """Play a saved multi-step keyboard workflow — save-then-build, switch-window-then-paste,
    and the like. This is how a run of shortcuts gets one spoken name. The keys land in
    whatever window is in front, so a macro that matters should focus its window first.
    name: one from list_macros."""
    saved = _saved()
    steps = saved.get(name.strip().lower())
    if steps is None:
        return f"No macro called {name}. Saved: {', '.join(sorted(saved)) or 'none'}."
    # not parked for confirmation: press_key and type_text are already tools in their own
    # right, so a macro is a run of calls the model could make one at a time anyway
    done = []
    for step in steps:
        try:
            done.append(_play(step))
        except ValueError as e:
            return f"Stopped after {len(done)} of {len(steps)} steps: {e}"
    return f"Ran {name}: " + "; ".join(done)


def save_macro(name, steps: list[str]):
    """Record a multi-step keyboard workflow under a spoken name, so run_macro can play it
    later. steps: the lines in order, each one of 'key ctrl+s', 'type some words',
    'focus Notepad', 'wait 0.5'. Read them back to the user before saving — a misheard step
    is a keystroke into the wrong window."""
    key = name.strip().lower()
    if not key:
        return "What should the macro be called?"
    if isinstance(steps, str):
        steps = [steps]
    steps = [str(step).strip() for step in steps if str(step).strip()]
    if not steps:
        return f"No steps given — {STEP_HELP}."
    wrong = next((s for s in steps if s.split(" ", 1)[0].lower() not in VERBS), None)
    if wrong:
        return f"{wrong!r} isn't a step — {STEP_HELP}."
    saved = _saved()
    saved[key] = steps
    MACROS.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return f"Saved {key}: {' then '.join(steps)}."


if __name__ == "__main__":
    def reads(command):
        return command.startswith(GIT_READS) and not GIT_DESTROYS.search(command)

    assert reads("status -s")
    assert reads("log --oneline -10")
    assert reads("diff HEAD~1")
    assert reads("config --get user.name")
    assert reads("stash list")
    assert not reads("commit -m 'x'"), "committing must ask first"
    assert not reads("push origin main"), "pushing must ask first"
    assert not reads("config user.name me"), "writing config must ask first"
    assert not reads("stash"), "stashing must ask first"
    assert not reads("branch -D old"), "deleting a branch must ask first"
    assert not reads("tag -d v1"), "deleting a tag must ask first"
    assert not reads("remote prune origin"), "pruning must ask first"

    assert _play("wait 0.01") == "waited 0.01s"
    assert _play("wait") == "waited 0.3s"
    for bad in ("jump around", "", "wait soon"):
        try:
            _play(bad)
            raise AssertionError(f"{bad!r} should not have played")
        except ValueError:
            pass

    assert "isn't a step" in save_macro("x", ["key ctrl+s", "jump"])
    assert "No steps" in save_macro("x", [])
    assert "called" in save_macro("", ["key ctrl+s"])
    assert not MACROS.exists() or "x" not in _saved(), "a rejected macro must not be saved"
    print("ok: git read/write split, macro steps, macro validation")
