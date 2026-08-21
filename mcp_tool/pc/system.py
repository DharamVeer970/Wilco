"""System, media and power tools — split from mcp_tool/pc.py."""
import datetime
import os

import windows.shell as shell
import windows.system as system
from config import ALWAYS_ACT, MAX_OUTPUT
from core import context
from mcp_tool.gate import _park
from mcp_tool.pc.common import _wifi_password_text


def set_volume(percent):
    """Set the system volume to an exact percentage, 0 to 100."""
    return f"Volume set to {system.set_volume(percent)} percent."


def change_volume(direction, steps=5):
    """Nudge the volume up or down without setting an exact number. direction: up or down."""
    way = "down" if direction.lower().startswith("d") else "up"
    system.volume_step(way, int(steps))
    return f"Turned the volume {way}."


def mute_sound():
    """Toggle mute on and off."""
    system.mute()
    return "Toggled mute."


def set_screen_brightness(percent):
    """Set screen brightness 0 to 100. Laptop panels only — external monitors can't be set."""
    done = system.set_brightness(percent)
    if done is None:
        return "This screen doesn't accept brightness changes — likely an external monitor."
    return f"Brightness set to {done} percent."


def media_control(action):
    """Control whatever is currently playing anywhere — Spotify, VLC, YouTube in a browser.
    action: play_pause, next, previous, or stop."""
    if action not in ("play_pause", "next", "previous", "stop"):
        return "action must be play_pause, next, previous or stop."
    running = system.media_app_running()
    system.media(action)
    if not running:
        return (f"Sent {action}, but no known media app is running, so it may have gone nowhere. "
                f"Ask the user what they want to play.")
    return f"Sent {action} to {', '.join(running)}."


def open_windows_settings(page=""):
    """Open a Windows Settings page. page: display, bluetooth, wifi, sound, battery, power,
    apps, update, privacy, storage, notifications, mouse, keyboard, language, date,
    personalization, night light, about — or empty for the Settings home page."""
    resolved = system.settings_page(page)
    if resolved is None:
        return f"There's no Settings page called {page}."
    system.open_settings(page)
    return f"Opened {resolved or 'the main'} Settings page."


def wifi_switch(on):
    """Turn the Wi-Fi adapter on or off. Wi-Fi ONLY — this does nothing for Bluetooth,
    airplane mode or mobile data. For those, open the settings page and use click_control on
    the switch. Needs Wilco to be running as administrator."""
    turn_on = on in (True, "true", "True", "on", 1)
    if not system.wifi(turn_on):
        return "That needs administrator rights — Wilco isn't elevated."
    return f"Wi-Fi turned {'on' if turn_on else 'off'}."


def wifi_password(name=""):
    """Reveal a saved Wi-Fi password so it can be read to connect another device. name is a
    profile/NSSID; leave it blank for the currently connected network. In all-access mode (the
    default) the password is spoken back directly; with WILCO_ALWAYS_ACT=0 it comes back asking
    first — a saved password is one thing that never runs without a yes unless all-access is on."""
    if ALWAYS_ACT:
        value = shell.wifi_password(name)
        return f"The Wi-Fi password is {value}." if value else "Couldn't read that password."
    return _park(f"reveal the saved Wi-Fi password for {name or 'the current network'}",
                 lambda: shell.wifi_password(name))


def system_info(what):
    """Read machine state. what: ip, wifi, password, battery, hostname, uptime, disk, or
    running. Use this before answering anything about the state of this computer."""
    readers = {
        "ip": lambda: f"IP address is {shell.ip_address()}",
        "wifi": lambda: f"Wi-Fi is {shell.wifi_status()}",
        "password": _wifi_password_text,
        "battery": lambda: f"Battery is at {shell.battery_percent()} percent",
        "hostname": lambda: f"This machine is called {shell.computer_name()}",
        "uptime": lambda: f"Running since {shell.uptime()}",
        "disk": lambda: "Disk: " + ", ".join(f"{c} has {free} of {total} GB free"
                                             for c, free, total in shell.disk_free()),
        "running": lambda: "Currently running: " + ", ".join(shell.running_apps()),
    }
    reader = readers.get(what.lower().strip())
    if not reader:
        return f"I can read: {', '.join(readers)}."
    return reader()


