"""Sending email and WhatsApp messages.

Both always confirm first. Sending is the one action here that cannot be taken back — a
misheard name or a garbled sentence goes to a real person and stays sent — so the recipient
and the full text are read back before anything leaves the machine.

Credentials are never handled by Wilco. The address and app password are read from the
environment, so they live in .env and nowhere else.
"""
import json
import os
import re
import smtplib
import ssl
import time
import urllib.parse
import webbrowser
from email.message import EmailMessage
from pathlib import Path

import windows.apps as apps
import windows.system as system
from config import EMAIL, EMAIL_PASSWORD, SMTP
from core import context
from mcp_tool.gate import _park

CONTACTS = Path(__file__).resolve().parent.parent / "contacts.json"
SMTP_HOST, SMTP_PORT = SMTP.split(":")


def _contacts():
    try:
        return json.loads(CONTACTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _look_up(who, field):
    """A saved contact's email or phone, the raw value if they gave one, else None."""
    who = who.strip()
    if field == "email" and "@" in who:
        return who
    if field == "phone" and re.fullmatch(r"[+\d][\d\s\-()]{6,}", who):
        return re.sub(r"\D", "", who)
    entry = _contacts().get(who.lower())
    if isinstance(entry, dict):
        value = entry.get(field)
        return re.sub(r"\D", "", value) if value and field == "phone" else value
    if isinstance(entry, str) and field == "email" and "@" in entry:
        return entry
    return None


def _known():
    names = ", ".join(sorted(_contacts())) or "nobody yet"
    return f"Saved contacts: {names}. Add more in contacts.json."


def _send_email_now(to, subject, body, sender, password):
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = sender, to, subject
    message.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, int(SMTP_PORT), context=ssl.create_default_context()) as s:
        s.login(sender, password)
        s.send_message(message)
    return f"Sent to {to}."


def send_email(to, subject, body):
    """Send an email. ALWAYS asks for confirmation first — this call does not send anything.
    Read the recipient, the subject and the whole body back to the user, then call confirm_yes
    only if they agree. to: a saved contact name, or a full address."""
    sender, password = EMAIL, EMAIL_PASSWORD
    if not sender or not password:
        return ("Email isn't set up. The user needs to put WILCO_EMAIL and "
                "WILCO_EMAIL_PASSWORD in their .env — for Gmail that password must be an App "
                "Password, not the account one. Tell them that; do not ask them to say it out "
                "loud to you.")
    address = _look_up(to, "email")
    if not address:
        return f"No email address for {to}. {_known()}"
    if not body.strip():
        return "The email has no body yet. Ask the user what it should say."
    return _park(
        f"email {address} with the subject {subject!r} and the message: {body}",
        lambda: _send_email_now(address, subject, body, sender, password))


def _send_to_number(number, message):
    """One-to-one chat: wa.me opens the right conversation with the text already typed."""
    webbrowser.open(f"https://wa.me/{number}?text={urllib.parse.quote(message)}")
    if not system.focus_window("WhatsApp", wait=15):
        return ("WhatsApp didn't come to the front, so the message is typed but NOT sent — "
                "tell the user to press Enter themselves.")
    time.sleep(2)  # the chat and the prefilled text land a moment after the window does
    system.press_key("enter")
    return "Enter pressed in WhatsApp. Tell the user to check it actually went."


def _open_chat_by_name(name):
    """Find a chat or group by its name in the WhatsApp window and open it.

    Groups have no phone number, so wa.me cannot reach them — the only way in is the app's
    own search box. Driven through UI Automation rather than blind hotkeys, because WhatsApp's
    shortcuts differ between the Store app, the desktop build and the web page.
    """
    from mcp_tool import ui  # imported here so message.py doesn't drag in COM on startup

    if not system.focus_window("WhatsApp", wait=4):
        installed = apps.find("whatsapp")
        if not installed:
            return "WhatsApp isn't open and isn't installed, so nothing was sent."
        apps.launch(installed[1])
        if not system.focus_window("WhatsApp", wait=25):
            return "WhatsApp wouldn't come up, so nothing was sent. Ask the user to open it."

    # remember it as the app in front, or "close this" a moment later has no idea what "this"
    # was — opening something without recording it is how the thread gets dropped
    context.app = "WhatsApp"
    time.sleep(1.5)
    for box in ("Search input textbox", "Search or start a new chat", "Search"):
        placed = ui.set_control_text(box, name, window="WhatsApp")
        if not placed.startswith("No text box"):
            break
    else:
        return ("Couldn't find WhatsApp's search box, so the chat was never opened and "
                "NOTHING was sent. Tell the user plainly that it didn't work.")

    time.sleep(2)          # results filter as you type
    system.press_key("down")   # first result — the search box itself holds focus until then
    system.press_key("enter")
    time.sleep(1.5)
    return ""


def _send_by_name(name, message):
    """Open a named chat or group, type into it, and send."""
    problem = _open_chat_by_name(name)
    if problem:
        return problem
    system.type_text(message)
    time.sleep(0.5)
    system.press_key("enter")
    return (f"Typed the message into the chat that WhatsApp's search matched for {name!r} and "
            f"pressed Enter. Tell the user to glance at WhatsApp and check it landed in the "
            f"right chat — this picks the top search result, so it can pick the wrong one.")


def send_whatsapp(to, message):
    """Send a WhatsApp message to a person OR a group. ALWAYS asks first — this call sends
    nothing. Read the recipient and the exact message back, then confirm_yes only if they
    agree. to: a group name exactly as it appears in WhatsApp, a saved contact name, or a
    phone number with country code. GROUPS HAVE NO PHONE NUMBER — pass the group name and it
    is found by searching WhatsApp. Best-effort: repeat what the result says rather than
    promising the message arrived."""
    if not message.strip():
        return "There's no message text yet. Ask the user what to say."
    number = _look_up(to, "phone")
    if number:
        return _park(f"send {to} a WhatsApp saying: {message}",
                     lambda: _send_to_number(number, message))
    # not a number and not in contacts — treat it as a chat or group name to search for
    return _park(f"open the WhatsApp chat called {to!r} and send: {message}",
                 lambda: _send_by_name(to, message))
