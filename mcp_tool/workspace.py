"""Repo and dependency work: check, install and test a project.

The agent used to improvise this with raw run_python — reading requirements, then deciding on
its own to write files or install packages, which is how junk files like "0.42.txt" appeared
from a question that only asked to CHECK something. These tools give it the one right path:

  check_requirements   reads requirements and compares it to what is installed. Read-only.
  install_requirements installs what requirements asks for, and it is parked behind a spoken
                       yes like every other system change.
  run_tests            runs the project's own suite (pytest, else unittest) in place.

The split is the point. Checking is free and runs at once; changing is held until the user
explicitly says so — never because a check "surfaced" something.
"""
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import windows.shell as shell
from config import MAX_OUTPUT, SHELL_TIMEOUT
from mcp_tool.gate import _park

PROJECT = Path(__file__).resolve().parent.parent
REQUIREMENTS_TXT = "requirements.txt"
_PIN = re.compile(r"^\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")
_active_project = PROJECT


def _project(folder=""):
    """Resolve an explicitly named project, or the voice-selected project for this session."""
    candidate = Path(folder).expanduser() if folder and folder.strip() else _active_project
    return candidate.resolve() if candidate.is_dir() else None


def current_project_dir():
    """The folder Wilco currently works in, as text — the voice-selected project, or Wilco's
    own folder before any project is chosen. Never a hardcoded location."""
    return str(_active_project)


def select_project(folder):
    """Set the project Wilco works on for this voice session. Pass a full folder path, for
    example D:/Codes/MyApp. Afterwards 'inspect my project', 'run tests', and 'check
    requirements' use it by default. This only changes Wilco's temporary working scope; it
    does not modify any project file."""
    global _active_project
    chosen = Path(folder).expanduser()
    if not chosen.is_dir():
        return f"There's no project folder at {chosen}."
    _active_project = chosen.resolve()
    return f"Working project set to {_active_project}."


def inspect_project(folder=""):
    """Inspect a project before changing it. Reports its folder, detected language/build
    files, Git state, and likely test command. folder is optional after select_project."""
    project = _project(folder)
    if project is None:
        return f"There's no project folder at {folder}."
    markers = {
        "Python": ("pyproject.toml", REQUIREMENTS_TXT, "setup.py"),
        "Node": ("package.json",), "Java": ("pom.xml", "build.gradle"),
        ".NET": ("*.sln", "*.csproj"), "Rust": ("Cargo.toml",),
        "Go": ("go.mod",),
    }
    detected = [name for name, names in markers.items()
                if any(project.glob(item) for item in names)]
    files = [p.name for p in project.iterdir() if p.is_file()][:20]
    git = "not a Git repository"
    if (project / ".git").exists():
        try:
            done = subprocess.run(["git", "status", "--short"], capture_output=True,
                                  text=True, timeout=15, cwd=project,
                                  creationflags=shell.NO_WINDOW, encoding="utf-8", errors="replace")
            changes = (done.stdout or "").strip().splitlines()
            git = "clean" if not changes else f"{len(changes)} changed file(s): " + "; ".join(changes[:8])
        except (OSError, subprocess.SubprocessError):
            git = "Git state unavailable"
    test_hint = "npm test" if (project / "package.json").is_file() else "python -m pytest -q"
    return (f"Project: {project}. Type: {', '.join(detected) or 'not recognised'}. "
            f"Git: {git}. Suggested tests: {test_hint}. Top-level files: {', '.join(files) or 'none'}.")


def _norm(name):
    """Normalise a distribution name so 'python-dotenv' == 'python_dotenv' == 'Python.Dotenv'."""
    return re.sub(r"[-_.]+", "-", (name or "")).lower().strip()


def _installed():
    """Map normalised dist name -> installed version."""
    out = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if name:
            out[_norm(name)] = dist.version
    return out


def _split(line):
    """A requirement line -> (package name, pinned spec or ''). Drops markers/extras."""
    line = line.split("#", 1)[0].strip()
    if not line:
        return None, ""
    m = _PIN.match(line)
    if not m:
        return None, ""
    name = m.group("name")
    rest = line[m.end():]
    # Strip extras like [x], markers like ; python_version<"3.9", and trailing commas.
    rest = re.split(r"[;\[]", rest, 1)[0].strip().rstrip(",")
    return name, rest


def _version_key(text):
    """A tuple so '2.10' sorts after '2.9'. Unparseable parts are dropped, not fatal."""
    out = []
    for tok in re.split(r"[.+-]", text.split("-", 1)[0]):
        if tok.isdigit():
            out.append(int(tok))
    return tuple(out)


def _v(pkg, spec):
    """Compare an installed version against a pinned spec. Returns 0 same, 1 newer, -1 older,
    or None when it can't be compared (spec has '~=' or no version at all)."""
    if not spec:
        return 0
    numbers = re.findall(r"\d+(?:\.\d+)*", spec.replace(" ", ""))
    if not numbers:
        return None
    want = _version_key(numbers[0])
    have = _version_key(pkg)
    if not have or not want:
        return None
    cmp = (have > want) - (have < want)      # -1 older, 0 equal, 1 newer
    negated = any(op in spec for op in ("!=", "<=", "<"))
    return -cmp if negated else cmp          # "<2" means installed-below-2 is the goal


