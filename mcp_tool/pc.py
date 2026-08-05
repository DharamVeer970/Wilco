"""Everything the agent can do to this Windows machine.

Thin wrappers over windows/* — the launching, matching and scanning logic already lives
there and is tested. What these add is a spoken-language result string, so the model can
see what happened and carry the conversation instead of guessing.

Imports windows/* and core.context only. It must never import core.commands, or the
one-way import chain turns into a cycle.
"""
import datetime
import os
import re
import shutil

import windows.apps as apps
import windows.browser as browsers
import windows.files as files
import windows.shell as shell
import windows.system as system
from config import TEXT_LIMIT
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


def open_browser_window(private=False, url="", browser=""):
    """Open a NEW browser window, private or ordinary. THIS is the tool for "incognito",
    "InPrivate", "private window", "private browsing", "secret tab" — never go at it through
    the browser's menu. Works whatever has focus.
    private: true for incognito. url: optional page. browser: edge, chrome, firefox, brave,
    opera, vivaldi — empty means the user's default.
    Reports the title of the window that actually appeared, so say what it says."""
    private = private in (True, "true", "True", 1, "1", "yes")
    try:
        name, title, looked_private, reused = browsers.open_window(browser, private, url)
    except LookupError:
        return (f"I don't know a browser called {browser}. Installed here: "
                f"{', '.join(browsers.installed()) or 'none I can find'}.")
    except FileNotFoundError as e:
        return (f"{e} isn't installed on this machine. What is: "
                f"{', '.join(browsers.installed()) or 'no browser I can find'}.")
    except OSError as e:
        return f"Couldn't start {browser or 'the browser'}: {e.strerror or e}."
    kind = "private" if private else "new"
    if reused:
        system.focus_window(title[:40])
        return (f"{name} already had a private window open, so this went in as a new tab "
                f"there rather than a second window, and that window is now in front: {title}.")
    if not title:
        return (f"Ran {name} with its {kind}-window switch, but no new window appeared within "
                f"a few seconds. Call list_open_windows to see whether it turned up late.")
    if private and not looked_private:
        return (f"Opened a {name} window ({title}), but it does not call itself private in "
                f"the title, so do not promise the user it is. Say what you see.")
    return f"Opened a {kind} {name} window: {title}."


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
    """Type text into whichever window has focus, as if on the keyboard. press_enter true hits
    Enter afterwards, which submits a search box or URL bar. focus_window first, or it lands in
    the wrong place. NOT for chat messages: typing into WhatsApp puts the text in whatever
    conversation was on screen. Use send_whatsapp and send_email — they find the right chat and
    confirm first."""
    system.type_text(text)
    if press_enter in (True, "true", "True", 1):
        system.press_key("enter")
        return f"Typed {text!r} and pressed Enter."
    return f"Typed {text!r}."


def press_key(name, times=1):
    """Press a key or shortcut in the focused window. One string with pluses: "ctrl+a",
    "ctrl+shift+n", "alt+f4". A modifier sent as its own call does nothing.
    Keys: enter tab escape space backspace delete insert up down left right home end
    pageup pagedown f1-f12, any letter or digit.
    ctrl+a select all, +c copy, +v paste, +x cut, +z undo, +s save, +f find, +t new tab,
    +w close tab, +shift+t reopen tab, +l address bar, +n new window; f11 full screen,
    alt+tab switch, alt+f4 close, alt+f browser menu, win+d desktop.
    ctrl+shift+n is incognito in Edge/Chrome, ctrl+shift+p in Firefox — the shortcut works
    even when the menu item is not in list_controls yet. Clear a box with ctrl+a then delete."""
    if not system.press_key(name, int(times)):
        return (f"'{name}' isn't a key I can press. Write shortcuts as one string like "
                f"'ctrl+a'. A modifier on its own does nothing.")
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




def _resolve(path):
    """A spoken path into a real one. Accepts C:/x, C:\\x, /c/x and ~/x."""
    path = os.path.expanduser(path.strip().strip('"'))
    if re.fullmatch(r"/[a-zA-Z]/.*", path):          # git-bash style /c/Users/...
        path = path[1] + ":" + path[2:]
    return os.path.abspath(path)


def read_file(path, lines=200):
    """Read a text file and return its contents — notes, code, config, logs, csv.
    path: a full path, or ~/Documents/notes.txt. lines: how many lines to read back.
    Use run_bash with grep when you need to search inside many files instead of one."""
    full = _resolve(path)
    if not os.path.isfile(full):
        return f"There's no file at {full}."
    try:
        with open(full, encoding="utf-8", errors="replace") as handle:
            read = [next(handle, None) for _ in range(int(lines))]
    except OSError as e:
        return f"Couldn't read {full}: {e.strerror or e}"
    text = "".join(part for part in read if part)
    if not text.strip():
        return f"{full} is empty."
    return f"{full}:\n{text[:TEXT_LIMIT]}"


def _backup(full):
    """Keep the previous contents next to the file. Overwriting is not undoable otherwise."""
    if os.path.isfile(full):
        try:
            shutil.copy2(full, full + ".bak")
            return " The previous version is saved alongside it as a .bak file."
        except OSError:
            return " I couldn't make a backup copy, so the old contents will be lost."
    return ""


