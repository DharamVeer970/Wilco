"""Reading and operating the controls inside a window, via Windows UI Automation.

Without this the agent could open Settings but not touch anything in it — it would open the
page and then say it couldn't help, or grab a nearby unrelated tool and claim success. UIA is
how the accessibility stack drives applications, so it works on buttons, checkboxes, toggles,
list items and text boxes in Settings, Explorer, browsers and most desktop apps.

It is not screen scraping and not blind clicking: controls are found by their real accessible
name, and a toggle reports the state it ended up in, so a claim of success is checkable.
"""
import ctypes

import win32gui
from comtypes.client import CreateObject, GetModule
from rapidfuzz import fuzz, process

import windows.system as system
from config import FUZZ_MIN, MAX_CONTROLS

GetModule("UIAutomationCore.dll")
from comtypes.gen import UIAutomationClient as UIA  # noqa: E402 — needs the GetModule above


CONTROL_KINDS = {
    50000: "button", 50002: "checkbox", 50003: "combobox", 50004: "edit",
    50005: "link", 50007: "item", 50008: "list", 50012: "radio",
    50014: "slider", 50019: "tab", 50025: "treeitem", 50029: "spinner",
}
# tried in order — the first pattern a control supports is the one used to operate it
ACTUATORS = (
    (UIA.UIA_TogglePatternId, "toggle"),
    (UIA.UIA_InvokePatternId, "invoke"),
    (UIA.UIA_SelectionItemPatternId, "select"),
    (UIA.UIA_ExpandCollapsePatternId, "expand"),
)
TOGGLE_STATES = {0: "off", 1: "on", 2: "indeterminate"}

_uia = None


def _automation():
    global _uia
    if _uia is None:
        ctypes.windll.ole32.CoInitialize(None)
        _uia = CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
    return _uia


def _window(title_part=""):
    """The UIA element for a window, focusing it first so it is the one being talked about."""
    if title_part:
        if not system.focus_window(title_part, wait=2.0):
            return None, ""
    hwnd, title = system.foreground_window()
    if not hwnd:
        return None, ""
    try:
        return _automation().ElementFromHandle(hwnd), title
    except Exception:
        return None, title


def _has_actuator(node):
    for pattern_id, _ in ACTUATORS:
        try:
            if node.GetCurrentPattern(pattern_id):
                return True
        except Exception:
            pass
    return False


def _kind_of(node, state):
    """What a control is by what it DOES, not by the type it reports.

    Windows 11 draws its on/off switches as plain buttons that happen to carry a toggle
    pattern, so going by control type alone hides every switch in Settings behind the word
    'button' and makes a search for checkboxes come back empty.
    """
    if state is not None:
        return "switch"
    kind = CONTROL_KINDS.get(node.CurrentControlType)
    if kind:
        return kind
    return "control" if _has_actuator(node) else None


def _nodes(element):
    """Every named, enabled, operable control in the window, as (name, kind, state, node)."""
    found = element.FindAll(UIA.TreeScope_Descendants, _automation().CreateTrueCondition())
    out = []
    for i in range(min(found.Length, MAX_CONTROLS)):
        try:
            node = found.GetElement(i)
            name = node.CurrentName
            if not name or not node.CurrentIsEnabled:
                continue
            state = _state_of(node)
            kind = _kind_of(node, state)
            if kind:
                out.append((name.strip(), kind, state, node))
        except Exception:
            continue  # controls vanish mid-enumeration when a page is still settling
    return out


def _state_of(node):
    """'on'/'off' for anything toggleable, else None."""
    try:
        pattern = node.GetCurrentPattern(UIA.UIA_TogglePatternId)
        if pattern:
            toggle = pattern.QueryInterface(UIA.IUIAutomationTogglePattern)
            return TOGGLE_STATES.get(toggle.CurrentToggleState)
    except Exception:
        pass
    return None


def _pick(name, controls):
    """The control the user meant: exact, then contained, then fuzzy."""
    lowered = name.lower().strip()
    names = [c[0] for c in controls]
    exact = next((c for c in controls if c[0].lower() == lowered), None)
    if exact:
        return exact
    contained = [c for c in controls if lowered in c[0].lower()]
    if contained:
        return min(contained, key=lambda c: len(c[0]))  # shortest adds least beyond the words
    best = process.extractOne(lowered, [n.lower() for n in names],
                              scorer=fuzz.partial_ratio, score_cutoff=FUZZ_MIN)
    return controls[best[2]] if best else None