def _resolve_req(path):
    """The requirements file to act on: a real file wins, otherwise a folder is searched."""
    supplied = Path(path).expanduser() if path and path.strip() else None
    if supplied and supplied.is_file():
        p = supplied
    else:
        base = _project(path) if supplied else _active_project
        if base is None:
            return None
        p = base / REQUIREMENTS_TXT
    if p.is_file():
        return p
    if p.is_dir():
        for candidate in (p / REQUIREMENTS_TXT, p / "Requirements.txt"):
            if candidate.is_file():
                return candidate
        return None
    return None


def _check_single(name, spec, installed):
    """Check one requirement, return (report_line, is_missing, is_outdated)."""
    key = _norm(name)
    if key in installed:
        verdict = _v(installed[key], spec)
        flag = " (OLDER than requested)" if verdict == -1 else ""
        if verdict == -1:
            return f"- {name}: installed {installed[key]}{'  wanted ' + spec if spec else ''}{flag}", False, True
        return f"- {name}: installed {installed[key]}{'  wanted ' + spec if spec else ''}{flag}", False, False
    return f"- {name}: MISSING" + (f"  (wanted {spec})" if spec else ""), True, False


def check_requirements(path=""):
    """Could this project's requirements actually be satisfied here? Reads a requirements.txt
    and compares every package against what is installed, then reports which are in place,
    which are MISSING, and which are older than the version it asks for. Read-only — it
    changes nothing. path: a project folder or a path to a requirements file; empty uses
    Wilco's own requirement. Use this FIRST when asked 'what's missing from requirements' or
    'is everything installed'; only install with install_requirements when they say to."""
    req = _resolve_req(path)
    if req is None:
        return (f"Couldn't find a {REQUIREMENTS_TXT} to check. If it lives somewhere other than "
                "the project root, give me the folder or file path.")
    installed = _installed()
    reports, missing, outdated, listed = [], 0, 0, 0
    for raw in req.read_text(encoding="utf-8", errors="replace").splitlines():
        name, spec = _split(raw)
        if not name:
            continue
        listed += 1
        report, is_missing, is_outdated = _check_single(name, spec, installed)
        reports.append(report)
        if is_missing:
            missing += 1
        elif is_outdated:
            outdated += 1
    if not listed:
        return f"{req} has no package lines to check."
    head = (f"{req} ({listed} packages): {missing} missing, {outdated} outdated."
            if missing or outdated
            else f"{req} ({listed} packages): all installed and up to date.")
    order = sorted(reports, key=lambda r: (0 if "MISSING" in r else 1, r.lower()))
    return head + "\n" + "\n".join(order[:60]) + ("\n...(more)" if len(order) > 60 else "")


def install_requirements(path="", upgrade=False):
    """Install every package a requirements.txt asks for, using pip. ALWAYS asks first — this
    call installs nothing on its own. Call it ONLY because the user asked to install, never
    because a check_report 'showed' something missing. path: a project folder or the file;
    empty uses Wilco's own requirement. upgrade: True re-installs the latest matching version
    instead of only what is absent."""
    req = _resolve_req(path)
    if req is None:
        return (f"There's no {REQUIREMENTS_TXT} to install from. Give me the project folder or "
                "the file path.")
    python = sys.executable or "python"
    args = [python, "-m", "pip", "install", "-r", str(req)]
    if upgrade:
        args.append("--upgrade")
    return _park(f"install or update the packages listed in {req}"
                 + (" (upgrading to newest)" if upgrade else ""),
                 lambda: _run_pip(args))


def _run_pip(args):
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              timeout=SHELL_TIMEOUT + 120, cwd=PROJECT,
                              creationflags=shell.NO_WINDOW, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "pip install ran over the time limit and was stopped."
    except OSError as e:
        return f"Couldn't run pip: {e.strerror or e}"
    out = ((done.stdout or "") + (done.stderr or "")).strip()
    tail = out[-MAX_OUTPUT:] if out else "It finished, with no output."
    return tail + (f"\n...(earlier output trimmed, exit was {done.returncode})"
                   if len(out) > MAX_OUTPUT else "")


def run_tests(folder="", runner=""):
    """Run a project's test suite and read back the result. Looks for pytest first, else
    unittest discover, in the given folder (default Wilco's own). This is how to check a code
    change works without asking the user to run anything — run it after an edit and report the
    pass/fail numbers. runner: 'pytest' or 'unittest' to force one."""
    where = _project(folder)
    if where is None:
        return f"There's no folder at {folder}."
    python = sys.executable or "python"
    command = [python, "-m", "pytest", "-q"] if runner != "unittest" else [python, "-m", "unittest"]
    if runner not in ("pytest", "unittest"):
        # pick pytest only if this project actually has pytest on it
        try:
            import pytest  # noqa: F401
        except Exception:
            command = [python, "-m", "unittest"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, cwd=str(where),
                              timeout=120, creationflags=shell.NO_WINDOW,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "The tests ran over two minutes and were stopped."
    except OSError as e:
        return f"Couldn't start the tests: {e.strerror or e}"
    out = ((done.stdout or "") + (done.stderr or "")).strip()
    tail = out[-MAX_OUTPUT:] if out else "It ran, with no output."
    summary = "Tests passed." if done.returncode == 0 else f"Tests FAILED (exit {done.returncode})."
    return summary + ((" " + tail) if tail else "")
