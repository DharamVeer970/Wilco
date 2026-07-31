<h1 align="center">Wilco</h1>

<p align="center">
  <em>A voice agent for Windows. You talk, it does the thing.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/tools-39-6E56CF" alt="39 tools">
  <img src="https://img.shields.io/badge/LLM-provider--agnostic-10B981" alt="Provider agnostic">
</p>

---

Wilco listens on the mic, transcribes with Whisper, and either fires a local command instantly
or hands the utterance to an agent that can call **39 tools** — apps, files, folders, volume,
brightness, media, Windows settings, the controls inside any window, web search, YouTube, and
PowerShell. Replies are spoken back through Windows SAPI.

It is an agent, not a command parser: it reads what each tool returned, chains further calls
if the job needs them, and keeps talking afterwards.

```
"volume up"              -> regex hit, instant, no LLM
"open notepad"           -> regex hit, instant
"could you turn it up"   -> no regex -> agent -> change_volume
"what's the weather"     -> no regex -> agent -> web_search -> spoken answer
"how was your day"       -> no regex -> agent -> just talks
```

The regex path in [core/commands.py](core/commands.py) stays because it costs nothing and
answers instantly. Everything it misses reaches the agent, which has the tools and can also
hold a conversation — so an unmatched phrasing is a conversation, never a dead end.

## Contents

