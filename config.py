import os

from dotenv import load_dotenv

load_dotenv(override=True)  # .env wins over stale OS env vars

platform = "cohere"
chat_model = "command-a-03-2025"

stt_model = "openai/whisper-large-v3"

PLATFORMS = {
    "openai": (None, "OPENAI_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY"),
    "cohere": ("https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
    "huggingface": ("https://router.huggingface.co/v1", "HUGGINGFACE_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}

base_url, key_var = PLATFORMS[platform]
apikey = os.environ[key_var] if key_var else "ollama"
hf_token = os.environ["HUGGINGFACE_API_KEY"]
