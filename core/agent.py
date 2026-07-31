"""The tool-calling loop — Wilco's actual decision making.

The old path classified one utterance into one action from a fixed enum, then handed back.
That is why things got "understood" but nothing followed: no second step, no reading of the
result, no conversation afterwards. Here the model calls tools, reads what they returned,
and either calls more or talks. Acting and chatting are the same turn, which is what makes
it hold a thread.
"""
import json

import mcp_tool
from config import chat_model
from core.brain import PROMPTS, llm
from windows.speech import speak

SYSTEM_PROMPT = (PROMPTS / "agent.txt").read_text(encoding="utf-8").strip()

MAX_STEPS = 6      # tool rounds in one turn, before we stop and admit it
MAX_MESSAGES = 40  # rolling window, trimmed on whole turns

history = [{"role": "system", "content": SYSTEM_PROMPT}]


def _as_dict(message):
    """Only the fields the API accepts back — providers reject their own extra keys."""
    data = message.model_dump(exclude_none=True)
    return {k: v for k, v in data.items() if k in ("role", "content", "tool_calls")}


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
    history.append({"role": "user", "content": text})

    for _ in range(MAX_STEPS):
        try:
            message = llm.chat.completions.create(
                model=chat_model, messages=history, tools=mcp_tool.TOOLS
            ).choices[0].message
        except Exception as e:
            print("Agent error:", e)
            del history[-1:]
            speak("I couldn't reach my brain just then. Say that again?")
            return

        history.append(_as_dict(message))

        if not message.tool_calls:
            speak(message.content or "Done.")
            _trim()
            return

        # a preamble alongside tool calls keeps the silence filled while tools run
        if message.content and message.content.strip():
            speak(message.content.strip())

        for call in message.tool_calls:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            print(f"  -> {call.function.name}({arguments})")
            result = mcp_tool.call(call.function.name, arguments)
            print(f"     {result[:160]}")
            history.append({"role": "tool", "tool_call_id": call.id, "content": result})

    speak("That turned into more steps than I expected, so I've stopped. What were you after?")
    _trim()


def reset():
    """Forget the conversation, keeping the personality."""
    del history[1:]
