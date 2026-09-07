import ctypes
import os
import re
import subprocess
import threading
import time
import uuid
from ctypes import wintypes

import win32api
import win32clipboard
import win32com.client
import win32con
import win32gui
import win32process

VK = {"mute": 0xAD, "down": 0xAE, "up": 0xAF,
      "next": 0xB0, "previous": 0xB1, "stop": 0xB2, "play_pause": 0xB3}
KEYUP = 0x0002
VK_LWIN, VK_S, VK_CTRL, VK_ALT, VK_W, VK_F4 = 0x5B, 0x53, 0x11, 0x12, 0x57, 0x73
NO_WINDOW = subprocess.CREATE_NO_WINDOW  # else every shell-out flashes a black console
PROCESS_QUERY_LIMITED = 0x1000

# named keys the agent can press by voice — separate from VK, whose up/down are volume
KEYS = {"enter": 0x0D, "return": 0x0D, "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
        "space": 0x20, "spacebar": 0x20, "backspace": 0x08, "back": 0x08,
        "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pgup": 0x21,
        "pagedown": 0x22, "pgdn": 0x22, "capslock": 0x14, "printscreen": 0x2C,
        "menu": 0x5D, "apps": 0x5D}
KEYS.update({f"f{n}": 0x6F + n for n in range(1, 13)})          # F1 = 0x70 ... F12 = 0x7B
KEYS.update({c: ord(c.upper()) for c in "abcdefghijklmnopqrstuvwxyz"})  # letters: 'A' = 0x41
KEYS.update({d: ord(d) for d in "0123456789"})                  # digits: '0' = 0x30
KEYS["refresh"] = KEYS["f5"]

# Held while another key taps — combos like ctrl+a are impossible as two separate keystrokes.
MODIFIERS = {"ctrl": VK_CTRL, "control": VK_CTRL, "ctl": VK_CTRL,
             "alt": VK_ALT, "shift": 0x10,
             "win": VK_LWIN, "windows": VK_LWIN, "super": VK_LWIN, "meta": VK_LWIN}
_KEY_SPLIT = re.compile(r"[\s+\-]+")

# Windows known-folder GUIDs — resolved at runtime so redirected paths still work
FOLDER_IDS = {
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD),
                ("d3", wintypes.WORD), ("d4", ctypes.c_byte * 8)]


_shell32 = ctypes.windll.shell32
_shell32.SHGetKnownFolderPath.argtypes = [
    ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)
]
_user32 = ctypes.windll.user32


def folder(name):
    """Real path of a known folder, or None."""
    guid = FOLDER_IDS.get(name.lower().replace(" folder", "").strip())
    if not guid:
        return None
    buf = ctypes.c_wchar_p()
    g = _GUID.from_buffer_copy(uuid.UUID(guid).bytes_le)
    if _shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
        return buf.value
    return None


def open_folder(name):
    path = folder(name)
    if not path or not os.path.isdir(path):
        return None
    os.startfile(path)
    return path


def _tap(vk, times=1):
    for _ in range(times):
        _user32.keybd_event(vk, 0, 0, 0)
        _user32.keybd_event(vk, 0, KEYUP, 0)


def _combo(modifier, vk):
    """Hold a modifier, tap a key, release it — goes to whatever window has focus."""
    _user32.keybd_event(modifier, 0, 0, 0)
    _tap(vk)
    _user32.keybd_event(modifier, 0, KEYUP, 0)


# Browsers only — File Explorer's Ctrl+W closes the whole window, not a tab.
BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi", "chromium")


def own_console():
    """Wilco's own console window — never a target, or it closes itself."""
    return ctypes.windll.kernel32.GetConsoleWindow()


