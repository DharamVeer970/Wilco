"""The tool-calling loop — Wilco's actual decision making.

The old path classified one utterance into one action from a fixed enum, then handed back.
That is why things got "understood" but nothing followed: no second step, no reading of the
result, no conversation afterwards. Here the model calls tools, reads what they returned,
and either calls more or talks. Acting and chatting are the same turn, which is what makes
it hold a thread.
"""
import json
import re
import time

import mcp_tool
from config import (EMPTY_TRIES, MAX_MESSAGES, MAX_STEPS, TOOL_LIMIT, MEMORY_ENABLED,
                    MEMORY_TURNS, chat_model)
from core import roman
from core.brain import PROMPTS, llm
from core.analytics import record_tool_call
from core.memory import add_conversation_turn, get_recent_conversations
from core.learning import (record_correction, correction_prompt_snippet,
                           is_correction, FEEDBACK_ENABLED)
from core.retry import retry_call
from core import ux as _ux
from core import batch as _batch
from windows import voice
from windows.speech import speak

SYSTEM_PROMPT = (PROMPTS / "agent.txt").read_text(encoding="utf-8").strip()

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

# Everything below is spoken aloud, so anything that reads like machinery has to go. The model
# sometimes writes its tool calls out as ordinary text, or narrates what it is about to do;
# read out loud that is noise, and the user asked for the answer, not the working.
_FENCE = re.compile(r"```.*?```", re.S)
_BRACKETED = re.compile(r"\[[^\[\]]{0,300}\]")          # [Checking system settings...]
_MARKDOWN = re.compile(r"\*{1,3}|#{1,6}\s*|`+")
_MACHINERY = ("tool_call_id", "tool_name", "tool_calls", '"parameters"', '"arguments"')
_META_LINE = re.compile(r"^\s*(?:note|disclaimer|reasoning|thought|action)\s*:", re.I)
_PUNCT_ONLY = re.compile(r"^[\s\[\]{}(),:\"']*$")
# The user asked for the answer, not for Wilco to read a URL aloud: drop every link, along
# with any bracket that only wrapped it, so a "(https://...)" becomes nothing instead of
# "h t t p colon slash slash ...".
_URL = re.compile(r"https?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.I)
_EMPTY_PAREN = re.compile(r"\(\s*\)")
_WS_SQUASH = re.compile(r"\s{2,}")
# Tool results are stored trimmed. The model needs the gist of what came back, not every
# character — a wide-open search or directory listing can be 3,000 chars, and every one of
# those gets re-sent on each later step of the turn. 2,000 keeps answers complete and the
# re-sent payload small.
_TOOL_RESULT_MAX = 2000


def _speakable(text):
    """Strip tool-call JSON, stage directions, markdown and links out of what gets spoken."""
    if not text:
        return ""
    kept = []
    for line in _MARKDOWN.sub("", _FENCE.sub("", text)).splitlines():
        if any(word in line for word in _MACHINERY) or _META_LINE.match(line):
            continue
        line = _BRACKETED.sub("", line)
        line = _URL.sub("", line)
        line = _EMPTY_PAREN.sub("", line)
        line = _WS_SQUASH.sub(" ", line).strip()
        if _PUNCT_ONLY.match(line):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


# The voice can be handed Devanagari and simply say nothing, which looks like a crash rather
# than a language problem. Converting it is a lookup table, so core/roman.py does it here
# instead of spending an API call — a third of the month's quota, for a Hindi speaker.
def _romanise(text):
    """Keep Hindi script for Hindi neural voices; transliterate it for other voices."""
    if not roman.has_devanagari(text):
        return text
    if voice.current()[1].startswith("hi-IN-"):
        return text
    return roman.romanise(text)


# The model sometimes TYPES a tool call instead of making one, and sometimes narrates an
# action it never took. Both leave the user told it happened when it didn't, which is the
# worst thing this can do — so both are caught rather than trusted.
_WRITTEN = re.compile(r"[\[{].*[\]}]", re.S)
_CLAIMED = re.compile(
    r"\b(?:i(?:'ve| have)?\s+(?:just\s+|now\s+)?(?:opened|set|changed|closed|sent|created|"
    r"deleted|increased|decreased|reduced|switched|started|launched|turned|played|typed|"
    r"saved|updated|added|removed|adjusted)|"
    r"(?:reminder|alarm|timer|volume|brightness|speed)\s+(?:is\s+|has\s+been\s+)?set|"
    r"(?:it'?s|that'?s|all)\s+done)\b", re.I)
# Diagnostics can accompany fabricated claims that defaults or code changed. Those require
# proof of a completed edit in this turn, not merely proof that some tool happened to run.
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
    """What the tool router ranks against — the latest ask plus whatever the last tools
    returned, so a follow-up like 'the first one' still lines up with the same tools."""
    recent = []
    for message in history[-8:]:
        content = message.get("content")
        if isinstance(content, str) and content:
            recent.append(content)
    return " ".join(recent)


def _ask():
    """One completion, retried when the provider generates nothing at all.

    Cohere intermittently answers a perfectly valid request with 422
    NO_TOOL_CALL_OR_RESPONSE_GENERATED — no tool call, no text, nothing. It is a flake on
    their side, not a fault in the request: the identical message shape succeeded twelve times
    out of twelve when tested. Nothing here can prevent it, so it is retried with a little
    backoff rather than costing the user their turn. Any other error is real and raised at once.
    """
    # The full 77-tool payload was ~8,000 tokens on every call — the biggest single cost.
    # dispatch_tools sends a routed, compact list instead, so each step is faster to chew.
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
    # Roll the whole turn back. Deleting just the last message used to strip a tool
    # RESULT when the failure landed mid-loop, stranding the tool call that produced
    # it — and a stranded tool call breaks every request that follows it, for good.
    del history[checkpoint:]
    # If tools already ran, the work really happened — saying "I couldn't reach my
    # brain" would be a lie about a machine the user is looking at.
    speak("I did that, but couldn't put the reply together. Ask again for the details?"
          if acted else "I couldn't reach my brain just then. Say that again?")


def _run_calls(calls):
    """Execute the assistant's tool calls, recording analytics for each."""
    results = []
    parked = False
    for index, call in enumerate(calls):
        start_time = time.time()
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
        print(f"  -> {call.function.name}({arguments})")

        try:
            result = retry_call(mcp_tool.call, call.function.name, arguments, max_retries=2)
            duration = time.time() - start_time
            record_tool_call(call.function.name, True, duration)
            print(f"     {result[:160]}")
        except Exception as e:
            duration = time.time() - start_time
            record_tool_call(call.function.name, False, duration, str(e))
            result = f"Error calling {call.function.name}: {type(e).__name__}: {e}"
            print(f"     ERROR: {result[:160]}")

        if len(result) > _TOOL_RESULT_MAX:
            result = result[:_TOOL_RESULT_MAX] + "\n…(rest trimmed to keep responses fast)"
        history.append({"role": "tool", "tool_call_id": call.id, "content": result})
        results.append((call.function.name, result))
        if result.startswith("NOT DONE"):
            # A model must not confirm an action it just parked. Still reply to every tool
            # call in this batch so the next user turn has valid API conversation history.
            parked = True
            for skipped in calls[index + 1:]:
                history.append({
                    "role": "tool", "tool_call_id": skipped.id,
                    "content": "Skipped: a previous action is awaiting the user's explicit confirmation.",
                })
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
    return any(name in {"edit_file", "write_file"} and not result.startswith("NOT DONE")
               for name, result in turn_tools)


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
    speak(spoken or "Done.")
    return "spoke"


def respond(text, already_done=()):
    """Handle one spoken turn: call tools until the model is done, then say the reply.

    already_done names parts of the sentence the instant path has carried out, so a compound
    command handed over halfway does not get its first half run a second time.
    """
    _refresh_prompt()
    user_text = text
    # Learning: remember corrections like "always X" / "not that, the other one" so later
    # turns behave differently (no-op unless WILCO_FEEDBACK_ENABLED=1).
    if is_correction(text):
        record_correction(text)
    text = (f"{text}\n\n{correction_prompt_snippet()}".strip()
            if correction_prompt_snippet() else text)

    if already_done:
        text = (f"{text}\n\n(Already carried out, do not repeat: {'; '.join(already_done)}. "
                f"Continue with the rest of the request.)")
    _repair()
    checkpoint = len(history)  # everything from here is this turn, and unwinds together
    history.append({"role": "user", "content": text})

    # Sub-goal tracking: surface where a multi-step turn is at, for logging/prompting.
    goal_tracker = _batch.SubGoalTracker("turn")
    acted = bool(already_done)  # the instant path did it, so a claim about it is not a lie
    nudged = False
    turn_tools = []
    for _ in range(MAX_STEPS):
        try:
            message = _ask()
        except Exception as e:
            _turn_failed(checkpoint, acted, e)
            return

        history.append(_as_dict(message))

        if message.tool_calls:
            for _c in message.tool_calls:
                goal_tracker.add_goal(_c.function.name)
            results, parked = _run_calls(message.tool_calls)
            turn_tools.extend(results)
            for _i in range(len(results)):
                goal_tracker.complete(_i)
            acted = True
            if parked:
                speak("That action is waiting for your confirmation. Say yes to continue or no to cancel.")
                _trim()
                return
            continue

        outcome = _no_calls(message, acted, nudged, turn_tools)
        if outcome == "spoke":
            _persist_turn(user_text, _romanise(_speakable(message.content)) or "Done.", turn_tools)
            _trim()
            return
        acted = acted or outcome == "ran"
        nudged = nudged or outcome == "nudged"

    # Only speak the "too many steps" message if we didn't already speak via _no_calls
    # _no_calls returns "spoke" when there are no tool calls and we should speak the result
    # If we get here, the loop completed without hitting "spoke", meaning we need the fallback
    if outcome != "spoke":
        reply = "That turned into more steps than I expected, so I've stopped. What were you after?"
        speak(reply)
        _persist_turn(user_text, reply, turn_tools)
    _trim()


def reset():
    """Forget the conversation, keeping the personality."""
    del history[1:]