def _write(full, text):
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    note = _backup(full)
    with open(full, "w", encoding="utf-8") as handle:
        handle.write(text)
    return f"Saved {len(text)} characters to {full}.{note}"


def write_file(path, text):
    """Create a file, or replace everything in one. ALWAYS asks the user first — this call
    writes nothing. Say the path and roughly what is going into it before they decide.
    The old contents are kept as a .bak file, so an overwrite can be undone."""
    full = _resolve(path)
    what = "replace everything in" if os.path.isfile(full) else "create"
    return _park(f"{what} {full} with {len(text)} characters of text",
                 lambda: _write(full, text))


def edit_file(path, find, replace):
    """Change some text inside a file, leaving the rest alone — fix a typo, change a setting,
    update a value. ALWAYS asks first, and tells you how many places would change, so a
    find-and-replace can't quietly rewrite more than expected. The old version is kept as
    a .bak file."""
    full = _resolve(path)
    if not os.path.isfile(full):
        return f"There's no file at {full}."
    try:
        original = open(full, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return f"Couldn't read {full}: {e.strerror or e}"
    hits = original.count(find)
    if not hits:
        return f"{full} doesn't contain that text, so there's nothing to change."
    preview = replace[:60] + ("..." if len(replace) > 60 else "")
    return _park(
        f"change {hits} place{'s' if hits > 1 else ''} in {os.path.basename(full)} "
        f"from {find[:60]!r} to {preview!r}",
        lambda: _write(full, original.replace(find, replace)))


def clipboard(text=""):
    """Read the Windows clipboard, or put something on it. Leave text empty to read what is
    there — that is how you answer "what did I just copy", "read my clipboard", "what's
    copied". Pass text to put it on the clipboard so the user can paste it anywhere, which
    beats type_text when the target window isn't focused or the text is long."""
    if text:
        if not system.clipboard_set(text):
            return "Another app is holding the clipboard, so nothing was copied."
        return f"Put {len(text)} characters on the clipboard."
    held = system.clipboard_get()
    if not held.strip():
        return "The clipboard is empty, or has something on it that isn't text."
    return f"The clipboard holds ({len(held)} chars): {held[:TEXT_LIMIT]}"


def manage_file(action, source, destination=""):
    """Move, copy or rename a file or folder, or make a new folder.
    action: move, copy, rename, new_folder. source: a full path, or a name find_files would
    turn up. destination: where it goes; for rename just the new name; unused for new_folder.
    Never overwrites — if the destination exists it refuses. delete_file first to replace."""
    action = (action or "").strip().lower()
    if action not in ("move", "copy", "rename", "new_folder"):
        return f"{action!r} isn't one of: move, copy, rename, new_folder."
    full = _resolve(source)

    if action == "new_folder":
        if os.path.exists(full):
            return f"{full} already exists."
        try:
            os.makedirs(full)
        except OSError as e:
            return f"Couldn't create {full}: {e.strerror or e}"
        return f"Created the folder {full}."

    if not os.path.exists(full):
        found = files.matches("document", source) or files.matches("image", source)
        hint = f" Did you mean {found[0][1]}?" if found else ""
        return f"There's nothing at {full}.{hint} Use find_files to get the real path."
    if not destination:
        return f"{action} needs a destination — where should {os.path.basename(full)} go?"

    target = _resolve(destination)
    if action == "rename" or os.path.isdir(os.path.dirname(target)) and not os.path.isdir(target):
        target = target if os.sep in destination or ":" in destination else \
            os.path.join(os.path.dirname(full), destination)
    elif os.path.isdir(target):
        target = os.path.join(target, os.path.basename(full))
    if os.path.exists(target):
        return (f"{target} already exists, so nothing was touched. Delete it first if the "
                f"user really wants it replaced.")
    try:
        if action == "copy":
            shutil.copytree(full, target) if os.path.isdir(full) else shutil.copy2(full, target)
        else:
            shutil.move(full, target)
    except OSError as e:
        return f"Couldn't {action} {full}: {e.strerror or e}"
    done = {"move": "Moved", "copy": "Copied", "rename": "Renamed"}[action]
    return f"{done} {os.path.basename(full)} to {target}."


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
    the switch. Needs Wilco to be running as administrator."""
    turn_on = on in (True, "true", "True", "on", 1)
    if not system.wifi(turn_on):
        return "That needs administrator rights — Wilco isn't elevated."
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


def take_screenshot(what="screen"):
    """Capture the screen to an image file in the user's Pictures folder and report where it
    went. what: 'screen' for everything including a second monitor, or 'window' for just the
    window in front."""
    from PIL import ImageGrab  # imported here so a missing Pillow can't stop Wilco starting

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
    """Permanently empty the recycle bin. ALWAYS asks the user to confirm first — this call
    does not do it. This one cannot be undone, so be explicit about that when you ask."""
    return _park("permanently empty the recycle bin, which cannot be undone",
                 shell.empty_recycle_bin)
