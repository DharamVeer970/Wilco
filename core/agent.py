"""The tool-calling loop — Wilco's actual decision making.

The old path classified one utterance into one action from a fixed enum, then handed back.
That is why things got "understood" but nothing followed: no second step, no reading of the
result, no conversation afterwards. Here the model calls tools, reads what they returned,
and either calls more or talks. Acting and chatting are the same turn, which is what makes
it hold a thread.
"""
import json
import os
import platform
import re
import time
from pathlib import Path

import mcp_tool
import config as _config
from config import (EMPTY_TRIES, MAX_MESSAGES, MAX_STEPS, TOOL_LIMIT, MEMORY_ENABLED,
                    MEMORY_TURNS, chat_model)
from core import roman
from core.brain import PROMPTS, llm
from core.analytics import record_tool_call
from core.memory import add_conversation_turn, get_recent_conversations
from core.learning import (record_correction, correction_prompt_snippet,
                           is_correction, suggest_reliable_tools, record_tuning_result)
from core.analytics import analytics as _analytics
from core.retry import retry_call
from core import batch as _batch
from windows import voice
from windows.speech import speak

SYSTEM_PROMPT = (PROMPTS / "agent.txt").read_text(encoding="utf-8").strip()

# Stable prompt-cache prefix: history[0] is only ever replaced wholesale by _refresh_prompt.
history = [{"role": "system", "content": SYSTEM_PROMPT}]


def _restore_memory():
    """Restore a bounded, opt-in local conversation context without replaying tool calls."""
    if not MEMORY_ENABLED or not MEMORY_TURNS:
        return
    for turn in get_recent_conversations(MEMORY_TURNS):
        user_text = turn.get("user")
        reply = turn.get("assistant")
        if isinstance(user_text, str) and user_text and isinstance(reply, str) and reply:
            history.extend((
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": reply},
            ))


def _persist_turn(user_text, reply, tools=()):
    """Persist a completed exchange only when the user explicitly enabled local memory."""
    if MEMORY_ENABLED and user_text and reply:
        add_conversation_turn(user_text, reply, [name for name, _ in tools])


_restore_memory()


def _refresh_prompt():
    """Use prompt edits on the next turn instead of requiring an app restart."""
    global SYSTEM_PROMPT
    latest = (PROMPTS / "agent.txt").read_text(encoding="utf-8").strip()
    if latest != SYSTEM_PROMPT:
        SYSTEM_PROMPT = latest
        history[0] = {"role": "system", "content": SYSTEM_PROMPT}


def remember_local_turn(user_text, result):
    """Keep an instant command available when a later turn needs AI reasoning."""
    _repair()
    history.extend((
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": result},
    ))
    _persist_turn(user_text, result)
    _trim()

# Everything below is spoken aloud — strip machinery, stage directions, markdown and <TALK> tags.
_TALK_TAG = re.compile(r"</?TALK\s*>|/?talk", re.I)
_FENCE = re.compile(r"```.*?```", re.S)
_BRACKETED = re.compile(r"\[[^\[\]]{0,300}\]")          # [Checking system settings...]
_MARKDOWN = re.compile(r"\*{1,3}|#{1,6}\s*|`+")
# Keep only speech-carryable chars (categories L/M/N + whitelist) — emoji and blocklists stall TTS.
_SYMBOL_KEEP = set(".,!?;:'\"()@#%…—–-_&/+-")
from functools import lru_cache as _lru_cache
@_lru_cache(maxsize=2048)
def _cat_is_keepable(ch: str) -> bool:
    import unicodedata as _ud
    return _ud.category(ch)[0] in "LMN"

def _clean_symbols(text):
    return "".join(ch for ch in text
                   if ch.isspace() or _cat_is_keepable(ch)
                   or ch in _SYMBOL_KEEP or ch in "\u200d\u200c\ufe0f")