def foreground_window():
    """(hwnd, title) of the window in front, or (None, '') when that's our own console."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or hwnd == own_console():
        return None, ""
    return hwnd, win32gui.GetWindowText(hwnd)


def _force_foreground(hwnd):
    """Raise a window and confirm it actually came forward.

    Windows refuses SetForegroundWindow from a process that doesn't already own the
    foreground — which Wilco never does, since the user is looking at their own work. The
    documented way through is to attach to the input queue of whichever thread currently
    holds the foreground, which makes the call legal for as long as the attachment lasts.
    A synthetic ALT tap on top of that satisfies the "there was recent user input" rule the
    lock also checks. Neither is a hack around a security boundary; both are the sanctioned
    route, and either alone fails on some Windows builds.
    """
    if not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        current = win32gui.GetForegroundWindow()
        if current == hwnd:
            return True  # already there, so don't touch focus at all
        ours = win32api.GetCurrentThreadId()
        theirs = win32process.GetWindowThreadProcessId(current)[0] if current else 0
        attached = False
        try:
            if theirs and theirs != ours:
                win32process.AttachThreadInput(theirs, ours, True)
                attached = True
            _tap(VK_ALT)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(theirs, ours, False)
                except Exception:
                    pass
    except Exception:
        pass
    # report what really happened rather than assuming the call did what it said
    for _ in range(6):
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.1)
    return False


def window_box(hwnd):
    """(left, top, right, bottom) of a window, or None if it has no usable rectangle."""
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    return (left, top, right, bottom) if right > left and bottom > top else None


# Apps beyond browsers whose Ctrl+W closes a tab — "close this tab" in VS Code once shut a browser tab instead.
TABBED = BROWSERS + ("visual studio code", "explorer", "terminal", "notepad",
                     "sublime", "notepad++", "atom", "obsidian")


def _tabbed_window():
    """A window that plausibly has tabs, when the user isn't looking at one."""
    for _, other in windows_matching(""):
        if any(app in other.lower() for app in TABBED):
            return other
    return None


def _target_for_tab(named):
    """Which window a tab-close should hit. None when there's nothing sensible.

    "This tab" means the one in front, whatever app that is — so when the user is already
    looking at it nothing has to be focused at all. That matters: Windows blocks a background
    process from stealing focus, so the less focus is moved the more reliably this works.
    """
    if named:
        return focus_window(named, wait=1.0)
    hwnd, title = foreground_window()
    if hwnd:
        return title
    # our own console is in front, so the user is looking at Wilco, not at their work
    other = _tabbed_window()
    return focus_window(other, wait=1.0) if other else None


def close_tab(target=""):
    """Ctrl+W on the right window, then verify. Returns the window's title only when a
    tab actually closed — the title swapped to the next tab, or the window went away
    with its last tab. None means nothing visibly changed, and the caller must not
    claim success.

    Never taps blind: Ctrl+W in the wrong app closes that app's document, and in our own
    console it does nothing useful, so with no plausible target we do nothing and say so.
    """
    title = _target_for_tab(target)
    if not title:
        return None
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd or hwnd == own_console():
        return None
    try:
        before = win32gui.GetWindowText(hwnd)
    except Exception:
        return None
    _combo(VK_CTRL, VK_W)
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        try:
            if not win32gui.IsWindow(hwnd):
                return title  # last tab closed — the whole window went with it
            after = win32gui.GetWindowText(hwnd)
            if after != before:
                return after or title  # the next tab took over the title
        except Exception:
            return title  # the handle died mid-check, which means it closed
        time.sleep(0.1)
    return None  # title unchanged, window still there — the close did not happen


def close_window(target=""):
    """Alt+F4 on a window, then verify. Returns the title only when the window really
    disappeared within a couple of seconds; None when there was nothing to close, the
    focus never landed, or the window is still up (typically asking to save)."""
    if target:
        title = focus_window(target, wait=1.0)
        if not title:
            return None
    else:
        hwnd, title = foreground_window()
        if not hwnd or not title:
            return None
    hwnd = win32gui.GetForegroundWindow()
    _combo(VK_ALT, VK_F4)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            if not win32gui.IsWindow(hwnd):
                return title
        except Exception:
            return title  # invalid handle now — it closed
        time.sleep(0.1)
    return None  # still there — say so instead of claiming success


def volume_step(direction, times=5):
    _tap(VK[direction], times)


def mute():
    _tap(VK["mute"])


# ------------------------------------ audio via Core Audio ------------------------------------
# Well-known GUIDs from the Windows SDK (mmdeviceapi.h / endpointvolume.h).
_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C459C1537871}"          #noqa
_IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF0F3732911}"          #noqa
_ERENDER, _ECONSOLE = 0, 1

