<h1 align="center">Wilco</h1>

<p align="center">
  <em>A voice agent for Windows. You talk, it does the thing.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/tools-64-6E56CF" alt="64 tools">
  <img src="https://img.shields.io/badge/MCP-server-D97757" alt="MCP server">
  <img src="https://img.shields.io/badge/LLM-provider--agnostic-10B981" alt="Provider agnostic">
</p>

---

Wilco listens on the mic, transcribes with Whisper, and either fires a local command instantly
or hands the utterance to an agent that can call **64 tools** — apps, files, folders, volume,
brightness, media, Windows settings, the controls inside any window, web search, YouTube, and
PowerShell. Replies are spoken back in a neural voice — thirteen voice packs, switchable by
voice mid-conversation, at whatever pace you ask for.

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
- [Use it as an MCP server](#use-it-as-an-mcp-server)
- [Switching provider](#switching-provider)
- [Configuration](#configuration)
- [Known limits](#known-limits)

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

Copy [.env.example](.env.example) to `.env` and fill it in:

```ini
COHERE_API_KEY=...
HUGGINGFACE_API_KEY=...
```

`HUGGINGFACE_API_KEY` is always required — speech-to-text runs on HF Whisper whatever the chat
provider is. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens);
a read token is enough.

**Every outside source is keyless.** Search, Wikipedia, weather, news, dictionary, exchange
rates and crypto prices all serve anonymous requests, so there is no signup, no key to rotate,
and nothing to expire quietly months from now. Only the chat model and Whisper need keys.

`PyAudio` is needed by `SpeechRecognition` for mic input; on Windows install a prebuilt wheel
if pip tries to compile it.

## What it can do

| Say | What happens |
|---|---|
| "open / launch `<app>`" | Opens any installed app, then focuses it |
| "type `<text>`" | Types into the focused window |
| "search for `<thing>`" | Web search, answer spoken back |
| "tell me about `<topic>`" / "who invented `<X>`" | Wikipedia — searched, so a spoken question works |
| "tell me more about its history" | The full article, or one named section |
| "what does `<word>` mean" | Dictionary definition and an example |
| "how's the weather" / "weather in London" | Current conditions and today's outlook |
| "today's headlines" / "cricket news" | Top stories, read out |
| "what's 100 dollars in rupees" | Today's exchange rate |
| "what's bitcoin at" | Live price and the day's move |
| "take a screenshot" | Saves to Pictures\Screenshots |
| "what's the time" / "what's the date" | Spoken naturally |
| "wake me at 7" / "remind me in 10 minutes to X" | Speaks aloud when it's due |
| "email Rahul about X" | Reads it back, sends only on your yes |
| "whatsapp mum saying X" | Same — confirmed before sending |
| "google `<thing>`" | Opens a Google results page |
| "play `<thing>` on youtube" | Searches and plays the top hit |
| "play the next one" | Steps through the last search |
| "open my downloads folder" | File Explorer at the real known-folder path |
| "set volume to 70" / "louder" / "mute" | Media keys |
| "brightness to 40" | WMI, laptop panels only |
| "open display settings and turn night light on" | Opens the page, then flips the actual switch |
| "search inside settings for bluetooth" | Types into the app's own search box |
| "open incognito" / "InPrivate window" | Launches the browser with its own private switch |
| "close this tab" | Ctrl+W on the frontmost browser — the browser stays open |
| "close the tab in chrome" | Focuses Chrome first, then closes one tab |
| "close chrome" / "close the app" | Closes the whole app, and every window it owns |
| "pause" / "next" / "stop" | Real media keys — works with Spotify, VLC, browsers |
| "what's my ip" / "how much disk space" | Machine state, spoken |
| "find every python file mentioning api_key" | grep across files, any type |
| "what's taking up space in downloads" | find / du / sort through real files |
| "what can you do" | Lists its own tools by area |
| "are you working properly" | Parses every file, checks the gates, and really creates/edits a throwaway file to prove the tools work |
| "read my notes file" | Reads any text file back |
| "change the port to 9090 in config" | Says how many places, then waits for yes |
| "shut down" / "restart" | Asks first, then does it |
| "reset chat" / "start over" | Clears the conversation and the context |
| "wilco quit" | Exits |
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
│   ├── pc.py               Windows control, screenshots, time and date
│   ├── ui.py               reading and operating controls inside a window
│   ├── web.py              search, Wikipedia, weather, news, dictionary, rates, YouTube
│   ├── reminders.py        alarms that speak up on their own
│   ├── message.py          email and WhatsApp, both confirmed first
│   ├── shell_tool.py       PowerShell, Python and bash — free to read, confirmed to change
│   ├── selftest.py         what Wilco can do, and whether it still works
│   ├── voice.py            switching voice pack and talking speed
│   └── gate.py             holds a dangerous action until you say yes
├── mcp_server.py           the same tools over MCP stdio, for any MCP client
├── windows/                the machine half — apps, files, shell, speech, browser, system
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
- sending an email or a WhatsApp — recipient and full text are read back first, because a
  sent message is the one thing here that cannot be taken back
- writing to or editing a file — it says how many places would change first, and keeps
  the previous version as a `.bak`

A reply is read three ways, not two. A clear yes runs it, a clear no cancels it, and anything
else — a half-heard word, background noise, "thank you" — asks again rather than cancelling.
Hindi counts too: *haan*, *ji*, *theek hai*, *kar do* are yes; *nahi*, *mat karo*, *rehne do*
are no.

Everything else just runs. Locking the screen, opening apps, volume, brightness, media,
screenshots, reminders, searching and typing are all immediate.

## Contacts

Email and WhatsApp accept a saved name or a raw address/number. Copy
`contacts.example.json` to `contacts.json` (gitignored — it holds real addresses):

```json
{ "rahul": { "email": "rahul@example.com", "phone": "+91 98765 43210" } }
```

PowerShell is split by [mcp_tool/shell_tool.py](mcp_tool/shell_tool.py): a command runs freely
only if it starts with something read-only (`Get-*`, `ipconfig`, `systeminfo`, `tasklist`,
`ping`, `dir`…), contains no changing verb anywhere, and has no `;`, `>`, `&` or backtick that
could smuggle a second command in. Anything else is held.

The split exists because the input is speech — Whisper mishears, and the model composes the
command from what it heard, so a misheard sentence must never be able to reconfigure the
machine on its own.

## Use it as an MCP server

The same 60 tools are also exposed over the [Model Context Protocol](https://modelcontextprotocol.io),
so Claude Desktop, Claude Code or any MCP client can drive this machine.

```jsonc
// claude_desktop_config.json
{
  "mcpServers": {
    "wilco": { "command": "python", "args": ["C:/path/to/Wilco/mcp_server.py"] }
  }
}
```

[mcp_server.py](mcp_server.py) is a second front door, not new plumbing. `main.py` still calls
`mcp_tool.call()` in-process — putting JSON-RPC between two functions in one process would
only cost latency, and voice is latency-sensitive. Both read the one `REGISTRY`, so a tool
written for the voice loop appears over MCP with no extra work:

```
main.py ──────┐
              ├──> mcp_tool.REGISTRY ──> 60 tools
mcp_server.py ┘
```

The confirmation gate is keyed per client session, so one client can never confirm an action
another one parked. Tools run on a worker thread, since pressing 50 media keys would otherwise
block the event loop.

**This is real control of a real desktop.** An MCP client that connects gets the same reach
the voice loop has — files, PowerShell, windows, power state. The gate still holds the
dangerous half, but everything else runs on request.

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
| `WILCO_PAUSE` | `2.5` | Seconds of silence before it decides you've finished |
| `WILCO_VOICE` | `ava` | Which voice pack it starts in |
| `WILCO_SPEED` | `25` | Talking pace, as a percentage on top of that voice's own |
| `WILCO_ROOT` | *(every drive)* | `;`-separated folders to limit the file scan to |

`WILCO_PAUSE` is how long you may go quiet mid-sentence. Every microphone and room differs,
so tune it: raise it if you're still being cut off, lower it if replies feel sluggish.

```ini
WILCO_PAUSE=3.5
```

## Voices

| | |
|---|---|
| American | `ava` `andrew` `emma` `brian` |
| British | `sonia` `ryan` |
| Indian English | `neerja` `prabhat` |
| Australian | `natasha` |
| Hindi | `madhur` `swara` |
| Built-in Windows | `david` `zira` — flat, but offline and instant |

Ask for one out loud and it answers in it: *"switch to ryan"*, *"use an Indian voice"*,
*"what voices have you got"*.

Speed is yours to drive, from -50 to +100 percent of the voice's own pace:

| Say | What it does |
|---|---|
| "talk faster" / "speak slower" | ±15 from where it is |
| "speed up" / "slow down" | the same, shorter |
| "talk 20 percent faster" | ±20 from where it is |
| "set speech speed to 40" | straight to +40 |

Those hit the instant regex path — no LLM round trip, so the change lands as fast as you can
say it. Both the voice and the speed are written to `.wilco_voice.json` and survive a restart;
`WILCO_VOICE` and `WILCO_SPEED` only set where it starts before that file exists.

A reply is synthesised a sentence or two at a time and played while the rest is still being
made, so Wilco starts talking before the paragraph is finished. Short lines it repeats a lot
are cached on disk and come back instantly. If the network is down, or `edge-tts` isn't
installed, it falls back to the built-in Windows voice mid-sentence rather than going quiet.

## Known limits

- No wake word — it acts on every utterance.
- `speak()` blocks, so it is deaf while talking.
- The first file or folder command scans the drives, which takes a few seconds once per run.
- The app list is read once per session, so restart to pick up a new install.
- Windows-only: `win32com` and `ctypes` throughout, and mp3 playback goes through MCI.
- Neural speech is synthesised over the network, so a line it hasn't said before starts after
  roughly a second and a half. Repeats are cached and instant; `david` and `zira` are always
  instant but flat.
- Whisper runs over the network, so transcription costs a round trip.
- `set_volume` taps volume-down 50 times then back up, since each key press moves 2%.