def check_windows_updates():
    """Check what Windows updates are available right now — read-only, installs nothing.
    Use when the user asks if there are updates, whether Windows is up to date, or wants
    to 'check for updates'. Reports the update titles, or that none are pending."""
    script = (
        "$Session = New-Object -ComObject Microsoft.Update.Session; "
        "$Searcher = $Session.CreateUpdateSearcher(); "
        "$Count = $Searcher.GetTotalHistoryCount(); "
        "$Results = $Searcher.Search('IsInstalled=0'); "
        "if($Results.Updates.Count -eq 0) { 'No updates available.' } else { "
        "'Updates available (' + $Results.Updates.Count + '):'; "
        "$Results.Updates | ForEach-Object { $_.Title } }"
    )
    try:
        output = shell.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    except Exception as e:
        return f"Couldn't check for updates: {e}"
    if not output or "No updates available" in output:
        return "No Windows updates are available right now."
    return f"Windows updates available: {output.strip()[:MAX_OUTPUT]}"


def power_action(action):
    """Shut down, restart or sleep the machine. In all-access mode (the default) it acts
    at once; with WILCO_ALWAYS_ACT=0 it parks until you agree. action: shutdown, restart,
    or sleep. For 'lock' use lock_screen, which is instant."""
    parked = {
        "shutdown": ("shut this computer down in 30 seconds", lambda: shell.shutdown(False)),
        "restart": ("restart this computer in 30 seconds", lambda: shell.shutdown(True)),
        "sleep": ("put this computer to sleep", shell.sleep),
    }
    if action not in parked:
        return "action must be shutdown, restart or sleep."
    return _park(*parked[action])


def take_screenshot(what="screen"):
    """Capture the screen to an image file in the user's Pictures folder and report where it
    went. what: 'screen' for everything including a second monitor, or 'window' for just the
    window in front."""
    from PIL import ImageGrab
    folder = os.path.join(system.folder("pictures") or os.path.expanduser("~"), "Screenshots")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"shot-{datetime.datetime.now():%Y-%m-%d-%H%M%S}.png")
    if what.strip().lower().startswith("win"):
        hwnd, title = system.foreground_window()
        box = system.window_box(hwnd) if hwnd else None
        image = ImageGrab.grab(bbox=box) if box else ImageGrab.grab(all_screens=True)
        where = f" of {title}" if box else ""
    else:
        image = ImageGrab.grab(all_screens=True)
        where = ""
    image.save(path)
    context.file = path
    return f"Screenshot{where} saved as {os.path.basename(path)} in {folder}."


def current_time(what="both"):
    """The current time and date. what: 'time', 'date', or 'both'. Say it the way a person
    would — 'about twenty past four' or 'Tuesday the third' — not as digits read out."""
    now = datetime.datetime.now()
    asked = what.strip().lower()
    if asked == "time":
        return f"It's {now:%I:%M %p}".replace(" 0", " ")
    if asked == "date":
        return f"Today is {now:%A, %d %B %Y}"
    return f"It's {now:%I:%M %p} on {now:%A, %d %B %Y}".replace(" 0", " ")


def lock_screen():
    """Lock the screen right now. Safe and instant — no confirmation needed."""
    shell.lock()
    return "Locked the screen."


def cancel_shutdown():
    """Call off a shutdown or restart that is counting down."""
    shell.cancel_shutdown()
    return "Cancelled the pending shutdown."


def empty_recycle_bin():
    """Permanently empty the recycle bin. In all-access mode (the default) it does it at
    once; with WILCO_ALWAYS_ACT=0 it parks first. This one cannot be undone, so be explicit
    about that when you ask."""
    return _park("permanently empty the recycle bin, which cannot be undone",
                 shell.empty_recycle_bin)