_audio_local = threading.local()
_audio_error = ""


def _class_factory_create(iface):
    """Activate a COM class straight from its DLL when the registry has no entry.

    Some slimmed-down Windows installs lack the COM registration for the audio
    enumerator even though MMDevAPI.dll ships with Windows. DllGetClassObject
    hands us the class factory without touching the registry. None on any failure.
    """
    import ctypes
    from comtypes import GUID
    from ctypes import POINTER, byref, c_void_p

    try:
        dll = ctypes.WinDLL(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                                         "System32", "MMDevAPI.dll"))
    except OSError:
        return None
    get_class_object = dll.DllGetClassObject
    get_class_object.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
    get_class_object.restype = ctypes.HRESULT
    factory = c_void_p()
    hr = get_class_object(byref(GUID(_CLSID_MMDeviceEnumerator)),
                          byref(GUID("{00000001-0000-0000-C000-000000000046}")),  # IID_IClassFactory
                          byref(factory))
    if hr != 0 or not factory.value:
        return None
    slot = ctypes.sizeof(c_void_p)
    try:
        create = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, c_void_p, POINTER(c_void_p))(
            factory.value + 3 * slot)                       # IClassFactory::CreateInstance
        out = c_void_p()
        if create(None, byref(iface._iid_), byref(out)) != 0 or not out.value:
            return None
        return iface(out.value)     # adopt the reference; comtypes releases it on GC
    finally:
        release = ctypes.WINFUNCTYPE(ctypes.c_uint, c_void_p)(factory.value + 2 * slot)  # Release
        release(factory)


