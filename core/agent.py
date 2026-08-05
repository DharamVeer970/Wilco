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
from config import EMPTY_TRIES, MAX_MESSAGES, MAX_STEPS, chat_model
from core import roman
from core.brain import PROMPTS, llm
from windows.speech import speak

SYSTEM_PROMPT = (PROMPTS / "agent.txt").read_text(encoding="utf-8").strip()

history = [{"role": "system", "content": SYSTEM_PROMPT}]

# Everything below is spoken aloud, so anything that reads like machinery has to go. The model
# sometimes writes its tool calls out as ordinary text, or narrates what it is about to do;
# read out loud that is noise, and the user asked for the answer, not the working.
_FENCE = re.compile(r"```.*?```", re.S)
_BRACKETED = re.compile(r"\[[^\[\]]{0,300}\]")          # [Checking system settings...]
_MARKDOWN = re.compile(r"\*{1,3}|#{1,6}\s*|`+")
_MACHINERY = ("tool_call_id", "tool_name", "tool_calls", '"parameters"', '"arguments"')
_META_LINE = re.compile(r"^\s*(?:note|disclaimer|reasoning|thought|action)\s*:", re.I)
_PUNCT_ONLY = re.compile(r"^[\s\[\]{}(),:\"']*$")


def _speakable(text):
    """Strip tool-call JSON, stage directions and markdown out of what gets spoken."""
    if not text:
        return ""
    kept = []
    for line in _MARKDOWN.sub("", _FENCE.sub("", text)).splitlines():
        if any(word in line for word in _MACHINERY) or _META_LINE.match(line):
            continue
        line = _BRACKETED.sub("", line)
        if _PUNCT_ONLY.match(line):
            continue
        kept.append(line.strip())
    return "\n".join(kept).strip()


# The voice can be handed Devanagari and simply say nothing, which looks like a crash rather
# than a language problem. Converting it is a lookup table, so core/roman.py does it here
# instead of spending an API call — a third of the month's quota, for a Hindi speaker.
def _romanise(text):
    """Rewrite non-Latin script into Latin letters so the voice can actually say it."""
    if not roman.has_devanagari(text):
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


def _ask():
    """One completion, retried when the provider generates nothing at all.

    Cohere intermittently answers a perfectly valid request with 422
    NO_TOOL_CALL_OR_RESPONSE_GENERATED — no tool call, no text, nothing. It is a flake on
    their side, not a fault in the request: the identical message shape succeeded twelve times
    out of twelve when tested. Nothing here can prevent it, so it is retried with a little
    backoff rather than costing the user their turn. Any other error is real and raised at once.
    """
    for attempt in range(1, EMPTY_TRIES + 1):
        try:
            return llm.chat.completions.create(
                model=chat_model, messages=history, tools=mcp_tool.TOOLS
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


def respond(text, already_done=()):
    """Handle one spoken turn: call tools until the model is done, then say the reply.

    already_done names parts of the sentence the instant path has carried out, so a compound
    command handed over halfway does not get its first half run a second time.
    """
    if already_done:
        text = (f"{text}\n\n(Already carried out, do not repeat: {'; '.join(already_done)}. "
                f"Continue with the rest of the request.)")
    _repair()
    checkpoint = len(history)  # everything from here is this turn, and unwinds together
    history.append({"role": "user", "content": text})

    acted = bool(already_done)  # the instant path did it, so a claim about it is not a lie
    nudged = False
    for _ in range(MAX_STEPS):
        try:
            message = _ask()
        except Exception as e:
            print("Agent error:", e)
            # Roll the whole turn back. Deleting just the last message used to strip a tool
            # RESULT when the failure landed mid-loop, stranding the tool call that produced
            # it — and a stranded tool call breaks every request that follows it, for good.
            del history[checkpoint:]
            # If tools already ran, the work really happened — saying "I couldn't reach my
            # brain" would be a lie about a machine the user is looking at.
            speak("I did that, but couldn't put the reply together. Ask again for the details?"
                  if acted else "I couldn't reach my brain just then. Say that again?")
            return

        history.append(_as_dict(message))

        if not message.tool_calls:
            written = _written_calls(message.content)
            if written:
                acted = True
                results = [f"{name}: {mcp_tool.call(name, arguments)}"
                           for name, arguments in written]
                for line in results:
                    print(f"  -> {line[:160]}  [recovered from text]")
                history.append({"role": "user", "content":
                                "Those tool calls were written as text, so they have now been "
                                "run for you. Results — " + "; ".join(results) +
                                ". Tell the user what happened, in a sentence or two."})
                continue

            spoken = _romanise(_speakable(message.content))
            if not acted and not nudged and _CLAIMED.search(spoken):
                nudged = True
                print("  [claimed an action without calling anything — asking again]")
                history.append({"role": "user", "content":
                                "You described that as done, but you called no tool, so "
                                "nothing actually happened. Call the tool that does it now, "
                                "or say plainly that you can't."})
                continue

            speak(spoken or "Done.")
            _trim()
            return

        for call in message.tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            print(f"  -> {call.function.name}({arguments})")
            result = mcp_tool.call(call.function.name, arguments)
            print(f"     {result[:160]}")
            acted = True
            history.append({"role": "tool", "tool_call_id": call.id, "content": result})

    speak("That turned into more steps than I expected, so I've stopped. What were you after?")
    _trim()


def reset():
    """Forget the conversation, keeping the personality."""
    del history[1:]
