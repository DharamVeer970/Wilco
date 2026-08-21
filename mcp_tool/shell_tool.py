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
from config import MAX_OUTPUT
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
    r"|\.write_text\s*\(|\.write_bytes\s*\(|\.mkdir\s*\(|\.touch\s*\("  # pathlib writes
    r"|\.unlink\s*\(|\.rmdir\s*\(|\.rename\s*\(|\.symlink_to\s*\(|\.hardlink_to\s*\("
    r"|json\.dump\s*\(|pickle\.dump\s*\("
    r"|\.(?:post|put|patch|delete)\s*\(|\.send\w*\s*\("  # sending things outward
    r"|keybd_event|SetForegroundWindow|ShowWindow|SetCursorPos|mouse_event"
    r"|\btaskkill\b|\bshutdown\b|\bpress_key\b|\btype_text\b"
    r"|winreg\.(?:Set|Delete|Create)\w*"
    r"|\bexec\s*\(|\beval\s*\(|__import__"
    r"|\bpip\b",
    re.I)

# Routine Python can run directly. These forms can destroy/overwrite data, execute an
# arbitrary child command, install code, change the registry, or send data outward.
PY_CRITICAL = re.compile(
    r"\b(?:os\.(?:remove|unlink|rmdir|removedirs|replace)|shutil\.(?:rmtree|move)|"
    r"winreg\.(?:Set|Delete|Create)\w*|subprocess\.(?:run|call|Popen|check_call|check_output)|"
    r"os\.system|(?:pip|venv)\b|(?:requests|httpx)\.(?:post|put|patch|delete)|"
    r"\.send\w*\s*\(|\.write(?:_text|_bytes|lines)?\s*\(|\.truncate\s*\(|"
    r"open\s*\([^)]*['\"][wax+])",
    re.I)


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
NETSH_STATUS = re.compile(r"^\s*netsh\s+wlan\s+show\s+(?:interfaces|profiles)\s*$", re.I)
POWERSHELL_CRITICAL = re.compile(
    r"\b(?:remove-item|\brm\b|\bdel\b|erase|rmdir|format(?:-volume)?|clear-disk|"
    r"clear-recyclebin|diskpart|bcdedit|cipher|manage-bde|bitlocker|shutdown|"
    r"restart-computer|stop-computer|restart|logoff|set-executionpolicy|set-acl|icacls|"
    r"takeown|reg(?:\.exe)?\s+(?:add|delete)|(?:new|set|remove)-(?:localuser|localgroup|"
    r"localgroupmember)|net\s+user|install|uninstall|winget|choco|msiexec|key\s*=\s*clear|"
    r"out-file|set-content|add-content|export-(?:csv|clixml)|git\s+(?:reset\s+--hard|clean|push))\b|>{1,2}",
    re.I)


def _is_read_only(command):
    if SMUGGLE.search(command):
        return False
    # `netsh` also changes Wi-Fi settings, but these two forms only list status/profile names.
    if NETSH_STATUS.fullmatch(command):
        return True
    return bool(READ_ONLY.search(command)) and not CHANGES.search(command)


def _powershell_needs_confirmation(command):
    """Only high-impact PowerShell actions wait for a separate spoken yes."""
    return bool(POWERSHELL_CRITICAL.search(command))


def _execute(command):
    output = shell.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command])
    if not output:
        return "It ran, with no output."
    return output[:MAX_OUTPUT] + ("\n...(truncated)" if len(output) > MAX_OUTPUT else "")


def run_powershell(command):
    """Run PowerShell on this machine — the escape hatch for services, processes, network
    config, registry, scheduled tasks, installed packages and hardware. Routine commands run
    immediately; destructive, security-sensitive, install, power and credential-revealing
    commands are parked only while confirmations are on; all-access mode (the default) runs
    them. Prefer a purpose-built tool when one fits. For screen brightness or speaker
    volume always use set_screen_brightness / change_volume — never WMI classes recalled
    from memory, which usually don't exist on the machine."""
    command = command.strip()
    if not command:
        return "No command given."
    if _powershell_needs_confirmation(command):
        return _park(f"run this PowerShell: {command}", lambda: _execute(command))
    return _execute(command)


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
BASH_CRITICAL = re.compile(
    r"\b(?:rm|rmdir|shred|truncate|dd|mkfs|fdisk|parted|chmod|chown|chgrp|"
    r"shutdown|reboot|halt|sudo|mount|umount|npm|pip|apt|yum|brew|choco|winget|"
    r"curl\s+[^|]*\|\s*(?:ba)?sh|wget\s+[^|]*\|\s*(?:ba)?sh)\b|"
    r"\bgit\s+(?:reset\s+--hard|clean|push)\b|-{1,2}delete\b|>{1,2}|\btee\b",
    re.I)


def _is_plain_read(command):
    stripped = _STDERR_NOISE.sub("", command)
    return (bool(BASH_READS.search(stripped)) and not BASH_CHANGES.search(stripped)
            and not BASH_SMUGGLE.search(stripped))


def _bash_needs_confirmation(command):
    """Only high-impact Bash actions wait for a separate spoken yes."""
    return bool(BASH_CRITICAL.search(command))


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
    """Search the file system with find, grep, ls, wc, du, sort and pipes. This is how you
    look for files by name, pattern or CONTENT, across any file type — find_files only knows
    music, video, image and document files. folder: where to search from, a Windows path like
    D:/Codes works, defaults to home; C:/Users/... and /c/Users/... both work. Routine commands
    run at once; destructive, privilege-changing, or installation commands are parked only while
    confirmations are on; all-access mode (the default) runs them. Prefer a purpose-built tool
    when one fits."""
    command = command.strip()
    if not command:
        return "No command given."
    where = folder.strip() or HOME
    if _bash_needs_confirmation(command):
        return _park(f"run this in bash, under {where}: {command}",
                     lambda: _execute_bash(command, where))
    return _execute_bash(command, where)


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
    """Run Python on this machine and read back what it prints. For inspecting or diagnosing
    anything no other tool covers. Runs inside Wilco's own folder, so it can import and use
    windows.system, windows.apps, windows.shell and mcp_tool.ui directly. You MUST print()
    what you want to see. Routine code runs at once; data-destructive, install, outbound, or
    arbitrary child-process code is parked only while confirmations are on;
    all-access mode (the default) runs it."""
    code = code.strip()
    if not code:
        return "No code given."
    if PY_CRITICAL.search(code):
        return _park(f"run this Python: {code}", lambda: _execute_python(code))
    return _execute_python(code)