def _audio_endpoint():
    """IAudioEndpointVolume of the default output device, cached per thread.

    win32com's Dispatch can't create the enumerator (it exposes no IDispatch), so this
    goes through comtypes with the real vtable. The endpoint is cached per thread
    because COM apartment rules require it — an STA pointer must stay on its own thread.
    Returns None on any failure so callers keep their silent fallbacks.
    """
    ep = getattr(_audio_local, "ep", None)
    if ep is not None:
        return ep
    try:
        import comtypes
        from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
        from ctypes import c_float, c_int, c_uint, c_void_p, POINTER

        class IAudioEndpointVolume(IUnknown):
            _iid_ = GUID(_IID_IAudioEndpointVolume)
            # vtable order matters — every method up to GetMute must be declared
            _methods_ = [
                COMMETHOD([], HRESULT, "RegisterControlChangeNotify",
                          (["in"], POINTER(c_void_p), "pNotify")),
                COMMETHOD([], HRESULT, "UnregisterControlChangeNotify",
                          (["in"], POINTER(c_void_p), "pNotify")),
                COMMETHOD([], HRESULT, "GetChannelCount",
                          (["out"], POINTER(c_uint), "pnChannelCount")),
                COMMETHOD([], HRESULT, "SetMasterVolumeLevel",
                          (["in"], c_float, "fLevelDB")),
                COMMETHOD([], HRESULT, "SetMasterVolumeLevelScalar",
                          (["in"], c_float, "fLevel"),
                          (["in"], POINTER(GUID), "pguidEventContext")),
                COMMETHOD([], HRESULT, "GetMasterVolumeLevel",
                          (["out"], POINTER(c_float), "pfLevelDB")),
                COMMETHOD([], HRESULT, "GetMasterVolumeLevelScalar",
                          (["out"], POINTER(c_float), "pfLevel")),
                COMMETHOD([], HRESULT, "SetChannelVolumeLevel",
                          (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevelDB")),
                COMMETHOD([], HRESULT, "SetChannelVolumeLevelScalar",
                          (["in"], c_uint, "nChannel"), (["in"], c_float, "fLevel")),
                COMMETHOD([], HRESULT, "GetChannelVolumeLevel",
                          (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevelDB")),
                COMMETHOD([], HRESULT, "GetChannelVolumeLevelScalar",
                          (["in"], c_uint, "nChannel"), (["out"], POINTER(c_float), "pfLevel")),
                COMMETHOD([], HRESULT, "SetMute",
                          (["in"], c_int, "bMute"),
                          (["in"], POINTER(GUID), "pguidEventContext")),
                COMMETHOD([], HRESULT, "GetMute",
                          (["out"], POINTER(c_int), "pbMute")),
            ]

        class IMMDevice(IUnknown):
            _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")          #noqa
            _methods_ = [
                COMMETHOD([], HRESULT, "Activate",
                          (["in"], POINTER(GUID), "iid"),
                          (["in"], c_uint, "dwClsCtx"),
                          (["in"], POINTER(c_void_p), "pActivationParams"),
                          (["out"], POINTER(POINTER(IAudioEndpointVolume)), "ppInterface")),
            ]

        class IMMDeviceEnumerator(IUnknown):
            _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")          #noqa
            _methods_ = [
                COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                          (["in"], c_int, "dataFlow"), (["in"], c_uint, "dwStateMask"),
                          (["out"], POINTER(c_void_p), "ppDevices")),
                COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                          (["in"], c_int, "dataFlow"), (["in"], c_int, "role"),
                          (["out"], POINTER(POINTER(IMMDevice)), "ppEndpoint")),
            ]

        comtypes.CoInitialize()
        try:
            enum = comtypes.CoCreateInstance(GUID(_CLSID_MMDeviceEnumerator),
                                             interface=IMMDeviceEnumerator,
                                             clsctx=comtypes.CLSCTX_ALL)
        except OSError:
            enum = _class_factory_create(IMMDeviceEnumerator)
        if enum is None:
            return None
        dev = enum.GetDefaultAudioEndpoint(_ERENDER, _ECONSOLE)
        ep = dev.Activate(GUID(_IID_IAudioEndpointVolume), 0x1E, None)      # CLSCTX_ALL
        _audio_local.ep = ep
        return ep
    except Exception as error:
        global _audio_error
        _audio_error = f"{type(error).__name__}: {error}"
        return None


def get_mute():
    """True if the default output device is muted, False if not, None if unreadable.

    Read-only — never changes anything. Uses the CoreAudio MMDevice API through
    the real, Microsoft-published interface GUIDs (the same constants the
    Windows SDK documents — not invented). Returns None on any COM failure, so
    it can never break the agent loop.
    """
    try:
        endpoint = _audio_endpoint()
        if endpoint is None:
            return None
        return bool(endpoint.GetMute())
    except Exception:
        return None


def media(action):
    """play_pause / next / previous / stop — whatever app currently owns media keys."""
    _tap(VK[action])


# tasklist is a ~200ms shell-out and the answer barely changes second to second,
# so a short TTL keeps repeat media queries instant.
_MEDIA_TTL = 10.0
_media_cache = {"at": 0.0, "apps": []}


def media_app_running():
    """Names of running apps that respond to media keys, if any."""
    now = time.monotonic()
    if now - _media_cache["at"] < _MEDIA_TTL:
        return _media_cache["apps"]
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         creationflags=NO_WINDOW).stdout
    known = {"spotify.exe": "Spotify", "vlc.exe": "VLC", "chrome.exe": "Chrome",
             "msedge.exe": "Edge", "brave.exe": "Brave", "wmplayer.exe": "Media Player",
             "music.ui.exe": "Media Player", "firefox.exe": "Firefox"}
    running = sorted({v for k, v in known.items() if f'"{k}"' in out.lower()})
    _media_cache.update(at=now, apps=running)
    return running


def set_volume(percent):
    """Set master volume directly through Core Audio; falls back to key taps
    (each key press moves 2%, so drop to zero then step up) if COM is unavailable."""
    percent = max(0, min(100, int(percent)))
    try:
        endpoint = _audio_endpoint()
        if endpoint is not None:
            endpoint.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return percent
    except Exception:
        pass
    _tap(VK["down"], 50)
    _tap(VK["up"], round(percent / 2))
    return percent

def get_volume():
    """Current master output volume as 0-100, or None if it can't be read.

    Read-only — never changes anything. Prefers the CoreAudio master scalar
    (what set_volume writes, so reads and writes agree), and falls back to the
    native WinMM wave-out average of its two channels.
    """
    try:
        endpoint = _audio_endpoint()
        if endpoint is not None:
            return round(float(endpoint.GetMasterVolumeLevelScalar()) * 100)
    except Exception:
        pass
    WAVE_MAPPER = 0xFFFFFFFF  # -1 selects the default output device
    try:
        current = wintypes.DWORD()
        rc = ctypes.windll.winmm.waveOutGetVolume(WAVE_MAPPER, ctypes.byref(current))
    except (OSError, AttributeError):
        return None
    if rc != 0:
        return None
    both = current.value
    left = (both & 0xFFFF) / 655.35
    right = ((both >> 16) & 0xFFFF) / 655.35
    return round((left + right) / 2)

_wmi_local = threading.local()


def _wmi_namespace():
    """SWbemServices for root/WMI, cached per thread (COM pointers are apartment-bound)."""
    ns = getattr(_wmi_local, "ns", None)
    if ns is None:
        import pythoncom
        pythoncom.CoInitialize()
        ns = win32com.client.GetObject("winmgmts://./root/WMI")
        _wmi_local.ns = ns
    return ns


def get_brightness():
    """Current panel brightness, read in-process over WMI (fast), with the old
    PowerShell route kept as a fallback for builds where the COM moniker fails."""
    try:
        values = [int(m.CurrentBrightness)
                  for m in _wmi_namespace().InstancesOf("WmiMonitorBrightness")]
        if values:
            return max(0, min(100, values[0]))
    except Exception:
        _wmi_local.ns = None  # dead pointer — rebuild next time
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness"
         " -EA SilentlyContinue).CurrentBrightness"],
        capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
    return int(out.split()[0]) if out.split() else None


