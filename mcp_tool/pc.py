"""Everything the agent can do to this Windows machine.

Thin wrappers over windows/* — the launching, matching and scanning logic already lives
there and is tested. What these add is a spoken-language result string, so the model can
see what happened and carry the conversation instead of guessing.

Imports windows/* and core.context only. It must never import core.commands, or the
one-way import chain turns into a cycle.
"""
import os

import windows.apps as apps
import windows.files as files
import windows.shell as shell
import windows.system as system
from core import context
from mcp_tool.gate import _park

KINDS = ("music", "video", "image", "document")


# ----------------------------------------------------------------- apps and windows
def open_app(name):
    """Launch an installed application by its spoken name — 'notepad', 'chrome', 'vs code'.
    Works for desktop and Store apps. If several match, they are listed instead of guessing:
    ask the user which one, then call this again with the fuller name."""
    found = apps.candidates(name)
    if not found:
        return f"There's no installed app matching {name}."
    if len(found) > 1:
        return (f"{len(found)} apps match {name}: " + ", ".join(d for d, _ in found) +
                ". Ask the user which one they meant, then call open_app with that exact name.")
    display, launch_id = found[0]
    apps.launch(launch_id)
    context.app = display
    # wait for the window to actually exist and take it to the front, so a follow-up
    # type_text lands in this app rather than in whatever happened to have focus
    title = system.focus_window(display, wait=4)
    if title:
        return f"Opened {display}, now focused ({title}). Typing will go here."
    return (f"Opened {display}, but its window hasn't appeared yet. Call focus_window "
            f"before typing anything into it.")


def close_app(name=""):
    """Close a whole running application and every window it owns. Asked politely, so
    anything with unsaved work still shows its own save prompt.

    Leave name empty to close whatever is in front. This closes the ENTIRE app — to close
    one browser tab use close_tab, which is almost always what 'close this' means when a
    browser is involved."""
    target = name or system.foreground_window()[1]
    if not target:
        return "Nothing is in front, so there's nothing to close. Ask which app they mean."
    image = shell.close_app(target)
    if not image:
        return f"{target} doesn't appear to be running."
    if context.app and target.lower() in context.app.lower():
        context.app = None
    return f"Closed {target} ({image}) and all of its windows."


def close_tab(app=""):
    """Close ONE browser tab with Ctrl+W, leaving the rest of the browser open. This is what
    'close this tab' means. app: which browser, if they named one — otherwise the frontmost
    browser is used. Never use close_app for a tab; that would shut the whole browser."""
    acted = system.close_tab(app)
    if not acted:
        return (f"No {app or 'browser'} window is open, so there's no tab to close. "
                f"Don't fall back to close_app — say there's nothing to close.")
    return f"Closed a tab in {acted}."


def close_window(app=""):
    """Close a single window with Alt+F4, leaving the app's other windows open. app: part of
    the window title, or empty for the window in front."""
    acted = system.close_window(app)
    if not acted:
        return f"No {app or 'foreground'} window to close."
    return f"Closed the window {acted}."


def list_installed_apps(filter_text=""):
    """List installed apps, optionally filtered by a word. Use when the user asks what is
    installed, or when you need the exact name of something before opening it."""
    names = sorted(display for display, _ in apps.index().values())
    if filter_text:
        names = [n for n in names if filter_text.lower() in n.lower()]
    if not names:
        return f"Nothing installed matches {filter_text}."
    return f"{len(names)} apps: " + ", ".join(names[:60])


def list_open_windows():
    """List the windows currently open on screen. Use this to find out what the user is
    looking at before typing into something, or when they say 'this window' or 'the browser'."""
    found = system.windows_matching("")
    if not found:
        return "No visible windows."
    return "Open windows: " + "; ".join(title for _, title in found[:20])


def focus_window(title_part):
    """Bring a window to the front so the next typing or keypress goes to it. Give any part
    of its title — 'chrome', 'word', 'youtube'. ALWAYS call this before type_text when the
    user names where the text should go."""
    title = system.focus_window(title_part)
    if not title:
        return (f"No open window matches {title_part}. Call list_open_windows to see what's "
                f"actually open, or open_app to start it first.")
    return f"Focused: {title}"


# ----------------------------------------------------------------- typing and keys
def type_text(text, press_enter=False):
    """Type text into whichever window has focus, as if on the keyboard. Set press_enter true
    to hit Enter afterwards — that is what submits a search box, a chat message or a URL bar.
    Focus the right window first with focus_window, or the text lands in the wrong place."""
    system.type_text(text)
    if press_enter in (True, "true", "True", 1):
        system.press_key("enter")
        return f"Typed {text!r} and pressed Enter."
    return f"Typed {text!r}."


def press_key(name, times=1):
    """Tap a key: enter, tab, escape, space, backspace, delete, up, down, left, right,
    home, end, pageup, pagedown, f5. Goes to the focused window."""
    if not system.press_key(name, int(times)):
        return f"I don't know a key called {name}."
    return f"Pressed {name}" + (f" {times} times." if int(times) > 1 else ".")


def search_in_windows(query):
    """Open the Windows Start search and type a query into it. Use for finding things on the
    machine itself — settings, files, apps — not for searching the web."""
    system.windows_search(query)
    return f"Opened Windows search for {query}."


