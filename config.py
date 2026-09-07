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


# -------------------------------- which brain ---------------------------------
PLATFORMS = {
    "openai": (None, "OPENAI_API_KEY"),
    "anthropic": ("https://api.anthropic.com/v1/", "ANTHROPIC_API_KEY"),
    "cohere": ("https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
    "huggingface": ("https://router.huggingface.co/v1", "HUGGINGFACE_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "ollama": ("http://localhost:11434/v1", None),
}
platform = _text("WILCO_PLATFORM", "cohere")

# The platform determines which API key and base URL to use automatically
chat_model = _text("WILCO_CHAT_MODEL", "command-a-03-2025")

# STT defaults per provider (.env overrides any field); transport: openai = multipart, openrouter = JSON/base64, huggingface = its API.
STT_PROVIDER_DEFAULTS = {
    "nvidia": {
        "key_env": "NVIDIA_API_KEY", "base_url": "https://integrate.api.nvidia.com/v1",
        "transport": "openai", "model": "nisb",
    },
    "groq": {
        "key_env": "GROQ_API_KEY", "base_url": "https://api.groq.com/openai/v1",
        "transport": "openai", "model": "whisper-large-v3-turbo",
    },
    "openai": {
        "key_env": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1",
        "transport": "openai", "model": "whisper-1",
    },
    "openrouter": {
        "key_env": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1",
        "transport": "openrouter", "model": "openai/whisper-large-v3",
    },
    "huggingface": {
        "key_env": "HUGGINGFACE_API_KEY", "base_url": "",
        "transport": "huggingface", "model": "openai/whisper-large-v3",
    },
}
stt_provider = _text("WILCO_STT_PROVIDER", "groq").lower()
_stt_defaults = STT_PROVIDER_DEFAULTS.get(stt_provider, {})
stt_transport = _text("WILCO_STT_TRANSPORT", _stt_defaults.get("transport", "openai")).lower()
stt_base_url = _text("WILCO_STT_BASE_URL", _stt_defaults.get("base_url", "")).rstrip("/")
stt_key_env = _text("WILCO_STT_KEY_ENV", _stt_defaults.get("key_env", ""))
stt_model = _text("WILCO_STT_MODEL", _stt_defaults.get("model", ""))

# Leave blank for automatic detection.
stt_language = _text("WILCO_STT_LANGUAGE", "").lower()

if platform not in PLATFORMS:
    raise SystemExit(f"WILCO_PLATFORM={platform!r} is not one of: {', '.join(PLATFORMS)}")

base_url, key_var = PLATFORMS[platform]
apikey = os.environ[key_var] if key_var else "ollama"

# On provider failure/429, retry the request on these platforms in order (own key/model each; keyless entries skipped).
CHAT_MODEL_DEFAULTS = {
    "openai": "gpt-4o",
    "cohere": "command-a-03-2025",
    "groq": "openai/gpt-oss-120b",
    "openrouter": _text("WILCO_OPENROUTER_MODEL", "nvidia/nemotron-3.5-lightning:free"),
    "nvidia": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "huggingface": "meta-llama/Llama-3.3-70B-Instruct",
}
CHAT_FALLBACKS = [name.strip().lower() for name in
                  _text("WILCO_CHAT_FALLBACKS", "openrouter,cohere").split(",") if name.strip()]


def _chat_chain():
    """The ordered chat provider chain: the chosen platform first, then the fallbacks."""
    chain, seen = [], set()
    for name in [platform] + CHAT_FALLBACKS:
        if name in seen or name not in PLATFORMS:
            continue
        seen.add(name)
        entry_base, entry_key_var = PLATFORMS[name]
        entry_key = os.environ.get(entry_key_var, "") if entry_key_var else "ollama"
        if entry_key_var and not entry_key:
            continue  # no key for this fallback, so it could never answer
        chain.append({"platform": name, "base_url": entry_base, "api_key": entry_key,
                      "model": chat_model if name == platform
                      else CHAT_MODEL_DEFAULTS.get(name, chat_model)})
    return chain


CHAT_CHAIN = _chat_chain()

if stt_transport not in ("openai", "openrouter", "huggingface"):
    raise SystemExit("WILCO_STT_TRANSPORT must be openai, openrouter, or huggingface.")

if not stt_model or (stt_transport != "huggingface" and not stt_base_url):
    raise SystemExit("Set WILCO_STT_MODEL and WILCO_STT_BASE_URL for a custom STT provider.")
stt_api_key = _text("WILCO_STT_API_KEY", "") or os.environ.get(stt_key_env, "")

# On primary STT failure, walk this comma-separated fallback list (each uses its own STT_PROVIDER_DEFAULTS entry).
STT_FALLBACKS = [name.strip().lower() for name in
                 _text("WILCO_STT_FALLBACKS", "openrouter,huggingface").split(",") if name.strip()]


def _stt_chain():
    """The ordered provider chain: the chosen provider (with its .env overrides) first."""
    chain = [{"provider": stt_provider, "key_env": stt_key_env, "base_url": stt_base_url,
              "transport": stt_transport, "model": stt_model, "api_key": stt_api_key}]
    for name in STT_FALLBACKS:
        if name == stt_provider or name not in STT_PROVIDER_DEFAULTS:
            continue
        defaults = STT_PROVIDER_DEFAULTS[name]
        chain.append({
            "provider": name, "key_env": defaults["key_env"],
            "base_url": defaults["base_url"].rstrip("/"),
            "transport": defaults["transport"], "model": defaults["model"],
            "api_key": os.environ.get(defaults["key_env"], ""),
        })
    return chain


STT_CHAIN = _stt_chain()

if not any(entry["api_key"] for entry in STT_CHAIN):
    raise SystemExit(
        "No speech-to-text API key is configured. Set WILCO_STT_API_KEY, the key named by "
        f"WILCO_STT_KEY_ENV ({stt_key_env}), or a fallback key such as GROQ_API_KEY, "
        "OPENROUTER_API_KEY, or HUGGINGFACE_API_KEY."
    )

MAX_STEPS = _number("WILCO_MAX_STEPS", 6, int)
MAX_MESSAGES = _number("WILCO_MAX_MESSAGES", 24, int)
EMPTY_TRIES = _number("WILCO_EMPTY_TRIES", 3, int)
LLM_TIMEOUT = _number("WILCO_LLM_TIMEOUT", 30)
# how many compact tool schemas the model sees each turn (0 = all of them, no routing)
TOOL_LIMIT = _number("WILCO_TOOL_LIMIT", 24, int)
# Prompt caching: stable system prefix cacheable (Anthropic explicit, others implicit); WILCO_PROMPT_CACHE=0 disables.
PROMPT_CACHE = _flag("WILCO_PROMPT_CACHE", True)

# Auto-learn: remembers recent turns locally (~/.wilco/memory.json, never sent out); WILCO_MEMORY_ENABLED=0 disables.
MEMORY_ENABLED = _flag("WILCO_MEMORY_ENABLED", True)
MEMORY_TURNS = max(0, _number("WILCO_MEMORY_TURNS", 6, int))

# -------------------------------- listening ---------------------------------
PAUSE_SECONDS = _number("WILCO_PAUSE", 2.5)
MIN_PHRASE_SECONDS = _number("WILCO_MIN_PHRASE", 0.4)
MAX_PHRASE_SECONDS = _number("WILCO_MAX_PHRASE", 45)
LISTEN_TIMEOUT = _number("WILCO_LISTEN_TIMEOUT", 8)

# -------------------------------- speaking ---------------------------------
VOICE = _text("WILCO_VOICE", "ava")
SPEED = _number("WILCO_SPEED", 25, int)
SPEED_STEP = _number("WILCO_SPEED_STEP", 15, int)
SPEECH_FIRST_GROUP = _number("WILCO_SPEECH_FIRST_GROUP", 90, int)
SPEECH_LATER_GROUP = _number("WILCO_SPEECH_LATER_GROUP", 400, int)
SPEECH_LEAST_GROUP = _number("WILCO_SPEECH_LEAST_GROUP", 40, int)
SPEECH_CACHEABLE = _number("WILCO_SPEECH_CACHE", 120, int)
# Prevent an identical reply from being played twice when two code paths finish together.
SPEECH_DEDUP_SECONDS = _number("WILCO_SPEECH_DEDUP_SECONDS", 2.0)

# ------------------------- how it decides ----------------------------------------
FUZZ_MIN = _number("WILCO_FUZZ_MIN", 70, int)
FAST_WORDS = _number("WILCO_FAST_WORDS", 9, int)
LIST_LIMIT = _number("WILCO_LIST_LIMIT", 40, int)
MAX_CONTROLS = _number("WILCO_MAX_CONTROLS", 300, int)
ASK_WHAT_NEXT = _flag("WILCO_ASK_WHAT_NEXT", False)

# All-access mode: every command executes immediately, no "are you sure?"; WILCO_ALWAYS_ACT=0 restores the gate.
ALWAYS_ACT = _flag("WILCO_ALWAYS_ACT", True)

# ---------------------------------------- running things ----------------------------------------
SHELL_TIMEOUT = _number("WILCO_SHELL_TIMEOUT", 25, int)
MAX_OUTPUT = _number("WILCO_MAX_OUTPUT", 3000, int)
TEXT_LIMIT = _number("WILCO_TEXT_LIMIT", 6000, int)
BROWSER_WAIT = _number("WILCO_BROWSER_WAIT", 12.0)
BROWSER_GRACE = _number("WILCO_BROWSER_GRACE", 2.5)

# ---------------------------------------- external MCP servers ----------------------------------------
# MCP servers provide additional tools. Each entry needs a name and serverUrl.
# Format: WILCO_MCP_SERVERS=name1,name2 (comma-separated)
# URLs are defined in MCP_SERVER_URLS below.
MCP_SERVER_URLS = {
    "docs-langchain": "https://docs.langchain.com/mcp",
    "reference-langchain": "https://reference.langchain.com/mcp",
}
mcp_server_names = [_s.strip() for _s in _text("WILCO_MCP_SERVERS", "").split(",") if _s.strip()]
MCP_SERVERS = [(name, MCP_SERVER_URLS[name]) for name in mcp_server_names if name in MCP_SERVER_URLS]

# ---------------------------------------- files and mail ----------------------------------------
SMTP = _text("WILCO_SMTP", "smtp.gmail.com:465")
EMAIL = _text("WILCO_EMAIL", "")
EMAIL_PASSWORD = os.environ.get("WILCO_EMAIL_PASSWORD", "")
