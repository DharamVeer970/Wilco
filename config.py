"""Every setting Wilco has, in one file, all of it overridable from .env.

Nothing else in the codebase reads a tunable out of the environment or hardcodes one. Modules
import the name from here, so .env is the only file to edit to change how Wilco behaves, and
each default sits beside the name it belongs to instead of being buried in whichever module
happened to need it.

Two things deliberately stay out. Protocol constants — virtual key codes, shell flags, API
endpoints — are not preferences; changing them breaks the code that depends on them. And the
guard rails on speech speed are the limits the voice service itself accepts, not a taste.

There is no second settings file. Voice and speed can be changed by voice mid-conversation,
but that lasts the session only — a file that quietly outranked .env meant editing .env and
seeing nothing happen, which is worse than not remembering.
"""
import os

from dotenv import load_dotenv

load_dotenv(override=True)  # .env wins over stale OS env vars


def _text(name, default):
    return os.environ.get(name, "").strip() or default


def _number(name, default, cast=float):
    try:
        return cast(os.environ[name].strip())
    except (KeyError, ValueError, AttributeError):
        return default


def _flag(name, default):
    value = os.environ.get(name, "").strip().lower()
    return value in ("1", "true", "yes", "on") if value else default


def roots():
    """WILCO_ROOT, ';'-separated. Read live rather than frozen, so a change takes effect."""
    return _text("WILCO_ROOT", "")


# ----------------------------------------------------------------- which brain
PLATFORMS = {
    "openai": (None, "OPENAI_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY"),
    "cohere": ("https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
    "huggingface": ("https://router.huggingface.co/v1", "HUGGINGFACE_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}
platform = _text("WILCO_PLATFORM", "cohere")
chat_model = _text("WILCO_CHAT_MODEL", "command-a-03-2025")
stt_model = _text("WILCO_STT_MODEL", "openai/whisper-large-v3")

if platform not in PLATFORMS:
    raise SystemExit(f"WILCO_PLATFORM={platform!r} is not one of: {', '.join(PLATFORMS)}")

base_url, key_var = PLATFORMS[platform]
apikey = os.environ[key_var] if key_var else "ollama"
hf_token = os.environ["HUGGINGFACE_API_KEY"]

MAX_STEPS = _number("WILCO_MAX_STEPS", 6, int)
MAX_MESSAGES = _number("WILCO_MAX_MESSAGES", 40, int)
EMPTY_TRIES = _number("WILCO_EMPTY_TRIES", 3, int)
LLM_TIMEOUT = _number("WILCO_LLM_TIMEOUT", 30)

# ----------------------------------------------------------------- listening
PAUSE_SECONDS = _number("WILCO_PAUSE", 2.5)
MIN_PHRASE_SECONDS = _number("WILCO_MIN_PHRASE", 0.4)
MAX_PHRASE_SECONDS = _number("WILCO_MAX_PHRASE", 45)
LISTEN_TIMEOUT = _number("WILCO_LISTEN_TIMEOUT", 8)

# ----------------------------------------------------------------- speaking
VOICE = _text("WILCO_VOICE", "ava")
SPEED = _number("WILCO_SPEED", 25, int)
SPEED_STEP = _number("WILCO_SPEED_STEP", 15, int)
SPEECH_FIRST_GROUP = _number("WILCO_SPEECH_FIRST_GROUP", 90, int)
SPEECH_LATER_GROUP = _number("WILCO_SPEECH_LATER_GROUP", 400, int)
SPEECH_LEAST_GROUP = _number("WILCO_SPEECH_LEAST_GROUP", 40, int)
SPEECH_CACHEABLE = _number("WILCO_SPEECH_CACHE", 120, int)

# ----------------------------------------------------------------- how it decides
FUZZ_MIN = _number("WILCO_FUZZ_MIN", 70, int)
FAST_WORDS = _number("WILCO_FAST_WORDS", 9, int)
LIST_LIMIT = _number("WILCO_LIST_LIMIT", 40, int)
MAX_CONTROLS = _number("WILCO_MAX_CONTROLS", 300, int)
ASK_WHAT_NEXT = _flag("WILCO_ASK_WHAT_NEXT", False)

# ----------------------------------------------------------------- running things
SHELL_TIMEOUT = _number("WILCO_SHELL_TIMEOUT", 25, int)
MAX_OUTPUT = _number("WILCO_MAX_OUTPUT", 3000, int)
TEXT_LIMIT = _number("WILCO_TEXT_LIMIT", 6000, int)
BROWSER_WAIT = _number("WILCO_BROWSER_WAIT", 12.0)
BROWSER_GRACE = _number("WILCO_BROWSER_GRACE", 2.5)

# ----------------------------------------------------------------- files and mail
SMTP = _text("WILCO_SMTP", "smtp.gmail.com:465")
EMAIL = _text("WILCO_EMAIL", "")
EMAIL_PASSWORD = os.environ.get("WILCO_EMAIL_PASSWORD", "")
