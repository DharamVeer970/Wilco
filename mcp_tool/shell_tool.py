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
import re

import windows.shell as shell
from mcp_tool.gate import _park

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
