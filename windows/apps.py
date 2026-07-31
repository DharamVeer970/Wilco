import ctypes
import os
import re
import winreg
from ctypes import wintypes
from functools import lru_cache

import win32com.client
from rapidfuzz import fuzz, process

_shlwapi = ctypes.windll.shlwapi
_shlwapi.SHLoadIndirectString.argtypes = [
    wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.UINT, ctypes.c_void_p
]

FUZZ_MIN = 70

ALIASES = {
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "code": "visual studio code",
    "chrome": "google chrome",
    "cmd": "command prompt",
    "explorer": "file explorer",
    "powershell": "windows powershell",
    "vlc": "vlc media player",
    "task manager": "task manager",
}


@lru_cache(maxsize=1)
def index():
    """{lowercase name: (display name, launch id)} for every app Windows can launch."""
    # ponytail: cached for the session, so restart Jarvis to pick up new installs
    shell = win32com.client.Dispatch("Shell.Application")
    return {i.Name.lower(): (i.Name, i.Path) for i in shell.NameSpace("shell:AppsFolder").Items()}


def _hits(name, limit):
    apps = index()
    if name in apps:
        return [name]
    word = re.compile(rf"\b{re.escape(name)}", re.I)
    found = sorted((k for k in apps if word.search(k)), key=len)
    if found:
        return found[:limit]
    keys = list(apps)
    for probe in dict.fromkeys((name, name.replace(" ", ""))):
        scored = process.extract(probe, keys, scorer=fuzz.ratio,
                                 score_cutoff=FUZZ_MIN, limit=limit)
        if scored:
            return [k for k, _, _ in scored]
    return []


def find(name):
    """Best (display name, launch id) for a spoken app name, or None."""
    name = ALIASES.get(name, name)
    hits = _hits(name, 1)
    return index()[hits[0]] if hits else None


def candidates(name, limit=4):
    """Every plausible app for a spoken name, best first — for asking which one."""
    name = ALIASES.get(name, name)
    apps = index()
    return [apps[h] for h in _hits(name, limit)]


def launch(launch_id):
    os.startfile("shell:AppsFolder\\" + launch_id)


def _indirect(s):
    """Resolve an @{Package?ms-resource:...} string to real text."""
    if not s or not s.startswith("@"):
        return s
    buf = ctypes.create_unicode_buffer(1024)
    return buf.value if _shlwapi.SHLoadIndirectString(s, buf, 1024, None) == 0 else None


def _progids(ext):
    ids = set()
    for hive, path in (
        (winreg.HKEY_CLASSES_ROOT, ext + r"\OpenWithProgids"),
        (winreg.HKEY_CURRENT_USER,
         rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}\OpenWithProgids"),
    ):
        try:
            with winreg.OpenKey(hive, path) as k:
                ids.update(
                    v for v, *_ in (winreg.EnumValue(k, i)
                                    for i in range(winreg.QueryInfoKey(k)[1])) if v
                )
        except OSError:
            pass
    return ids


def _app_for(progid):
    """(display name, exe path) that a ProgID opens with, or None."""
    exe = None
    try:
        cmd = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, progid + r"\shell\open\command")
        found = re.findall(r'"([^"]+\.exe)"|(\S+\.exe)', cmd, re.I)
        exe = next((a or b for a, b in found), None)
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r"\Application") as k:
            name = _indirect(winreg.QueryValueEx(k, "ApplicationName")[0])
            if name:
                return name, exe
    except OSError:
        pass
    if exe:
        hit = find(os.path.splitext(os.path.basename(exe))[0].lower())
        if hit:
            return hit[0], exe
    return None


@lru_cache(maxsize=None)
def openers(exts):
    """[(app name, exe)] Windows says can open these extensions. Discovered, not guessed."""
    seen = {}
    for ext in exts:
        for progid in _progids(ext):
            hit = _app_for(progid)
            if hit and hit[0] not in seen:
                seen[hit[0]] = hit[1]
    return sorted(seen.items())