# Leading list markers ("-", "•", "1.") read aloud as noise; drop just the marker, keep the words.
_LIST = re.compile(r"^\s*(?:[-*•◦▪–]|\d{1,2}[.)])\s+")
_MACHINERY = ("tool_call_id", "tool_name", "tool_calls", '"parameters"', '"arguments"')
_META_LINE = re.compile(r"^\s*(?:note|disclaimer|reasoning|thought|action)\s*:", re.I)
_PUNCT_ONLY = re.compile(r"^[\s\[\]{}(),:\"']*$")
# Drop links (and a bracket that only wrapped one) so URLs are never read aloud.
_URL = re.compile(r"https?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.I)
_EMPTY_PAREN = re.compile(r"\(\s*\)")
_WS_SQUASH = re.compile(r"\s{2,}")
# Per-tool history trim limits; global fallback 2000.
_TOOL_RESULT_MAX = 2000
# A tool result that starts with this means the action is parked awaiting user confirmation.
_NOT_DONE = "NOT DONE"
_TOOL_RESULT_MAX_BY_TOOL = {
    "web_search": 1200,
    "read_web_page": 1500,
    "search_file_contents": 1500,
    "find_files": 1200,
    "list_folder_contents": 1200,
    "list_installed_apps": 1200,
    "list_open_windows": 1000,
    "wikipedia_summary": 1200,
    "wikipedia_article": 1500,
}


def _speakable(text):
    """Strip tool-call JSON, stage directions, markdown and links out of what gets spoken."""
    if not text:
        return ""
    text = _TALK_TAG.sub("", text)
    kept = []
    for line in _clean_symbols(_MARKDOWN.sub("", _FENCE.sub("", text))).splitlines():
        if any(word in line for word in _MACHINERY) or _META_LINE.match(line):
            continue
        line = _BRACKETED.sub("", line)
        line = _URL.sub("", line)
        line = _EMPTY_PAREN.sub("", _LIST.sub("", line))
        line = _WS_SQUASH.sub(" ", line).strip()
        if _PUNCT_ONLY.match(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


# Devanagari is transliterated locally (core/roman.py) instead of costing an API call.
def _romanise(text):
    """Keep Hindi script for Hindi neural voices; transliterate it for other voices."""
    if not roman.has_devanagari(text):
        return text
    if voice.current()[1].startswith("hi-IN-"):
        return text
    return roman.romanise(text)


# The model sometimes TYPES a tool call instead of making one, or narrates an action it never took.
_WRITTEN = re.compile(r"[\[{].*[\]}]", re.S)
_CLAIMED = re.compile(
    r"\b(?:i(?:'ve| have)?\s+(?:just\s+|now\s+)?(?:opened|set|changed|closed|sent|created|"
    r"deleted|increased|decreased|reduced|switched|started|launched|turned|played|typed|"
    r"saved|updated|added|removed|adjusted)|\b(?:reminder|alarm|timer|volume|brightness|speed)"
    r"\s+(?:is\s+|has\s+been\s+)?set\b|"
    r"\b(?:it'?s|that'?s|all)\s+done\b|"
    r"\b(?:turned|set|cranked|raised|lowered|boosted|changed)\s+(?:the\s+)?"
    r"(?:volume|brightness|sound)\s+(?:up|down)\b|"
    r"\bvolume\s+(?:up|down)\b|\b(?:muted|unmuted|dimmed|brightened)\b|"
    r"\b(?:volume|brightness|sound|speed)\s+(?:is|is now|currently is|now)\s+"
    r"(?:at\s+)?\d+\s?(?:percent|%)?\b)", re.I)
# Claims that defaults/code changed require proof of a completed edit, not just a tool run.
_PERSISTENT_CLAIM = re.compile(
    r"\b(?:default|configuration|config|code|cache|workflow|search\s+results?)\b"
    r"[\s\S]{0,90}?\b(?:changed|updated|reduced|switched|replaced|implemented|optimised|optimized)\b"
    r"|\b(?:changed|updated|reduced|switched|replaced|implemented|optimised|optimized)\b"
    r"[\s\S]{0,90}?\b(?:default|configuration|config|code|cache|workflow|search\s+results?)\b", re.I)


def _written_calls(text):
    """Tool calls the model wrote out as text instead of making. Returns [(name, arguments)]."""
    if not text or not any(k in text for k in ("tool_name", "tool_call_id", '"name"')):
        return []
    block = _WRITTEN.search(text)
    if not block:
        return []
    try:
        data = json.loads(block.group(0))
    except json.JSONDecodeError:
        return []
    found = []
    for item in (data if isinstance(data, list) else [data]):
        if not isinstance(item, dict):
            continue
        name = next((item[k] for k in ("tool_name", "name") if isinstance(item.get(k), str)), "")
        arguments = next((item[k] for k in ("parameters", "arguments")
                          if isinstance(item.get(k), dict)), {})
        if name in mcp_tool.REGISTRY:
            found.append((name, arguments))
    return found


def _query_for_tools():
    """What the tool router ranks against — latest ask plus last tool results.

    Optimized: only last 2 turns, truncated at 500 chars to keep ranking cheap.
    """
    recent = []
    for message in history[-2:]:
        content = message.get("content")
        if isinstance(content, str) and content:
            recent.append(content[:500])
    return " ".join(recent)


def _ask():
    """One completion, retried when the provider generates nothing at all.

    Cohere intermittently answers a perfectly valid request with 422
    NO_TOOL_CALL_OR_RESPONSE_GENERATED — no tool call, no text, nothing. It is a flake on
    their side, not a fault in the request: the identical message shape succeeded twelve times
    out of twelve when tested. Nothing here can prevent it, so it is retried with a little
    backoff rather than costing the user their turn. Any other error is real and raised at once.
    """
    # Routed compact tool list + cached stable prefix keep the payload far below the old 8K tokens.
    tools = mcp_tool.dispatch_tools(_query_for_tools(), TOOL_LIMIT)
    for attempt in range(1, EMPTY_TRIES + 1):
        try:
            return llm.chat.completions.create(
                model=chat_model, messages=history, tools=tools
            ).choices[0].message
        except Exception as e:
            if attempt == EMPTY_TRIES or "NO_TOOL_CALL_OR_RESPONSE" not in str(e):
                raise
            print(f"  (empty generation — retry {attempt} of {EMPTY_TRIES - 1})")
            time.sleep(attempt)


def _as_dict(message):
    """Only the fields the API accepts back — providers reject their own extra keys."""
    data = message.model_dump(exclude_none=True)
    return {k: v for k, v in data.items() if k in ("role", "content", "tool_calls")}


def _repair():
    """Drop a trailing tool_calls message that never got its results.

    One of these is fatal and permanent: every later request is rejected with "tool_call_ids
    did not have response messages", so the assistant is dead until restart. Cheap to check,
    so it is checked before every turn rather than trusted not to happen.
    """
    while len(history) > 1:
        answered = {m.get("tool_call_id") for m in history if m.get("role") == "tool"}
        wanted = {c["id"] for m in history if m.get("role") == "assistant"
                  for c in (m.get("tool_calls") or [])}
        orphans = wanted - answered
        if not orphans:
            return
        cut = next(i for i, m in enumerate(history)
                   if m.get("role") == "assistant"
                   and any(c["id"] in orphans for c in (m.get("tool_calls") or [])))
        print(f"[history repair] dropping {len(history) - cut} messages with unanswered tool calls")
        del history[cut:]


def _trim():
    """Drop the oldest turns, never splitting a tool call from its result.

    A tool message whose matching assistant tool_call has been trimmed away is a hard 400
    from every provider, so we always cut forward to the next user message.
    """
    while len(history) > MAX_MESSAGES:
        del history[1]
        while len(history) > 1 and history[1].get("role") != "user":
            del history[1]


def _turn_failed(checkpoint, acted, error):
    print("Agent error:", error)
    # Roll back the whole turn — a stranded tool call breaks every request that follows it.
    del history[checkpoint:]
    # If tools already ran, saying "I couldn't reach my brain" would be a lie about a machine the user sees.
    speak("I did that, but couldn't put the reply together. Ask again for the details?"
          if acted else "I couldn't reach my brain just then. Say that again?")


# Read-only calls that are safe to run concurrently (e.g. "weather and price").
_PARALLEL_READ_ONLY = frozenset({
    "web_search", "read_web_page", "wikipedia_summary", "wikipedia_article",
    "weather", "define", "crypto_price", "convert_currency", "news_headlines",
    "read_file", "list_folder_contents", "search_file_contents", "find_files",
    "get_volume", "get_screen_brightness", "mute_state", "list_installed_apps",
    "list_open_windows",
})

_SKIP_NOTE = "Skipped: a previous action is awaiting the user's explicit confirmation."


def _parse_arguments(call):
    try:
        return json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        return {}


def _trim_result(label, result):
    limit = _TOOL_RESULT_MAX_BY_TOOL.get(label, _TOOL_RESULT_MAX)
    return result[:limit] + "\n…(rest trimmed to keep responses fast)" if len(result) > limit else result


def _skip_remaining(calls, done_call):
    # Still answer every tool call in the batch so the next request has valid API history.
    for skipped in calls[calls.index(done_call) + 1:]:
        history.append({"role": "tool", "tool_call_id": skipped.id, "content": _SKIP_NOTE})


def _run_parallel(calls):
    """Run independent read-only calls concurrently; returns (results, parked)."""
    def _make_fn(c):
        args = _parse_arguments(c)
        return lambda c=c, a=args: retry_call(mcp_tool.call, c.function.name, a, max_retries=2)

    start = time.time()
    paired = [(c.function.name, _make_fn(c)) for c in calls]
    results, parked = [], False
    for call, (label, result) in zip(calls, _batch.run_parallel(paired)):
        print(f"  -> {label}({call.function.arguments})")
        print(f"     {result[:160]}")
        success = not result.startswith(("Error calling", "Wrong arguments", "No tool called"))
        record_tool_call(label, success, time.time() - start)
        result = _trim_result(label, result)
        history.append({"role": "tool", "tool_call_id": call.id, "content": result})
        results.append((label, result))
        if result.startswith(_NOT_DONE):
            _skip_remaining(calls, call)
            parked = True
            break
    return results, parked


def _run_one(call):
    """Run one tool call; returns (name, result) with failures returned as strings, never raised."""
    arguments = _parse_arguments(call)
    print(f"  -> {call.function.name}({arguments})")
    start = time.time()
    try:
        result = retry_call(mcp_tool.call, call.function.name, arguments, max_retries=2)
        record_tool_call(call.function.name, True, time.time() - start)
        print(f"     {result[:160]}")
    except Exception as e:
        record_tool_call(call.function.name, False, time.time() - start, str(e))
        result = f"Error calling {call.function.name}: {type(e).__name__}: {e}"
        print(f"     ERROR: {result[:160]}")
    return call.function.name, _trim_result(call.function.name, result)


def _run_calls(calls):
    """Execute the assistant's tool calls, recording analytics for each."""
    if len(calls) > 1 and all(c.function.name in _PARALLEL_READ_ONLY for c in calls):
        return _run_parallel(calls)
    results, parked = [], False
    for call in calls:
        name, result = _run_one(call)
        history.append({"role": "tool", "tool_call_id": call.id, "content": result})
        results.append((name, result))
        if result.startswith(_NOT_DONE):
            _skip_remaining(calls, call)
            parked = True
            break
    return results, parked


def _run_written(written):
    """Run the tool calls the model typed out as text, then tell it they have been run."""
    results = [f"{name}: {retry_call(mcp_tool.call, name, arguments, max_retries=2)}" for name, arguments in written]
    for line in results:
        print(f"  -> {line[:160]}  [recovered from text]")
    history.append({"role": "user", "content":
                    "Those tool calls were written as text, so they have now been "
                    "run for you. Results — " + "; ".join(results) +
                    ". Tell the user what happened, in a sentence or two."})


def _nudge():
    print("  [claimed an action without calling anything — asking again]")
    history.append({"role": "user", "content":
                    "You described that as done, but you called no tool, so "
                    "nothing actually happened. Call the tool that does it now, "
                    "or say plainly that you can't."})


def _has_completed_edit(turn_tools):
    """Whether this turn has proof that a persistent local change actually landed."""
    return any(name in {"edit_file", "write_file"} and not result.startswith(_NOT_DONE)
               for name, result in turn_tools)


def _failed_tool_names(turn_tools):
    """Tools in this turn whose result was an error, not a success.

    The model can present an errored call as if it succeeded — the exact false-success
    from the harness. Naming the failures lets the next prompt correct it honestly.
    """
    return tuple(name for name, result in turn_tools
                 if result.startswith(("Error", "Wrong arguments", "No tool called", _NOT_DONE))
                 or result.lower().startswith(f"{name} failed:"))


def _no_calls(message, acted, nudged, turn_tools=()):
    """Deal with a message that called nothing. 'ran', 'nudged' or 'spoke'."""
    written = _written_calls(message.content)
    if written:
        _run_written(written)
        return "ran"
    spoken = _romanise(_speakable(message.content))
    if _PERSISTENT_CLAIM.search(spoken) and not _has_completed_edit(turn_tools):
        print("  [claimed a persistent change without a completed edit - asking again]")
        history.append({"role": "user", "content":
                        "You claimed a code/default/configuration change, but no completed "
                        "edit or write tool result proves it. Nothing persistent changed. "
                        "Correct the user plainly, or make the verified change now."})
        return "nudged"
    if not acted and not nudged and _CLAIMED.search(spoken):
        _nudge()
        return "nudged"
    failed = _failed_tool_names(turn_tools)
    if failed and _CLAIMED.search(spoken):
        # A tool errored earlier in this turn, yet the reply presents it as done.
        print(f"  [tool(s) {', '.join(failed)} errored - not a success, asking again]")
        history.append({"role": "user", "content":
                        "The tool(s) " + ", ".join(failed) +
                        " returned an error this turn, so that action did not happen. "
                        "Tell the user exactly which tool errored and what the error was, "
                        "or retry it once and then report honestly."})
        return "nudged"
    speak(spoken or "Done.")
    return "spoke"


def _process_tool_calls(message, turn_tools, goal_tracker):
    """Handle tool calls in one turn, return parked flag."""
    for _c in message.tool_calls:
        goal_tracker.add_goal(_c.function.name)
    results, parked = _run_calls(message.tool_calls)
    turn_tools.extend(results)
    for _i in range(len(results)):
        goal_tracker.complete(_i)
    return parked


def _handle_text_outcome(message, acted, nudged, turn_tools, user_text):
    """Handle a text-only assistant message, return (acted, nudged, should_return)."""
    outcome = _no_calls(message, acted, nudged, turn_tools)
    if outcome == "spoke":
        _persist_turn(user_text, _romanise(_speakable(message.content)) or "Done.", turn_tools)
        # learn which tools worked for this query - enhances next time
        for name, result in turn_tools:
            record_tuning_result(user_text, name, success=not result.startswith("Error"))
        _trim()
        return acted, nudged, True
    acted = acted or outcome == "ran"
    nudged = nudged or outcome == "nudged"
    return acted, nudged, False


def _build_extra(user_text):
    """Ephemeral per-turn system hints; removed after the turn so the cached prefix stays stable."""
    # Environment resolved live (never hardcoded) so the model stops guessing paths/usernames.
    extra = [
        "Environment (resolved live on this machine, trust these over any guess):\n"
        f"- Current working directory: {os.getcwd()}\n"
        f"- User home directory: {Path.home()}\n"
        f"- OS: {platform.system()} {platform.release()}\n"
        "When the user says 'current directory', 'here', or 'this folder', use the cwd. "
        "Never invent user names or paths under C:/Users — derive paths only from these values "
        "or paths the user explicitly gave."
    ]
    corr = correction_prompt_snippet()
    if corr:
        extra.append(corr)
    try:
        hint = suggest_reliable_tools(user_text, _analytics)
        if hint:
            extra.append(hint)
    except Exception:
        pass
    return extra


def _agent_loop(checkpoint, user_text, acted, turn_tools, clean_ephemeral):
    """Gather -> Act -> Verify loop; returns (spoke, acted). Spoke is False only on a hard error."""
    nudged = False
    goal_tracker = _batch.SubGoalTracker("turn")

    def _flush_analytics():
        try:
            _analytics.flush()
        except Exception:
            pass

    for _ in range(MAX_STEPS):
        try:
            message = _ask()
        except Exception as e:
            _turn_failed(checkpoint, acted, e)
            _flush_analytics()
            return False, acted
        history.append(_as_dict(message))
        if message.tool_calls:
            parked = _process_tool_calls(message, turn_tools, goal_tracker)
            acted = True
            if parked:
                speak("That action is waiting for your confirmation. Say yes to continue or no to cancel.")
                _trim()
                clean_ephemeral()
                _flush_analytics()
                return True, acted
            continue
        acted, nudged, should_return = _handle_text_outcome(message, acted, nudged, turn_tools, user_text)
        if should_return:
            clean_ephemeral()
            _flush_analytics()
            return True, acted
    # Ran out of steps without a reply — own it instead of going quiet.
    reply = "That turned into more steps than I expected, so I've stopped. What were you after?"
    speak(reply)
    _persist_turn(user_text, reply, turn_tools)
    for name, result in turn_tools:
        record_tuning_result(user_text, name, success=not result.startswith("Error"))
    _trim()
    clean_ephemeral()
    _flush_analytics()
    return True, acted


def respond(text, already_done=()):
    """Handle one spoken turn: call tools until the model is done, then say the reply.

    Agentic Loop (Gather -> Act -> Verify) like Claude Code:
      Gather = _repair + hints + already_done context
      Act    = loop calling tools via _ask/_run_calls
      Verify = _no_calls/_has_completed_edit checks

    already_done names parts of the sentence the instant path has carried out, so a compound
    command handed over halfway does not get its first half run a second time.
    """
    _refresh_prompt()
    user_text = text
    if is_correction(text):
        record_correction(text)
    extra = _build_extra(user_text)
    if already_done:
        text = (f"{text}\n\n(Already carried out, do not repeat: {'; '.join(already_done)}. "
                f"Continue with the rest of the request.)")
    _repair()
    checkpoint = len(history)
    if extra:
        history.append({"role": "system", "content": "\n\n".join(extra)})
        _ephemeral_at = checkpoint
    else:
        _ephemeral_at = None
    history.append({"role": "user", "content": text})

    def _clean_ephemeral():
        nonlocal _ephemeral_at
        if _ephemeral_at is not None and 0 <= _ephemeral_at < len(history) and history[_ephemeral_at].get("role") == "system":
            if history[_ephemeral_at].get("content") == "\n\n".join(extra):
                del history[_ephemeral_at]
        _ephemeral_at = None

    _agent_loop(checkpoint, user_text, bool(already_done), [], _clean_ephemeral)


def reset():
    """Forget the conversation, keeping the personality."""
    del history[1:]
