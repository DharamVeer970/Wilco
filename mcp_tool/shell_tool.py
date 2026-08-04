"""PowerShell, split into what may run instantly and what must be confirmed out loud.

The split matters because the input is speech. Whisper mishears, and the model composes
the command from what it heard — so a misheard sentence must never be able to delete or
reconfigure anything without a spoken yes. Reading is free; changing is not.

To run without asking, a command must:
  - start with something on READ_ONLY,
  - contain no word from CHANGES anywhere in it,
  - contain no redirect or statement separator that could smuggle a second command in.
Anything else is parked for confirmation. False alarms only cost one extra question.
"""
import os
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import windows.shell as shell
from mcp_tool.gate import _park

PROJECT = str(Path(__file__).resolve().parent.parent)

# Python that changes something rather than just looking. Deliberately over-eager: a false
# alarm costs one extra question, a miss costs the user a file. Same bargain as the
# PowerShell split above.
PY_MUTATES = re.compile(
    r"open\s*\([^)]*['\"][waxb+]"                       # open(path, "w") and friends
    r"|\bos\.(?:system|remove|unlink|rmdir|removedirs|mkdir|makedirs|rename|replace|"
    r"startfile|chmod|chown|kill|popen|truncate)\b"
    r"|\bshutil\.\w+"
    r"|\bsubprocess\b|\bPopen\b|\bcheck_call\b|\bcheck_output\b"
    r"|\.write\s*\(|\.writelines\s*\(|\.truncate\s*\("  # writing through a handle
    r"|\.(?:post|put|patch|delete)\s*\(|\.send\w*\s*\("  # sending things outward
    r"|keybd_event|SetForegroundWindow|ShowWindow|SetCursorPos|mouse_event"
    r"|\btaskkill\b|\bshutdown\b|\bpress_key\b|\btype_text\b"
    r"|winreg\.(?:Set|Delete|Create)\w*"
    r"|\bexec\s*\(|\beval\s*\(|__import__"
    r"|\bpip\b",
    re.I)

MAX_OUTPUT = 3000

READ_ONLY = re.compile(
    r"^\s*\(?\s*(?:get-|test-|resolve-|measure-|select-|compare-|convertto-|convertfrom-|"
    r"find-|show-|read-|out-string|format-|sort-|group-|"
    r"ipconfig|systeminfo|tasklist|hostname|whoami|ver|netstat|ping|tracert|nslookup|arp|"
    r"getmac|driverquery|dir|ls|gci|type|cat|echo|write-output|write-host|date|time|vol|"
    r"tree|df|du|where|which|wmic\b(?=.*\bget\b)|net\s+(?:view|statistics|time)|"
    r"powercfg\s+/(?:query|list|batteryreport)|"
    r"query\s+(?:user|session)|schtasks\s*(?:/query)?|sc\s+query)",
    re.I)

CHANGES = re.compile(
    r"\b(?:remove|rm|del|delete|erase|rd|rmdir|format|clear|clean|"
    r"set|new|add|update|install|uninstall|enable|disable|"
    r"stop|start|restart|suspend|resume|kill|taskkill|shutdown|logoff|"
    r"move|mv|copy|cp|rename|ren|mkdir|md|touch|"
    r"reg|regedit|net\s+user|netsh|bcdedit|diskpart|cipher|takeown|icacls|attrib|"
    r"invoke-expression|invoke-webrequest|iex|iwr|curl|wget|"
    r"out-file|set-content|add-content|export)\b",
    re.I)

# a separator or redirect can hide a second, unvetted command behind a harmless-looking first
SMUGGLE = re.compile(r"[;>&`]|\$\(|\|\s*%|\bthen\b")


def _is_read_only(command):
    return bool(READ_ONLY.search(command)) and not CHANGES.search(command) \
        and not SMUGGLE.search(command)


def _execute(command):
    output = shell.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command])
    if not output:
        return "It ran, with no output."
    return output[:MAX_OUTPUT] + ("\n...(truncated)" if len(output) > MAX_OUTPUT else "")


def run_powershell(command):
    """Run a PowerShell command on this machine. This is the escape hatch for anything the
    other tools don't cover — services, processes, network config, registry, scheduled tasks,
    installed packages, hardware details.

    Read-only commands (Get-*, ipconfig, systeminfo, tasklist, ping, dir...) run immediately
    and return their output. Anything that writes, deletes, installs or reconfigures is NOT
    run: it comes back asking for confirmation. When that happens, tell the user plainly what
    the command would do, then call confirm_yes only if they agree.

    Prefer the purpose-built tools when one fits — they are faster and give better answers."""
    command = command.strip()
    if not command:
        return "No command given."
    if _is_read_only(command):
        return _execute(command)
    return _park(f"run this PowerShell: {command}", lambda: _execute(command))


HOME = os.path.expanduser("~")

# Git for Windows ships a full GNU userland. Nothing new to install, and it is what makes
# "find every python file mentioning X" a single command instead of a directory walk.
BASH_READS = re.compile(
    r"^\s*\(?\s*(?:ls|ll|find|grep|egrep|fgrep|rg|cat|head|tail|wc|sort|uniq|cut|awk|nl|"
    r"basename|dirname|realpath|readlink|stat|file|du|df|tree|pwd|echo|printf|which|type|"
    r"date|whoami|hostname|env|printenv|ps|seq|tr|diff|cmp|md5sum|sha256sum|rev|tac|"
    r"command\s+-v|where|whereis|locate|uname|id|groups|df|free|uptime|"
    # sed only writes with -i, which BASH_CHANGES catches; sed -n and sed -e just print
    r"sed|jq|strings|xxd|od|comm|join|paste|fold|expand|column|zcat|"
    r"xargs\s+(?:grep|ls|cat|wc|stat|file))\b", re.I)
