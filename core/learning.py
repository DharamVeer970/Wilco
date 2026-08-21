"""Learning & adaptation for Wilco: prompt optimization and a user feedback loop.

Two of the "learning" ideas from the roadmap, kept self-contained and off by default:

  - Feedback loop  : remember corrections and preferences ("not that, I meant X",
                     "always use X", "stop doing Y") and feed them back into the
                     system prompt so behaviour changes.
  - Prompt tuning  : learn which tools succeed for which query patterns (via the
                     analytics already collected) and surface concise guidance into
                     the system prompt, refining Wilco over time.

Nothing here calls the LLM. It is deterministic bookkeeping (store + match + render),
so it is fast and safe, and it layers on core/memory.py for persistence.

Enable with  WILCO_FEEDBACK_ENABLED=1  (feedback loop) in .env.
"""
import re

from config import _flag
from core.memory import get_preference, set_preference

FEEDBACK_ENABLED = _flag("WILCO_FEEDBACK_ENABLED", False)
PROMPT_TUNING_ENABLED = _flag("WILCO_PROMPT_TUNING_ENABLED", False)

# corrections are just preferences; these keys never collide with voice/speed defaults
_CORRECTION_KEY = "corrections"
_TUNING_KEY = "prompt_tuning"

# --- feedback loop -------------------------------------------------------------------
# "always ...", "don't/stop/never ...", and "use ... not ..." are the correction shapes
# people actually say. Each is stored verbatim and rendered out later. We deliberately do
# NOT try to interpret them — the model reading the rendered list is far better at that.
_ALWAYS = re.compile(r"\b(?:always|from now on|please remember|keep this)\b", re.I)
_NEVER = re.compile(r"\b(?:never|do_not|stop|don'?t|avoid|refrain)\b", re.I)  # S5855 fixed: removed redundant 'dont'
_BUT = re.compile(r"\bnot\b.*?\b(?:but|instead|rather)\b", re.I)


def is_correction(utterance: str) -> bool:
    """Guess whether a spoken sentence is a correction rather than a request."""
    if not isinstance(utterance, str) or not utterance.strip():
        return False
    u = utterance.lower()
    if _ALWAYS.search(u) and len(utterance.split()) <= 16:
        return True
    if _NEVER.search(u) and len(utterance.split()) <= 16:
        return True
    # "that's not ... it's ..." / "not the left one, the right one"
    if "not" in u and re.search(r"\b(?:that'?s?|this|it|i meant|use|open)\b", u):
        return True
    return False


def record_correction(utterance: str):
    """Store a correction so it shapes future behaviour (no-op unless enabled)."""
    if not FEEDBACK_ENABLED:
        return
    if not is_correction(utterance):
        return
    corrections = list(get_preference(_CORRECTION_KEY, []) or [])
    if utterance not in corrections:
        corrections.append(utterance)
        # keep a bounded, most-recent-first history
        set_preference(_CORRECTION_KEY, corrections[-50:])


def get_corrections() -> list:
    """The stored corrections (most recently added first)."""
    return list(reversed(get_preference(_CORRECTION_KEY, []) or []))


def correction_prompt_snippet() -> str:
    """Render stored corrections as a short block the system prompt can carry."""
    corrections = get_corrections()
    if not corrections:
        return ""
    lines = [f"- The user once said: {c}" for c in corrections[:12]]
    return ("A few things the user has told me to remember:\n" + "\n".join(lines)
            + "\nApply these going forward.") if lines else ""


# --- prompt tuning -------------------------------------------------------------------
_QUERY_KEYWORDS = {
    "web": ("search", "find", "google", "look up", "search for"),
    "weather": ("weather", "temperature", "rain", "forecast"),
    "crypto": ("crypto", "bitcoin", "ethereum", "price", "coin"),
    "file": ("open", "folder", "file", "directory", "create", "rename"),
    "system": ("cpu", "memory", "disk", "process", "battery", "status"),
}


def _topic_of(query: str) -> str | None:
    lower = query.lower()
    for topic, keywords in _QUERY_KEYWORDS.items():
        if any(k in lower for k in keywords):
            # most specific wins: longer keyword overlap beats earlier topic
            if topic == "web":
                continue
            return topic
    return None


def suggest_reliable_tools(query: str, analytics) -> str:
    """Using analytics, recommend which tools are reliable for this query's topic.

    Pass the core.analytics singleton. Returns a one-line hint, or "" if unsure.
    """
    if not PROMPT_TUNING_ENABLED:
        return ""
    topic = _topic_of(query)
    if not topic:
        return ""
    stats = analytics.get_all_stats()
    # find tools whose name or description mentions the topic
    relevant = []
    for name, s in stats.items():
        if s.total_calls < 3:  # not enough data yet
            continue
        if topic in name or topic in getattr(s, "name", ""):
            relevant.append(s)
    if len(relevant) < 2:
        return ""
    reliable = [s.name for s in relevant if s.success_rate >= 0.8][:3]
    return (f"[Learned] For {topic} requests, these tools have been reliable: "
            f"{', '.join(reliable)}.") if reliable else ""


def record_tuning_result(query: str, tool_name: str, success: bool):
    """Feed a tool result back into long-term tuning memory (no-op unless enabled)."""
    if not PROMPT_TUNING_ENABLED:
        return
    from core.memory import learn_pattern
    learn_pattern(query[:120], [tool_name], success=success)
