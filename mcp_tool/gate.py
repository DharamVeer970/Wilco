"""One dangerous action, parked until the user says yes out loud.

Anything that writes, deletes or changes system state goes through _park() instead of
running. The model relays the question, the next utterance answers it, and the model
calls confirm_yes() or cancel_action(). Nothing here runs on its own.
"""

_pending = None  # (spoken description, zero-arg callable)


def _park(description, action):
    """Hold an action until confirmed. Returns what the model should tell the user."""
    global _pending
    _pending = (description, action)
    return (f"NOT DONE. This needs the user's spoken permission first. Ask them, in your own "
            f"words, whether to go ahead with: {description}. Do not claim it is done.")


def confirm_yes():
    """Run the action the user was just asked to confirm. Call this ONLY when they clearly
    agree — yes, yeah, go ahead, do it. Never call it on your own initiative."""
    global _pending
    if not _pending:
        return "There is nothing waiting to be confirmed."
    description, action = _pending
    _pending = None
    try:
        result = action()
    except Exception as e:
        return f"Tried to {description} but it failed: {type(e).__name__}: {e}"
    return f"Done: {description}." + (f" {result}" if isinstance(result, str) and result else "")


def cancel_action():
    """Drop the action awaiting confirmation. Call this when the user says no, stop, or cancel."""
    global _pending
    if not _pending:
        return "There was nothing waiting."
    description, _ = _pending
    _pending = None
    return f"Cancelled: {description}. Nothing was changed."