BASH_CHANGES = re.compile(
    r"\b(?:rm|rmdir|mv|cp|dd|touch|mkdir|chmod|chown|chgrp|ln|tee|truncate|shred|"
    r"kill|pkill|killall|reboot|shutdown|halt|mount|umount|"
    r"curl|wget|scp|rsync|ssh|nc|netcat|"
    r"npm|pip|apt|yum|brew|choco|winget|"
    r"export|unset|source|eval|exec|sudo)\b"
    r"|\bgit\s+(?:commit|push|reset|checkout|clean|rm|mv|restore|stash)\b"
    r"|-delete\b|-exec\b|-execdir\b|-ok\b"
    # sed edits in place via -i, --in-place, or a clustered flag like -ni. Matching only
    # " -i" missed the other two, which would have rewritten files without asking.
    r"|\bsed\b[^|]*\s-{1,2}[a-z]*i", re.I)
# 2>/dev/null and 2>&1 are noise suppression, not a second hidden command
_STDERR_NOISE = re.compile(r"2>\s*(?:/dev/null|&1)")
BASH_SMUGGLE = re.compile(r"[;>&`]|\$\(")


def _is_plain_read(command):
    stripped = _STDERR_NOISE.sub("", command)
    return (bool(BASH_READS.search(stripped)) and not BASH_CHANGES.search(stripped)
            and not BASH_SMUGGLE.search(stripped))


@lru_cache(maxsize=1)
def _bash_exe():
    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe",
                      r"C:\Program Files\Git\usr\bin\bash.exe"):
        if os.path.isfile(candidate):
            return candidate
    # System32\bash.exe is WSL, which may not have a distro installed — Git's is the safe bet
    return shutil.which("bash")


def _execute_bash(command, folder):
    exe = _bash_exe()
    if not exe:
        return "Git Bash isn't installed, so there's no bash to run this in."
    try:
        done = subprocess.run(
            [exe, "-c", command], capture_output=True, text=True, timeout=90,
            cwd=folder if os.path.isdir(folder) else HOME,
            creationflags=shell.NO_WINDOW, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "That search ran over 90 seconds and was stopped. Narrow it to a folder."
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    if not output:
        return "It ran and found nothing."
    lines = output.splitlines()
    trimmed = "\n".join(lines[:60])
    return trimmed + (f"\n...and {len(lines) - 60} more lines" if len(lines) > 60 else "")


def run_bash(command, folder=""):
    """Search the file system with GNU tools — find, grep, ls, wc, du, head, sort, and pipes.

    This is how you look for files by name, pattern or CONTENT, across any file type, which
    find_files cannot do (it only knows music, video, image and document files).

        find . -name "*.py" | head -20
        grep -ril "api_key" --include=*.py .
        ls -lh Downloads | sort -k5 -h | tail -5
        du -sh */ | sort -h
        find . -name "*.log" -mtime -7

    folder: where to search from — a Windows path like D:/Codes works. Defaults to the user's
    home folder. Paths may be written C:/Users/... or /c/Users/... — both work.

    Reading commands run immediately. Anything that removes, moves, copies, downloads or
    installs is NOT run: it comes back asking first. Say what it would do in plain words,
    then call confirm_yes only if the user agrees."""
    command = command.strip()
    if not command:
        return "No command given."
    where = folder.strip() or HOME
    if _is_plain_read(command):
        return _execute_bash(command, where)
    return _park(f"run this in bash, under {where}: {command}",
                 lambda: _execute_bash(command, where))


def _execute_python(code):
    try:
        done = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
            cwd=PROJECT, creationflags=shell.NO_WINDOW, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return "That took over a minute and was stopped. Try something smaller."
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    if not output:
        return "It ran, but printed nothing. Add a print() to see a result."
    return output[:MAX_OUTPUT] + ("\n...(truncated)" if len(output) > MAX_OUTPUT else "")


def run_python(code):
    """Run a snippet of Python on this machine and read back whatever it prints.

    This is how you inspect and diagnose things no other tool covers: enumerate windows,
    look through the file system, parse a file, do arithmetic on real data, check why
    something misbehaved. It runs inside Wilco's own project folder, so it can import
    Wilco's own machinery and use it directly:

        import windows.system as sy; print(sy.windows_matching(''))
        import windows.apps as ap;   print(ap.find('spotify'))
        import windows.shell as sh;  print(sh.running_apps())
        import mcp_tool.ui as ui;    print(ui.list_controls())

    You must print() what you want to see — the return value alone is not captured.

    Code that only reads runs immediately. Anything that writes, deletes, installs, sends or
    drives the keyboard is NOT run: it comes back asking, and you relay the question in plain
    words before calling confirm_yes. Prefer a purpose-built tool when one fits."""
    code = code.strip()
    if not code:
        return "No code given."
    if not PY_MUTATES.search(code):
        return _execute_python(code)
    return _park(f"run this Python: {code}", lambda: _execute_python(code))
