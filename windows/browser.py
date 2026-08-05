"""Opening browser windows through the browser's own command line, not through its menus.

A private window is a switch the browser accepts at launch — msedge --inprivate, chrome
--incognito, firefox -private-window. Going through the menu instead means finding "Settings
and more", opening it, waiting for it to draw, and hoping focus stays put for the whole
sequence. It usually doesn't: a menu is a separate popup window, it isn't in the parent
window's control tree until it opens, and anything that steals focus mid-way sends the
keystroke somewhere else entirely. The switch needs none of that and cannot land in the
wrong window.

Browsers are located through App Paths, where every installer registers its exe. Both hives
are checked because Chrome and Brave install per-user under HKCU while Edge sits in HKLM.
"""
import os
import shutil
import subprocess
import time
import winreg

import config
import windows.system as system

APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
USER_CHOICE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"

BROWSERS = {
    "edge": ("msedge.exe", "--inprivate", "--new-window", "inprivate", "edge"),
    "chrome": ("chrome.exe", "--incognito", "--new-window", "incognito", "chrome"),
    "brave": ("brave.exe", "--incognito", "--new-window", "private", "brave"),
    "vivaldi": ("vivaldi.exe", "--incognito", "--new-window", "private", "vivaldi"),
    "opera": ("opera.exe", "--private", "--new-window", "private", "opera"),
    "firefox": ("firefox.exe", "-private-window", "-new-window", "private", "firefox"),
}


def path(name):
    """Where a browser's exe actually is, or None if it isn't installed."""
    exe = BROWSERS[name][0]
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"{APP_PATHS}\{exe}") as key:
                found = winreg.QueryValueEx(key, "")[0].strip('" ')
        except OSError:
            continue
        if found and os.path.isfile(found):
            return found
    return shutil.which(exe)


def installed():
    """Every browser on this machine, the user's default one first."""
    found = [name for name in BROWSERS if path(name)]
    preferred = default()
    if preferred in found:
        found.remove(preferred)
        found.insert(0, preferred)
    return found


def default():
    """Which browser Windows opens https links with — the user's own choice, not a guess."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_CHOICE) as key:
            progid = winreg.QueryValueEx(key, "ProgId")[0].lower()
    except OSError:
        progid = ""
    named = next((name for name in BROWSERS if name in progid), None)
    return named if named and path(named) else next((n for n in BROWSERS if path(n)), None)


def resolve(name):
    """Match a spoken browser name to an installed one. None if it isn't here."""
    wanted = (name or "").strip().lower()
    if not wanted:
        return default()
    if wanted in BROWSERS:
        return wanted if path(wanted) else None
    return next((n for n in BROWSERS if n in wanted or wanted in n), None)


def open_window(name="", private=False, url=""):
    """Open a new browser window, private or not.

    Returns (browser, title, looked_private, reused). The title is read back off the window
    that actually appeared, so success is observed rather than assumed — looked_private says
    whether that window names itself InPrivate or Incognito, which is the only proof from
    outside that the switch took.

    reused covers the case that looks like failure and isn't: when a private window is already
    open, Edge and Chrome put a new TAB in it rather than building a second window. Nothing
    new appears, so waiting for a new window would time out and report nothing happened, when
    in fact the browser did exactly what was asked.
    """
    chosen = resolve(name)
    if not chosen:
        raise LookupError(name)
    exe = path(chosen)
    if not exe:
        raise FileNotFoundError(chosen)
    _, private_flag, window_flag, mark, brand = BROWSERS[chosen]
    command = [exe, private_flag if private else window_flag]
    if url:
        command.append(url if "://" in url else f"https://{url}")

    wanted_exe = os.path.basename(exe).lower()

    def its_windows():
        return [(hwnd, title) for hwnd, title in system.windows_matching("")
                if brand in title.lower() and system.window_exe(hwnd) == wanted_exe]

    before = {hwnd for hwnd, _ in its_windows()}
    subprocess.Popen(command, close_fds=True)
    deadline = time.monotonic() + config.BROWSER_WAIT
    newest, settled = "", None
    while time.monotonic() < deadline:
        fresh = [title for hwnd, title in its_windows() if hwnd not in before]
        marked = next((t for t in fresh if mark in t.lower()), "")
        if marked:
            return chosen, marked, True, False
        if fresh:
            newest = fresh[0]
            if not private:
                return chosen, newest, False, False
            # the window is up but hasn't named itself private yet, so give the title a
            # moment to settle rather than waiting out the whole appearance deadline
            settled = settled or time.monotonic() + config.BROWSER_GRACE
            if time.monotonic() >= settled:
                break
        time.sleep(0.25)
    already = next((t for _, t in its_windows() if mark in t.lower()), "")
    if private and already:
        return chosen, already, True, True
    return chosen, newest, False, False
