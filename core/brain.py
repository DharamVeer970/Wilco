"""The LLM client, shared by the agent.

Conversation and command routing both live in core/agent.py now — this module just owns the
client and the one-shot "write it to a file" helper.
"""
import os
import re
from pathlib import Path

from openai import OpenAI

from config import apikey, base_url, chat_model
from windows.speech import speak

# without these it waits forever on a stalled request, and the whole assistant hangs
llm = OpenAI(api_key=apikey, base_url=base_url, timeout=30, max_retries=1)

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

    os.makedirs("Openai", exist_ok=True)
    # name the file after the request, dropping the "...artificial intelligence" prefix
    topic = prompt.split("intelligence", 1)[-1].strip()
    name = re.sub(r'[<>:"/\\|?*\s]+', "_", topic)[:50] or "prompt"
    with open(f"Openai/{name}.txt", "w", encoding="utf-8") as f:
        f.write(f"Response for prompt: {prompt}\n{'*' * 25}\n\n{answer}")
    speak("The response has been saved.")
