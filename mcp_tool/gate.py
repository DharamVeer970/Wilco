"""One dangerous action per caller, parked until the user says yes out loud.

Anything that writes, deletes or changes system state goes through _park() instead of
running. The model relays the question, the next utterance answers it, and the model
calls confirm_yes() or cancel_action(). Nothing here runs on its own.
"""

import contextvars
import re

# Keyed by caller, so two clients never confirm each other's action. The voice loop is "local".
session = contextvars.ContextVar("session", default="local")
_pending = {}  # session -> (spoken description, zero-arg callable)

STRIP = " .,!?;:'\""
# Politeness carries no decision. "Thank you" on its own is not consent, so it is peeled off
# before judging: "yes please" is a yes, bare "thanks" is not.
_POLITE_TAIL = re.compile(r"[\s,]*(?:please|thanks?|thank\s+you|jarvis|wilco|sir|bro|man)[\s,]*$",
                          re.I)
_YES = re.compile(
    r"(?:(?:yes|yeah|yep|yup|yah|ya|sure|ok|okay|kk|alright|all right|fine|right|correct|"
    r"confirm(?:ed)?|affirmative|definitely|absolutely|certainly|of course|course|"
    r"do it|go ahead|go on|carry on|proceed|continue|agreed?|i do|that's right|thats right|"
    r"haan|han|haa|haan ji|ji haan|ji|theek hai|thik hai|thike|theek|thik|"
    r"kar do|kardo|karo|chalu karo|bilkul|zaroor|sahi hai|sahi)[\s,]*)+", re.I)
_NO = re.compile(
    r"(?:(?:no|nope|nah|na|not now|don't|dont|do not|cancel|stop|abort|wait|hold on|"
    r"never ?mind|forget it|leave it|negative|skip|rehne do|"
    r"nahi|nahin|nai|mat karo|mat|ruko|rukho|band karo|chhod do|chod do)[\s,]*)+", re.I)


def _reply_kind(text):
    """Is a spoken reply a yes, a no, or neither?

    'Neither' is the important one. Treating anything unrecognised as a no meant a
    mistranscription silently cancelled the thing the user had just asked for, and treating
    it as a yes would shut the machine down on a cough. Unclear is its own answer: ask again.
    """
    text = (text or "").strip(STRIP).lower()
    while True:
        shorter = _POLITE_TAIL.sub("", text).strip(STRIP)
        if shorter == text:
            break
        text = shorter
    if not text:
        return "unclear"  # nothing left but politeness, which decides nothing
    if _NO.fullmatch(text):
        return "no"
    if _YES.fullmatch(text):
        return "yes"
    return "unclear"


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