def set_brightness(percent):
    """Set panel brightness in-process over WMI (fast); PowerShell fallback.
    Get-CimInstance objects carry no methods, so the fallback has to be Get-WmiObject."""
    percent = max(0, min(100, int(percent)))
    try:
        done = False
        for m in _wmi_namespace().InstancesOf("WmiMonitorBrightnessMethods"):
            m.WmiSetBrightness(1, percent)
            done = True
        if done:
            return percent
    except Exception:
        _wmi_local.ns = None  # dead pointer — rebuild next time
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods"
         f" -EA Stop).WmiSetBrightness(1,{percent})"],
        capture_output=True, text=True, creationflags=NO_WINDOW)
    return percent if out.returncode == 0 else None


def wifi(on):
    out = subprocess.run(
        ["netsh", "interface", "set", "interface", "Wi-Fi",
         "enable" if on else "disable"], capture_output=True, text=True,
        creationflags=NO_WINDOW)
    return out.returncode == 0


def clipboard_get():
    """Whatever text is on the clipboard, or '' if there is none."""
    try:
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                return ""
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""


def clipboard_set(text):
    """Put text on the clipboard. False if another app is holding it."""
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return True
    except Exception:
        return False


def type_text(text):
    """Type into whatever has focus.

    SendKeys can only send keys the active keyboard layout actually has, so Devanagari, emoji
    and accented letters silently type NOTHING — which looks exactly like the message being
    sent, because the call reports success either way. Anything outside ASCII therefore goes
    via the clipboard and Ctrl+V, which carries any script, and the user's own clipboard is
    put back afterwards so dictating a message doesn't quietly eat what they had copied.
    """
    if text.isascii():
        escaped = "".join("{%s}" % c if c in "+^%~(){}[]" else c for c in text)
        win32com.client.Dispatch("WScript.Shell").SendKeys(escaped)
        return text
    saved = clipboard_get()
    if not clipboard_set(text):
        return ""
    press_key("ctrl+v")
    time.sleep(0.3)
    if saved:
        clipboard_set(saved)
    return text


def windows_search(query):
    _combo(VK_LWIN, VK_S)
    type_text(query)
    return query


