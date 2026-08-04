"""Alarms and reminders that speak up on their own.

One threading.Timer per reminder rather than a polling loop — the OS does the waiting, so
nothing burns CPU counting seconds, and cancelling is just Timer.cancel().

The model does the language part: it turns "quarter past seven" or "in ten minutes" into a
concrete time and passes that in. Parsing English dates in Python would be a library and a
pile of edge cases to do worse than the model already does for free.

Reminders live in memory, so they are forgotten if Wilco restarts.
"""
import datetime
import threading

import pythoncom

from windows.voice import speak

_reminders = {}  # id -> (timer, when, text)
_next_id = 1


def _announce(reminder_id, text):
    """Speak from the timer thread, in whatever voice Wilco is using. The thread needs its own
    COM apartment; windows/voice.py gives it its own fallback voice object to match."""
    _reminders.pop(reminder_id, None)
    try:
        pythoncom.CoInitialize()
        print("\n[reminder]")
        speak(text)
    except Exception as e:
        print(f"[reminder failed to speak] {text} ({type(e).__name__}: {e})")
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


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
        # 7 AM said at 9 PM means tomorrow morning, not a time that has already gone
        return target + datetime.timedelta(days=1) if target <= now else target
    return None


def set_reminder(when, text):
    """Set an alarm or reminder that speaks aloud at the right moment.

    when: a 24-hour clock time such as '07:00' or '19:30', or minutes from now as 'in 10'.
    Work out the exact time yourself from what the user said — 'quarter past seven tonight'
    becomes '19:15', 'in half an hour' becomes 'in 30' — and confirm the real time back to
    them so a misheard number is caught before it matters.
    text: what to say when it goes off, phrased as you'd say it out loud.

    Reminders are lost if Wilco is restarted; say so if the user sets one far ahead."""
    global _next_id
    target = _parse(when)
    if target is None:
        return (f"I couldn't read {when!r} as a time. Give it as 24-hour 'HH:MM', or "
                f"'in N' for minutes from now.")
    delay = (target - datetime.datetime.now()).total_seconds()
    if delay <= 0:
        return f"{target:%H:%M} has already gone by."

    reminder_id = _next_id
    _next_id += 1
    timer = threading.Timer(delay, _announce, args=(reminder_id, text))
    timer.daemon = True  # a pending reminder must never keep Wilco alive after it quits
    timer.start()
    _reminders[reminder_id] = (timer, target, text)

    minutes = round(delay / 60)
    away = f"{minutes} minutes" if minutes < 90 else f"{round(delay / 3600, 1)} hours"
    return f"Reminder {reminder_id} set for {target:%H:%M} on {target:%A}, {away} from now: {text}"


def list_reminders():
    """Every reminder still waiting to go off."""
    if not _reminders:
        return "Nothing set."
    return "Waiting: " + "; ".join(
        f"{rid} at {when:%H:%M} — {text}" for rid, (_, when, text) in sorted(_reminders.items()))


def cancel_reminder(which="all"):
    """Call off a reminder. which: its number from list_reminders, or 'all'."""
    if which.strip().lower() == "all":
        count = len(_reminders)
        for timer, _, _ in _reminders.values():
            timer.cancel()
        _reminders.clear()
        return f"Cancelled {count} reminder{'s' if count != 1 else ''}." if count else "Nothing set."
    try:
        reminder_id = int(which)
    except ValueError:
        return f"{which} isn't a reminder number. Call list_reminders to see them."
    parked = _reminders.pop(reminder_id, None)
    if not parked:
        return f"There's no reminder {reminder_id}."
    parked[0].cancel()
    return f"Cancelled reminder {reminder_id}: {parked[2]}"
