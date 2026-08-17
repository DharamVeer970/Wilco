"""User experience helpers for Wilco: progressive disclosure, clarification questions,
and multi-modal response shaping.

Three small, self-contained pieces:

  - Progressive disclosure : given a long answer, produce a short spoken version and keep
    the full detail available for a follow-up ("tell me more"). Reduces speaking time.
  - Clarification         : detect when a request is ambiguous and formulate targeted
    questions instead of guessing.
  - Presentation          : shape a reply into speech + an on-screen summary so the same
    result can be spoken briefly and shown verbatim (multi-modal).

All functions are pure and dependency-light; nothing here runs on its own.
"""
import re

# --- progressive disclosure ----------------------------------------------------------
# A "disclosure" splits a result into a terse spoken summary and a fuller written version.
def progressive_reveal(full_text: str, spoken_max: int = 280, detail_max: int = 2000):
    """Split a response into (spoken_summary, detail). The summary is the first useful
    sentence(s); the detail keeps the substance for those who want it.

    Returns a dict: {"summary": str, "detail": str, "continued": bool}. If the text is
    already short, summary == detail and continued is False.
    """
    if not full_text:
        return {"summary": "", "detail": "", "continued": False}
    text = " ".join(str(full_text).split())  # normalise whitespace
    if len(text) <= spoken_max:
        return {"summary": text, "detail": text, "continued": False}

    # first sentence boundary (don't cut mid-sentence at the limit)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary, used = "", 0
    for s in sentences:
        if used + len(s) + 1 > spoken_max and summary:
            break
        summary += s + " "
        used = len(summary)
    summary = summary.strip()
    if not summary:
        summary = text[:spoken_max - 1].rstrip() + "…"
    detail = text[:detail_max] + ("…" if len(text) > detail_max else "")
    return {"summary": summary, "detail": detail, "continued": len(text) > len(summary)}


# --- clarification -------------------------------------------------------------------
_AMBIGUOUS_OPEN = r"\b(?:it|that|those|them|there|the file|the folder)\b"
_AMBIGUOUS_TIME = r"\b(?:later|after|the next one|which|what kind)\b"
_REPEATED_LAST = r"(?:him|her|them)\b"
# A request with no concrete noun is usually under-specified for a voice assistant.
_UNDERSPECIFIED = re.compile(
    r"^\s*(?:can you|please|hey |could you|will you)?\s*"
    r"(?:do (?:that|this|it)|deal with (?:it|that)|make (?:it|that) (?:work|happen)|"
    r"fix (?:it|that)|show (?:it|that)?|tell me (?:about )?(?:it|that))\s*[?.!]*$",
    re.I)

# generic clarifying follow-ups, keyed by the kind of ambiguity spotted
_QUESTION_BANK = {
    "which": "Could you tell me which one you mean — say the name or the place?",
    "what": "What exactly would you like me to do?",
    "when": "When should that happen — now or at a particular time?",
    "default": "I didn't quite catch which one. Could you narrow it down for me?",
}


def needs_clarification(query: str) -> bool:
    """Heuristic guess that a spoken request is under-specified and worth a question."""
    if not isinstance(query, str) or not query.strip():
        return False
    if _UNDERSPECIFIED.match(query.strip()):
        return True
    words = re.findall(r"\b[a-z]+\b", query.lower())
    # pronoun-heavy with no concrete noun
    pronouns = sum(1 for w in words if w in
                   {"it", "that", "those", "them", "there", "this", "its", "which"})
    return pronouns >= 1 and len(words) <= 10 and not any(
        w in words for w in {"file", "folder", "app", "open", "play", "set"}
    )


def clarification_question(query: str) -> str:
    """Pick a clarification question suited to what is unclear ('' if none needed)."""
    if not needs_clarification(query):
        return ""
    lower = query.lower()
    if "what" in lower:
        return _QUESTION_BANK["what"]
    if "which" in lower or "which one" in lower:
        return _QUESTION_BANK["which"]
    if re.search(r"\b(?:when|later|after|time)\b", lower):
        return _QUESTION_BANK["when"]
    return _QUESTION_BANK["default"]


# --- multi-modal speaking/writing shaping ---------------------------------------------
_HEADING = re.compile(r"^#{1,6}\s+", re.M)
_FENCE = re.compile(r"```.*?```", re.S)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_URL_RE = re.compile(r"https?://\S+")


def shape_presentation(full_text: str):
    """Return (speech_text, screen_text) — a spoken version and a richer written version.

    Speech strips markdown fences/headings but keeps whole sentences and key labels
    (emails, URLs, numbers). Screen keeps the full original for a visual pop-up.
    """
    if not full_text:
        return "", ""
    screen = str(full_text).strip()
    speech = _FENCE.sub(" ", screen)
    speech = _HEADING.sub("", speech)
    speech = re.sub(r"[*_`>]", "", speech)
    speech = re.sub(r"\s+", " ", speech).strip()
    return speech, screen