- [Quick start](#quick-start)
- [What it can do](#what-it-can-do)
- [Layout](#layout)
- [Adding a tool](#adding-a-tool)
- [Safety: what needs confirming](#safety-what-needs-confirming)
- [Switching provider](#switching-provider)
- [Configuration](#configuration)
- [Known limits](#known-limits)

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Create a `.env` next to `main.py`:

```ini
COHERE_API_KEY=...
HUGGINGFACE_API_KEY=...
```

`HUGGINGFACE_API_KEY` is always required — speech-to-text runs on HF Whisper whatever the chat
provider is. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens);
a read token is enough.

Web search needs no key. It reads DuckDuckGo's HTML endpoint, the same approach `online.py`
already uses for YouTube.

`PyAudio` is needed by `SpeechRecognition` for mic input; on Windows install a prebuilt wheel
if pip tries to compile it.

## What it can do

| Say | What happens |
|---|---|
| "open / launch `<app>`" | Opens any installed app, then focuses it |
| "type `<text>`" | Types into the focused window |
| "search for `<thing>`" | Web search, answer spoken back |
| "google `<thing>`" | Opens a Google results page |
| "play `<thing>` on youtube" | Searches and plays the top hit |
| "play the next one" | Steps through the last search |
| "open my downloads folder" | File Explorer at the real known-folder path |
| "set volume to 70" / "louder" / "mute" | Media keys |
| "brightness to 40" | WMI, laptop panels only |
| "open display settings and turn night light on" | Opens the page, then flips the actual switch |
| "search inside settings for bluetooth" | Types into the app's own search box |
| "close this tab" | Ctrl+W on the frontmost browser — the browser stays open |
| "close the tab in chrome" | Focuses Chrome first, then closes one tab |
| "close chrome" / "close the app" | Closes the whole app, and every window it owns |
| "pause" / "next" / "stop" | Real media keys — works with Spotify, VLC, browsers |
| "what's my ip" / "how much disk space" | Machine state, spoken |
| "shut down" / "restart" | Asks first, then does it |
| "reset chat" / "start over" | Clears the conversation and the context |
| "jarvis quit" | Exits |
| anything else | The agent — acts, answers, or just talks |

Ambiguity is never auto-resolved. "open python" lists the matches and asks; answer with a
number or a fuller name.

## Layout

```
Wilco/
├── main.py                 the listen loop, nothing else
├── config.py               .env, provider and model choice
├── core/
│   ├── commands.py         the instant regex path — device commands, no LLM round-trip
│   ├── agent.py            the tool-calling loop
│   ├── brain.py            the LLM client
│   ├── context.py          last search, app, folder, file — for follow-ups
│   └── online.py           YouTube search and playback
├── mcp_tool/               everything the agent can call
│   ├── __init__.py         the registry — schemas derived from signatures
│   ├── pc.py               Windows control
│   ├── ui.py               reading and operating controls inside a window
│   ├── web.py              web search, page reading, YouTube
│   ├── shell_tool.py       PowerShell, split into free and confirmed
│   └── gate.py             holds a dangerous action until you say yes
├── windows/                the machine half — apps, files, shell, speech, system
└── prompts/agent.txt       personality and tool guidance, edit without touching code
```

Imports run one way, so there are no cycles:

```
main.py -> core/commands.py -> core/agent.py -> mcp_tool/ -> windows/ -> config.py
```

`mcp_tool/` must never import `core/commands.py`, or that becomes a loop.

## Adding a tool

Write a function in any module listed in `MODULES` in [mcp_tool/\_\_init\_\_.py](mcp_tool/__init__.py).
That is the whole job — the name, signature and docstring become the schema the model sees, so
there is no JSON to keep in sync. Names starting with `_` stay private.

```python
def open_terminal(profile="powershell"):
    """Open Windows Terminal. profile: powershell, cmd or wsl."""
    os.startfile(f"wt.exe -p {profile}")
    return f"Opened Windows Terminal on the {profile} profile."
```

Write the docstring for the model — it is the only instruction it gets about when to reach for
the tool. Return a sentence saying what actually happened, including failures: the model reads
that string and decides what to do next, so "no file called that" gets a useful reply instead
of a false claim of success.

## Safety: what needs confirming

These do **not** run when the tool is called. They come back asking, and only run when you say
yes out loud:

- deleting a file (always to the recycle bin, never a hard delete)
- emptying the recycle bin
- shutdown, restart, sleep
- any PowerShell that writes, deletes, installs or reconfigures

Everything else just runs. Locking the screen, opening apps, volume, brightness, media,
searching and typing are all immediate.

PowerShell is split by [mcp_tool/shell_tool.py](mcp_tool/shell_tool.py): a command runs freely
only if it starts with something read-only (`Get-*`, `ipconfig`, `systeminfo`, `tasklist`,
`ping`, `dir`…), contains no changing verb anywhere, and has no `;`, `>`, `&` or backtick that
could smuggle a second command in. Anything else is held.

The split exists because the input is speech — Whisper mishears, and the model composes the
command from what it heard, so a misheard sentence must never be able to reconfigure the
machine on its own.

## Switching provider

Two lines in [config.py](config.py) plus the matching key in `.env`:

```python
platform = "cohere"
chat_model = "command-a-03-2025"
```

| `platform` | `.env` key | Example model |
|---|---|---|
| `cohere` | `COHERE_API_KEY` | `command-a-03-2025` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `huggingface` | `HUGGINGFACE_API_KEY` | `meta-llama/Llama-3.3-70B-Instruct` |
| `ollama` | *(none)* | `llama3.2` |

The provider must support tool calling, and support it well — the agent is only as good as
that. Cohere `command-a-03-2025` is the tested default and handles parallel tool calls, so
"open notepad and search for X" resolves in one round trip. Groq's `llama-3.3-70b-versatile`
was tried and returned a 400 on the same tool schema.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `HUGGINGFACE_API_KEY` | *required* | Whisper speech-to-text |
| `COHERE_API_KEY` | *required for the default provider* | Chat + tool calling |
| `JARVIS_PAUSE` | `2.5` | Seconds of silence before it decides you've finished |
| `JARVIS_ROOT` | *(every drive)* | `;`-separated folders to limit the file scan to |

`JARVIS_PAUSE` is how long you may go quiet mid-sentence. Every microphone and room differs,
so tune it: raise it if you're still being cut off, lower it if replies feel sluggish.

```ini
JARVIS_PAUSE=3.5
JARVIS_ROOT=C:\Users\me\Documents;D:\Projects
```

## Known limits

- No wake word — it acts on every utterance.
- `speak()` blocks, so it is deaf while talking.
- The first file or folder command scans the drives, which takes a few seconds once per run.
- The app list is read once per session, so restart to pick up a new install.
- Windows-only: SAPI for speech, `win32com` and `ctypes` throughout.
- Whisper runs over the network, so transcription costs a round trip.
- `set_volume` taps volume-down 50 times then back up, since each key press moves 2%.
