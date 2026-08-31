"""The LLM client, shared by the agent.

Conversation and command routing both live in core/agent.py now — this module just owns the
client and the one-shot "write it to a file" helper.

Prompt caching: providers cache longest stable prefix. System prompt kept stable
and for Anthropic marked with cache_control. Others (OpenAI/Groq) are implicit.
"""
import os
import re
from pathlib import Path

from openai import OpenAI

import config as _config
from config import CHAT_CHAIN, LLM_TIMEOUT, apikey, base_url, chat_model
from windows.speech import speak

# where one-shot "using artificial intelligence" answers are saved
AI_OUTPUT_DIR = os.environ.get("WILCO_AI_OUTPUT_DIR", "Openai")

# no SDK retries: a 429 with a 30-second retry-after must not stall the conversation — the
# chain below moves the request to the next provider instead
_PRIMARY_CLIENT = OpenAI(api_key=apikey, base_url=base_url, timeout=LLM_TIMEOUT, max_retries=0)


class _ChainCompletions:
    """Tries each configured chat provider in order; the first one that answers wins."""

    def __init__(self, chain):
        self._chain = []
        for index, entry in enumerate(chain):
            client = (_PRIMARY_CLIENT if index == 0 else
                      OpenAI(api_key=entry["api_key"], base_url=entry["base_url"],
                             timeout=LLM_TIMEOUT, max_retries=0))
            self._chain.append((entry, client))

    def create(self, **kwargs):
        # callers pass the primary platform's model; each fallback substitutes its own
        # Prompt caching: Anthropic wire format needs cache_control on system prefix
        if "messages" in kwargs and _config.PROMPT_CACHE:
            kwargs["messages"] = _cached_messages(kwargs["messages"])
        requested = kwargs.get("model")
        errors = []
        for index, (entry, client) in enumerate(self._chain):
            if not requested or requested == chat_model:
                kwargs["model"] = entry["model"]
            try:
                resp = client.chat.completions.create(**kwargs)
                # Empty content with no tool_calls is treated as failure (e.g. max_tokens too low)
                msg = resp.choices[0].message if resp.choices else None
                if msg and not (msg.content or msg.tool_calls):
                    raise RuntimeError("empty generation — no content or tool_calls")
                return resp
            except Exception as error:
                err_text = str(error)
                # Detect empty generation to retry without max_tokens limit
                if "empty generation" in err_text and "max_tokens" in kwargs:
                    kwargs.pop("max_tokens", None)
                    # retry same provider without the low limit before falling back
                    try:
                        resp = client.chat.completions.create(**kwargs)
                        msg = resp.choices[0].message if resp.choices else None
                        if msg and (msg.content or msg.tool_calls):
                            return resp
                    except Exception:
                        pass
                summary = err_text.strip().splitlines()[0][:160] if err_text.strip() else type(error).__name__
                errors.append(f"{entry['platform']}: {summary}")
                print(f"CHAT: {entry['platform']} failed ({summary}).")
                following = self._chain[index + 1:]
                if following:
                    print(f"CHAT: falling back to {following[0][0]['platform']}.")
        raise RuntimeError("every chat provider failed — " + " | ".join(errors))


class _ChainChat:
    def __init__(self, chain):
        self.completions = _ChainCompletions(chain)


class _ChainLLM:
    """Drop-in for the OpenAI client: same llm.chat.completions.create shape, with failover."""

    def __init__(self, chain):
        self.chat = _ChainChat(chain)


llm = _ChainLLM(CHAT_CHAIN)

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def _cached_messages(messages):
    """explicit cache: mark stable system prefix as cacheable.

    For OpenAI/Groq implicit caching we keep prefix stable — no wire change.
    """
    if not _config.PROMPT_CACHE or _config.platform != "anthropic":
        return messages
    out = []
    for i, m in enumerate(messages):
        if i == 0 and m.get("role") == "system" and isinstance(m.get("content"), str):
            out.append({
                "role": "system",
                "content": [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}],
            })
        else:
            out.append(m)
    return out


def complete(messages):
    msgs = _cached_messages(messages)
    return llm.chat.completions.create(
        model=chat_model, messages=msgs
    ).choices[0].message.content


def ai(prompt):
    """Answer a one-shot prompt and save it to disk instead of speaking it."""
    try:
        answer = complete([{"role": "user", "content": prompt}])
    except Exception as e:
        print("Error:", e)
        speak("Failed to process the AI request.")
        return

    os.makedirs(AI_OUTPUT_DIR, exist_ok=True)
    # name the file after the request, dropping the "...artificial intelligence" prefix
    topic = prompt.split("intelligence", 1)[-1].strip()
    name = re.sub(r'[<>:"/\\|?*\s]+', "_", topic)[:50] or "prompt"
    with open(os.path.join(AI_OUTPUT_DIR, f"{name}.txt"), "w", encoding="utf-8") as f:
        f.write(f"Response for prompt: {prompt}\n{'*' * 25}\n\n{answer}")
    speak(f"The response has been saved to {AI_OUTPUT_DIR}.")
