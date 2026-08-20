"""Alarms and reminders that survive a Wilco restart.

One daemon ``threading.Timer`` waits for each reminder. The pending schedule is also stored
on disk, so starting Wilco again restores reminders that are still in the future. Expired
reminders are discarded rather than unexpectedly spoken long after they were due.
"""
import datetime
import json
import threading
from pathlib import Path

import pythoncom

from windows.voice import speak

_STORE = Path.home() / ".wilco" / "reminders.json"
_lock = threading.RLock()
_reminders = {}  # id -> (timer, when, text)
_next_id = 1


def _save_locked():
    """Persist the future schedule. Caller holds _lock."""
    payload = [
        {"id": reminder_id, "when": when.isoformat(), "text": text}
        for reminder_id, (_, when, text) in sorted(_reminders.items())
    ]
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as error:
        print(f"[reminder persistence failed] {type(error).__name__}: {error}")


def _schedule(reminder_id, when, text):
    """Create, start, and return the daemon timer for one already-validated reminder."""
    delay = max(0.0, (when - datetime.datetime.now()).total_seconds())
    timer = threading.Timer(delay, _announce, args=(reminder_id, text))
    timer.daemon = True  # a pending reminder must never keep Wilco alive after it quits
    timer.start()
    return timer


def _announce(reminder_id, text):
    """Remove the fired reminder before speaking, so it cannot replay after a restart."""
    with _lock:
        _reminders.pop(reminder_id, None)
        _save_locked()
    try:
        pythoncom.CoInitialize()
        print("\n[reminder]")
        speak(text)
    except Exception as error:
        print(f"[reminder failed to speak] {text} ({type(error).__name__}: {error})")
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _restore():
    """Restore only valid, future reminders saved by a previous Wilco process."""
    global _next_id
    try:
        saved = json.loads(_STORE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return
    if not isinstance(saved, list):
        return

    now = datetime.datetime.now()
    with _lock:
        for item in saved:
            try:
                reminder_id = int(item["id"])
                when = datetime.datetime.fromisoformat(item["when"])
                text = str(item["text"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if reminder_id < 1 or not text or when <= now:
                continue
            _reminders[reminder_id] = (_schedule(reminder_id, when, text), when, text)
            _next_id = max(_next_id, reminder_id + 1)
        _save_locked()  # discard expired or malformed records from disk


def _parse(when):
    """A clock time like '07:00' or '19:30', or 'in 10' minutes, into a datetime."""
    text = when.strip().lower()
    now = datetime.datetime.now()

    relative = text.removeprefix("in").strip()
    if relative.replace(".", "", 1).isdigit():
        return now + datetime.timedelta(minutes=float(relative))

    for fmt in ("%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H"):
        try:
            parsed = datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
        target = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
        return target + datetime.timedelta(days=1) if target <= now else target
    return None


def set_reminder(when, text):
    """Set an alarm that speaks aloud at the right moment. when: 24-hour time like '07:00' or
    '19:30', or minutes from now as 'in 10'. Work the exact time out yourself — 'quarter past
    seven tonight' is '19:15', 'in half an hour' is 'in 30' — and say it back so a misheard
    number is caught. text: what to say when it fires. Future reminders survive a restart."""
    global _next_id
    target = _parse(when)
    if target is None:
        return (f"I couldn't read {when!r} as a time. Give it as 24-hour 'HH:MM', or "
                f"'in N' for minutes from now.")
    delay = (target - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        return f"{target:%H:%M} has already gone by."

    with _lock:
        reminder_id = _next_id
        _next_id += 1
        _reminders[reminder_id] = (_schedule(reminder_id, target, text), target, text)
        _save_locked()

    minutes = round(delay / 60)
    away = f"{minutes} minutes" if minutes < 90 else f"{round(delay / 3600, 1)} hours"
    return f"Reminder {reminder_id} set for {target:%H:%M} on {target:%A}, {away} from now: {text}"


def list_reminders():
    """Every reminder still waiting to go off, including reminders restored after a restart."""
    with _lock:
        pending = [(rid, when, text) for rid, (_, when, text) in sorted(_reminders.items())]
    if not pending:
        return "Nothing set."
    return "Waiting: " + "; ".join(
        f"{rid} at {when:%H:%M} — {text}" for rid, when, text in pending)


def cancel_reminder(which="all"):
    """Call off a reminder. which: its number from list_reminders, or 'all'."""
    with _lock:
        if which.strip().lower() == "all":
            count = len(_reminders)
            for timer, _, _ in _reminders.values():
                timer.cancel()
            _reminders.clear()
            _save_locked()
            if not count:
                return "Nothing set."
            return f"Cancelled {count} reminder{'s' if count != 1 else ''}."
        try:
            reminder_id = int(which)
        except ValueError:
            return f"{which} isn't a reminder number. Call list_reminders to see them."
        parked = _reminders.pop(reminder_id, None)
        if not parked:
            return f"There's no reminder {reminder_id}."
        parked[0].cancel()
        _save_locked()
    return f"Cancelled reminder {reminder_id}: {parked[2]}"


_restore()
