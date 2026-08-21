"""Typing, keys and clipboard — split from mcp_tool/pc.py."""
import windows.system as system
from config import TEXT_LIMIT


def type_text(text, press_enter=False):
    """Type text into whichever window has focus, as if on the keyboard. press_enter true hits
    Enter afterwards, which submits a search box or URL bar. focus_window first, or it lands in
    the wrong place. NOT for chat messages: typing into WhatsApp puts the text in whatever
    conversation was on screen. Use send_whatsapp and send_email — they find the right chat and
    confirm first."""
    if not system.foreground_window()[0]:
        return "No app window is focused, so I didn't type anywhere. Focus or open the app first."
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


def scroll(direction="down", pages=1):
    """Scroll the focused app up or down. direction: up or down. pages: 1 to 10 whole-page
    steps. Use this for long chats, documents, web pages, lists, and feeds after focusing the
    app. It uses Page Up/Page Down, so it follows the keyboard focus instead of the mouse."""
    direction = direction.strip().lower()
    if direction not in ("up", "down"):
        return "Direction must be 'up' or 'down'."
    if not system.foreground_window()[0]:
        return "No app window is focused, so there is nowhere to scroll."
    try:
        pages = max(1, min(10, int(pages)))
    except (TypeError, ValueError):
        return "Pages must be a number from 1 to 10."
    system.press_key(f"page{direction}", pages)
    return f"Scrolled {direction} {pages} page{'s' if pages != 1 else ''}."


def search_in_windows(query):
    """Open the Windows Start search and type a query into it. Use for finding things on the
    machine itself — settings, files, apps — not for searching the web."""
    system.windows_search(query)
    return f"Opened Windows search for {query}."


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