def list_controls(window="", kind=""):
    """List the controls inside a window, with the current state of every on/off switch.
    Call this BEFORE click_control whenever you are not certain of the exact wording on
    screen, and again afterwards to check a switch really moved.
    window: part of a window title, or empty for the one in front.
    kind: switch, button, edit, item, link, combobox, slider — or empty for all.
    An on/off switch is kind 'switch' whatever it looks like."""
    element, title = _window(window)
    if element is None:
        return f"No window matching {window or 'the foreground'} to read."
    controls = _nodes(element)
    if kind:
        controls = [c for c in controls if c[1] == kind.lower().strip()]
    if not controls:
        kinds = sorted({c[1] for c in _nodes(element)})
        return (f"{title} has no {kind or ''} controls. What it does have: "
                f"{', '.join(kinds) or 'nothing readable'}.")
    described = [f"{name} [{control_kind}{'=' + state if state else ''}]"
                 for name, control_kind, state, _ in controls[:60]]
    return f"Controls in {title}: " + "; ".join(described)


def click_control(name, window=""):
    """Press, tick or toggle a named control inside a window — a button, a checkbox, an
    on/off switch, a list item. This is how you actually change a setting rather than just
    opening the page that holds it. For a switch, the state it ended up in is reported back,
    so say that rather than assuming. window: part of a window title, or empty for the front
    one. If the name isn't found, call list_controls and use the real wording."""
    element, title = _window(window)
    if element is None:
        return f"No window matching {window or 'the foreground'}."
    controls = _nodes(element)
    picked = _pick(name, controls)
    if not picked:
        nearby = "; ".join(f"{c[0]} [{c[1]}]" for c in controls[:25]) or "nothing readable"
        return (f"No control called {name} in {title}. What's actually there: {nearby}. "
                f"Use one of those names, or tell the user it isn't on this screen.")
    found_name, kind, before, node = picked
    for pattern_id, how in ACTUATORS:
        try:
            pattern = node.GetCurrentPattern(pattern_id)
            if not pattern:
                continue
            if how == "toggle":
                pattern.QueryInterface(UIA.IUIAutomationTogglePattern).Toggle()
            elif how == "invoke":
                pattern.QueryInterface(UIA.IUIAutomationInvokePattern).Invoke()
            elif how == "select":
                pattern.QueryInterface(UIA.IUIAutomationSelectionItemPattern).Select()
            else:
                pattern.QueryInterface(UIA.IUIAutomationExpandCollapsePattern).Expand()
            after = _state_of(node)
            if after and after != before:
                return f"{found_name} is now {after}."
            if after:
                return f"{found_name} is {after} — it did not change."
            return f"Activated {found_name} ({kind}) in {title}."
        except Exception:
            continue
    return (f"{found_name} was found but exposes no way to operate it. It may need a real "
            f"mouse click, so tell the user what to click rather than claiming it's done.")


def set_control_text(name, text, window=""):
    """Type into a named text box — a search box, an address bar, a form field — without
    relying on what currently has focus. Use this for 'search inside Settings' or 'search in
    this app': set the search box text, then press_key enter. name: the box's label, e.g.
    'Search box'. Call list_controls with kind 'edit' if you don't know the wording."""
    element, title = _window(window)
    if element is None:
        return f"No window matching {window or 'the foreground'}."
    boxes = [c for c in _nodes(element) if c[1] in ("edit", "combobox")]
    picked = _pick(name, boxes) if name else (boxes[0] if boxes else None)
    if not picked:
        available = "; ".join(c[0] for c in boxes) or "none"
        return f"No text box called {name} in {title}. Text boxes here: {available}."
    found_name, _, _, node = picked
    try:
        value = node.GetCurrentPattern(UIA.UIA_ValuePatternId)
        if not value:
            return f"{found_name} won't accept text directly. Focus it and use type_text."
        value.QueryInterface(UIA.IUIAutomationValuePattern).SetValue(text)
    except Exception as e:
        return f"Couldn't put text in {found_name}: {type(e).__name__}."
    return f"Put {text!r} into {found_name} in {title}. Press enter to submit it."
