import ctypes
import os
import re
import shutil
import string
import subprocess
from ctypes import wintypes

from rapidfuzz import fuzz, process

TIMEOUT = 25
NO_WINDOW = subprocess.CREATE_NO_WINDOW
FUZZ_MIN = 70

# never close these — Windows dies with them
CRITICAL = {"csrss", "winlogon", "wininit", "services", "lsass", "smss", "system", "explorer"}


def run(cmd, timeout=TIMEOUT):
    """Run a command and return its text output, or '' if it fails."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, creationflags=NO_WINDOW)
        return (done.stdout or done.stderr).strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def ip_address():
    found = re.findall(r"IPv4 Address[.\s]*:\s*([\d.]+)", run(["ipconfig"]))
    return found[0] if found else None


def computer_name():
    return run(["hostname"]) or None


def wifi_status():
    out = run(["netsh", "wlan", "show", "interfaces"])
    state = re.search(r"^\s*State\s*:\s*(.+)$", out, re.M)
    ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
    signal = re.search(r"^\s*Signal\s*:\s*(\d+%)", out, re.M)
    if not state:
        return None
    if ssid:
        return f"connected to {ssid.group(1).strip()} at {signal.group(1) if signal else 'unknown'} signal"
    return state.group(1).strip()


def running_apps(limit=8):
    rows = run(["tasklist", "/fo", "csv", "/nh"]).splitlines()
    names, seen = [], set()
    for row in rows:
        name = row.split('","')[0].strip('"').removesuffix(".exe")
        mem = row.split('","')[-1].strip('" K').replace(",", "")
        if name.lower() in seen or not mem.isdigit() or int(mem) < 60000:
            continue
        seen.add(name.lower())
        names.append(name)
    return names[:limit]


def _best_image(name, stems):
    """Pick the running process image that best matches a spoken app name, or None."""
    name = name.lower().strip().removesuffix(".exe")
    if not name:
        return None  # "" is a substring of every process name — would match at random
    safe = [s for s in stems if s not in CRITICAL]
    # "chrome" sits inside "google chrome" — longest wins; "code" inside "vscode" — shortest wins
    hit = (max((s for s in safe if s in name), key=len, default=None)
           or min((s for s in safe if name in s), key=len, default=None))
    if not hit:
        best = process.extractOne(name, safe, scorer=fuzz.ratio, score_cutoff=FUZZ_MIN)
        hit = best[0] if best else None
    return stems[hit] if hit else None


def close_app(name):
    """Ask the best-matching running app to close. Returns its image name, or None."""
    stems = {}
    for row in run(["tasklist", "/fo", "csv", "/nh"]).splitlines():
        image = row.split('","')[0].strip('"')
        if image.lower().endswith(".exe"):
            stems[image[:-4].lower()] = image
    image = _best_image(name, stems)
    if image:
        run(["taskkill", "/IM", image])  # no /F, so unsaved work still gets its prompt
    return image


def disk_free():
    """(drive, free GB, total GB) per drive — stdlib, so no wmic and no subprocess."""
    drives = []
    for letter in string.ascii_uppercase:
        try:
            use = shutil.disk_usage(f"{letter}:\\")
        except OSError:
            continue
        drives.append((f"{letter}:", round(use.free / 1e9), round(use.total / 1e9)))
    return drives


def battery_percent():
    out = run(["wmic", "path", "Win32_Battery", "get", "EstimatedChargeRemaining"])
    found = re.findall(r"\b(\d{1,3})\b", out)
    return int(found[0]) if found else None


def uptime():
    since = re.search(r"since\s+(.+)$", run(["net", "statistics", "workstation"]), re.M)
    return since.group(1).strip() if since else None


def ping(host):
    out = run(["ping", "-n", "2", host], timeout=15)
    loss = re.search(r"\((\d+)% loss\)", out)
    avg = re.search(r"Average = (\d+ms)", out)
    if not loss:
        return None
    return f"{host} replied, average {avg.group(1)}" if loss.group(1) == "0" else f"{host} is not reachable"


def lock():
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])


def sleep():
    # ponytail: hibernates instead of sleeping when hibernation is on — `powercfg /h off` to change
    subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 0x0003
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 0x0004, 0x0010, 0x0040


def recycle(path):
    """Send a file to the recycle bin. Recoverable — never a hard delete."""
    if not os.path.exists(path):
        return f"{path} isn't there any more."
    op = _SHFILEOPSTRUCTW(
        hwnd=None, wFunc=FO_DELETE,
        pFrom=path + "\0\0",  # the API expects a double-null-terminated list
        pTo=None, fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT,
        fAnyOperationsAborted=False, hNameMappings=None, lpszProgressTitle=None)
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if code != 0 or op.fAnyOperationsAborted:
        return f"Windows refused to delete it (code {code})."
    return "It's in the recycle bin, so it can be restored."


def empty_recycle_bin():
    return run(["powershell", "-NoProfile", "-Command", "Clear-RecycleBin -Force"]) == ""


def shutdown(restart=False, delay=30):
    return run(["shutdown", "/r" if restart else "/s", "/t", str(delay)]) is not None


def cancel_shutdown():
    return run(["shutdown", "/a"]) is not None


if __name__ == "__main__":
    assert any(c == "C:" and 0 < free <= total for c, free, total in disk_free()), disk_free()
    _demo = {"chrome": "chrome.exe", "code": "Code.exe", "csrss": "csrss.exe", "notepad": "notepad.exe"}
    assert _best_image("Google Chrome", _demo) == "chrome.exe"
    assert _best_image("Visual Studio Code", _demo) == "Code.exe"
    assert _best_image("notepad.exe", _demo) == "notepad.exe"
    assert _best_image("csrss", {"csrss": "csrss.exe"}) is None, "must never target a critical process"
    assert _best_image("qqqq zzzz", _demo) is None
    print("ok:", disk_free(), ip_address(), computer_name(), battery_percent())
