"""App and window controls — split from mcp_tool/pc.py."""
import windows.apps as apps
import windows.browser as browsers
import windows.shell as shell
import windows.system as system
from core import context


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