def press_key(name, times=1):
    """Tap a key or a combination into the focused window. False if the name isn't known.

    Accepts "enter", "a", "f2", and combinations written any of the usual ways —
    "ctrl+a", "ctrl a", "ctrl+shift+n", "alt+f4". Modifiers are held down while the final
    key is tapped, which is the only way a shortcut actually registers.
    """
    parts = [p for p in _KEY_SPLIT.split(name.lower().strip()) if p]
    if not parts:
        return False
    *held, final = parts
    if final not in KEYS or any(m not in MODIFIERS for m in held):
        return False
    codes = [MODIFIERS[m] for m in held]
    for _ in range(max(1, int(times))):
        for code in codes:
            _user32.keybd_event(code, 0, 0, 0)
        _tap(KEYS[final])
        for code in reversed(codes):  # release in reverse, as a real hand would
            _user32.keybd_event(code, 0, KEYUP, 0)
    return True


def window_exe(hwnd):
    """The lowercased exe name behind a window — 'msedge.exe'. Empty when it can't be read.

    Which process owns a window is the only dependable way to tell one browser's windows from
    another's. Matching on the pid that was launched does not work for Chromium browsers: they
    hand the request to an already-running process and the launched one exits immediately, so
    by the time the window appears that pid is gone.
    """
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(len(buffer))
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return os.path.basename(buffer.value).lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    return ""


def windows_matching(title_part):
    """[(hwnd, title)] of visible windows whose title contains the text, front-most first.

    EnumWindows hands back windows in z-order, so the one the user was last looking at comes
    first. That order used to be thrown away by sorting on title length, which is why asking
    for "Notepad" with several open picked whichever happened to have the shortest title
    rather than the one just being used.
    """
    found = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and title_part.lower() in title.lower():
                found.append((hwnd, title))

    win32gui.EnumWindows(collect, None)
    return found


def focus_window(title_part, wait=3.0):
    """Bring a window to the front by part of its title. Returns its title, or None.

    Polls rather than looking once: an app launched a moment ago has not drawn its window
    yet, so a single check right after opening it almost always misses.
    """
    deadline = time.monotonic() + wait
    found = windows_matching(title_part)
    while not found and time.monotonic() < deadline:
        time.sleep(0.2)
        found = windows_matching(title_part)
    if not found:
        return None
    hwnd, title = found[0]
    return title if _force_foreground(hwnd) else None


# spoken name -> ms-settings: page. "" is the Settings home page.
SETTINGS = {
    "": "", "display": "display", "screen": "display", "brightness": "display",
    "bluetooth": "bluetooth", "devices": "bluetooth", "printer": "printers",
    "wifi": "network-wifi", "wi-fi": "network-wifi", "network": "network",
    "internet": "network", "airplane mode": "network-airplanemode",
    "sound": "sound", "audio": "sound", "volume": "sound",
    "battery": "batterysaver", "power": "powersleep", "sleep": "powersleep",
    "app": "appsfeatures", "apps": "appsfeatures", "default app": "defaultapps",
    "update": "windowsupdate", "windows update": "windowsupdate",
    "privacy": "privacy", "security": "windowsdefender",
    "personalization": "personalization", "background": "personalization",
    "theme": "themes", "wallpaper": "personalization-background",
    "storage": "storagesense", "notification": "notifications",
    "mouse": "mousetouchpad", "touchpad": "devices-touchpad", "keyboard": "keyboard",
    "language": "regionlanguage", "date": "dateandtime", "time": "dateandtime",
    "about": "about", "account": "yourinfo", "night light": "nightlight",
}
_FILLER = re.compile(r"\b(?:open|show|the|my|a|windows|settings?|options?|page|panel|menu|for|to|and)\b")


def settings_page(name=""):
    """The ms-settings page a spoken name asks for, or None."""
    key = " ".join(_FILLER.sub(" ", name.lower()).split())
    return next((SETTINGS[p] for p in (key, key.removesuffix("s")) if p in SETTINGS), None)


def open_settings(name=""):
    """Open a Windows Settings page by spoken name. False if the name isn't a known page."""
    page = settings_page(name)
    if page is None:
        return False
    os.startfile("ms-settings:" + page)
    return True


if __name__ == "__main__":
    for spoken, page in [("", ""), ("settings", ""), ("display settings", "display"),
                         ("the wifi options", "network-wifi"), ("notifications", "notifications"),
                         ("settings and display options", "display"), ("bluetooth", "bluetooth")]:
        assert settings_page(spoken) == page, (spoken, settings_page(spoken))
    assert settings_page("quantum flux capacitor") is None
    print("ok")
