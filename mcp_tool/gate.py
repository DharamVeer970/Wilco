"""One dangerous action per caller, parked until the user says yes out loud.

Anything that writes, deletes or changes system state goes through _park() instead of
running. The model relays the question, the next utterance answers it, and the model
calls confirm_yes() or cancel_action(). Nothing here runs on its own.
"""

import contextvars

# Keyed by caller, so two clients never confirm each other's action. The voice loop is "local".
session = contextvars.ContextVar("session", default="local")
_pending = {}  # session -> (spoken description, zero-arg callable)


def _park(description, action):
    """Hold an action until confirmed. Returns what the model should tell the user."""
    _pending[session.get()] = (description, action)
    return (f"NOT DONE. This needs the user's spoken permission first. Ask them, in your own "
            f"words, whether to go ahead with: {description}. Do not claim it is done.")


def confirm_yes():
    """Run the action the user was just asked to confirm. Call this ONLY when they clearly
    agree — yes, yeah, go ahead, do it. Never call it on your own initiative."""
    parked = _pending.pop(session.get(), None)
    if not parked:
        return "There is nothing waiting to be confirmed."
    description, action = parked
    try:
        result = action()
    except Exception as e:
        return f"Tried to {description} but it failed: {type(e).__name__}: {e}"
    return f"Done: {description}." + (f" {result}" if isinstance(result, str) and result else "")


def cancel_action():
    """Drop the action awaiting confirmation. Call this when the user says no, stop, or cancel."""
    parked = _pending.pop(session.get(), None)
    if not parked:
        return "There was nothing waiting."
    return f"Cancelled: {parked[0]}. Nothing was changed."
