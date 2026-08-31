"""The LLM client, shared by the agent.

Conversation and command routing both live in core/agent.py now — this module just owns the
client and the one-shot "write it to a file" helper.
"""
import os
import re
from pathlib import Path

from openai import OpenAI

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
        requested = kwargs.get("model")
        errors = []
        for index, (entry, client) in enumerate(self._chain):
            if not requested or requested == chat_model:
                kwargs["model"] = entry["model"]
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as error:
                summary = str(error).strip().splitlines()[0][:160] if str(error).strip() else type(error).__name__
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


def complete(messages):
    return llm.chat.completions.create(
        model=chat_model, messages=messages
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