# ----------------------------------------------------------------- files and folders
def open_folder(name):
    """Open a folder in File Explorer. Known names — downloads, documents, desktop, pictures,
    music, videos — resolve instantly; anything else is searched for across the drives."""
    path = system.open_folder(name)
    if path:
        context.folder = path
        return f"Opened your {name} folder ({path})."
    found = files.folder_matches(name)
    if not found:
        return f"No folder called {name} anywhere on the drives."
    if len(found) > 1:
        listed = "; ".join(f"{n} in {p}" for n, p in found)
        return (f"{len(found)} folders match: {listed}. Ask the user which, then call "
                f"open_folder with a more specific name.")
    folder_name, path = found[0]
    files.open_file(path)
    context.folder = path
    return f"Opened {folder_name} at {path}."


def find_files(name, kind="any"):
    """Find files by name across the drives. kind: music, video, image, document, or any.
    Returns what matched — use open_file to actually open one. The first call of the session
    scans the disks and takes a few seconds."""
    kinds = KINDS if kind in ("any", "", None) else (kind,)
    hits = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not hits:
        return f"No {kind} files matching {name}."
    return f"{len(hits)} matches: " + "; ".join(f"{n} ({k}) in {os.path.dirname(p)}"
                                                for k, n, p in hits[:15])


def open_file(name, kind="any"):
    """Open a file by name in its default application. If several match, they are listed
    rather than guessed — ask which one, then call again with a fuller name."""
    kinds = KINDS if kind in ("any", "", None) else (kind,)
    hits = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not hits:
        return f"No file matching {name}."
    if len(hits) > 1:
        listed = "; ".join(f"{n} ({k})" for k, n, p in hits[:10])
        return f"{len(hits)} files match: {listed}. Ask which one, then call open_file again."
    kind_found, found_name, path = hits[0]
    files.open_file(path)
    context.file = path
    return f"Opened {found_name} from {os.path.dirname(path)}."


def list_folder_contents(folder_name, kind="any"):
    """List the files of one kind sitting directly inside a folder. kind: music, video,
    image, document, or any."""
    path = system.folder(folder_name)
    if not path:
        found = files.folder_matches(folder_name)
        path = found[0][1] if found else None
    if not path:
        return f"Couldn't find a folder called {folder_name}."
    kinds = KINDS if kind in ("any", "", None) else (kind,)
    items = [(k, n) for k in kinds for n, _ in files.in_folder(path, k)]
    context.folder = path
    if not items:
        return f"No {kind} files in {path}."
    return (f"{len(items)} files in {path}: " +
            "; ".join(f"{n} ({k})" for k, n in items[:30]))


def delete_file(name, kind="any"):
    """Delete a file. ALWAYS goes to the recycle bin, never a hard delete, and ALWAYS asks
    the user to confirm first — it does not delete on this call. Relay the question, then
    call confirm_yes only if they agree."""
    kinds = KINDS if kind in ("any", "", None) else (kind,)
    hits = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not hits:
        return f"No file matching {name}, so there's nothing to delete."
    if len(hits) > 1:
        listed = "; ".join(f"{n} ({k}) in {os.path.dirname(p)}" for k, n, p in hits[:10])
        return f"{len(hits)} files match: {listed}. Ask exactly which one before deleting."
    _, found_name, path = hits[0]
    return _park(f"move {found_name} to the recycle bin (from {os.path.dirname(path)})",
                 lambda: shell.recycle(path))


# ----------------------------------------------------------------- sound, screen, media
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


# ----------------------------------------------------------------- system state
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
    the switch. Needs Jarvis to be running as administrator."""
    turn_on = on in (True, "true", "True", "on", 1)
    if not system.wifi(turn_on):
        return "That needs administrator rights — Jarvis isn't elevated."
    return f"Wi-Fi turned {'on' if turn_on else 'off'}."


def system_info(what):
    """Read machine state. what: ip, wifi, battery, hostname, uptime, disk, or running.
    Use this before answering anything about the state of this computer."""
    readers = {
        "ip": lambda: f"IP address is {shell.ip_address()}",
        "wifi": lambda: f"Wi-Fi is {shell.wifi_status()}",
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


def power_action(action):
    """Shut down, restart or sleep the machine. ALWAYS asks the user to confirm first — this
    call does not do it. Relay the question, then call confirm_yes only if they agree.
    action: shutdown, restart, or sleep. For 'lock' use lock_screen, which is instant."""
    parked = {
        "shutdown": ("shut this computer down in 30 seconds", lambda: shell.shutdown(False)),
        "restart": ("restart this computer in 30 seconds", lambda: shell.shutdown(True)),
        "sleep": ("put this computer to sleep", shell.sleep),
    }
    if action not in parked:
        return "action must be shutdown, restart or sleep."
    return _park(*parked[action])


def lock_screen():
    """Lock the screen right now. Safe and instant — no confirmation needed."""
    shell.lock()
    return "Locked the screen."


def cancel_shutdown():
    """Call off a shutdown or restart that is counting down."""
    shell.cancel_shutdown()
    return "Cancelled the pending shutdown."


def empty_recycle_bin():
    """Permanently empty the recycle bin. ALWAYS asks the user to confirm first — this call
    does not do it. This one cannot be undone, so be explicit about that when you ask."""
    return _park("permanently empty the recycle bin, which cannot be undone",
                 shell.empty_recycle_bin)
