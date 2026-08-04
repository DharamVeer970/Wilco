import datetime
import os
import re
import subprocess
import webbrowser
from urllib.parse import quote_plus

from rapidfuzz import fuzz, process

import windows.apps as apps
import windows.files as files
from core import agent, context, online
import windows.shell as shell
import windows.system as system
from core.brain import ai
from mcp_tool import gate
from windows import voice
from windows.speech import speak

SITES = {
    "youtube": "https://www.youtube.com",
    "wikipedia": "https://www.wikipedia.org",
    "google": "https://www.google.com",
}
SEARCH = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
    "maps": "https://www.google.com/maps/search/{}",
    "amazon": "https://www.amazon.in/s?k={}",
    "github": "https://github.com/search?q={}",
}
KIND_WORDS = {
    "music": ("music", "song", "songs", "audio", "playlist"),
    "video": ("video", "videos", "movie", "movies"),
    "image": ("image", "images", "photo", "photos", "picture", "pictures"),
    "document": ("document", "documents", "pdf", "pdfs", "file", "files"),
}
ONLINE = "youtube"
LIST_LIMIT = 40
ASK_WHAT_NEXT = False  # the agent carries the conversation now, so the stock prompt just nags
DOWN = re.compile(r"\b(?:down|low|lower|decrease|reduce|less|quieter|softer|dim|dimmer|darker)\b")
BRIGHT = re.compile(r"\b(?:brightness|dim|dimmer|darker|brighten|brighter)\b")
# how fast the words come out, which is not how loud — "louder" belongs to the volume path
TALK = re.compile(
    r"\b(?:talk|talking|speak|speaking|speech|say|saying|voice|read|reading)\b[\w\s']{0,20}?"
    r"\b(?:speed|pace|rate|fast|faster|quick|quicker|slow|slower|slowly)\b"
    r"|\b(?:speed\s+up|slow\s+down)\b")
SLOWER = re.compile(r"\b(?:slow|slower|slowly|down|less)\b")
RELATIVE = re.compile(r"\b(?:faster|slower|quicker|slowly|more|less|up|down|bit)\b")
SPEED_STEP = 15
# each pattern is wrapped before THIS_PC is appended, or the suffix would bind to
# the last alternative only and "shut down the laptop" would never match
POWER = [
    (r"shut\s?down|turn\s+off|power\s+off", "shutdown"),
    (r"restart|reboot", "restart"),
    (r"lock(?:\s+(?:the|my)\s+screen)?", "lock"),
    (r"(?:go\s+to\s+)?sleep|hibernate|suspend|put\s+\S+(?:\s+\S+)?\s+to\s+sleep", "sleep"),
]
THIS_PC = r"(?:\s+(?:the|my|this))?(?:\s+(?:computer|pc|laptop|system|machine|thing))?"
MEDIA_WORDS = {"pause": "play_pause", "resume": "play_pause", "play_pause": "play_pause",
               "next": "next", "skip": "next", "previous": "previous", "back": "previous",
               "stop": "stop"}
STRIP = " .,!?;:'\""
# Whisper rarely spells an uncommon name the same way twice — add what yours actually hears
NAME = r"(?:wilco|wilko|will\s?co)"  # grouped, or a suffix would bind to the last alternative only

# what Wilco is waiting for: None | ("source", kind) | ("pick", kind, exe) | ("online", kind) | ("app", [candidates])
_pending = None


def _next():
    speak("What would you like to do next?")


def _kind(word):
    return next((k for k, w in KIND_WORDS.items() if word in w), None)


def _kind_asked_for(query):
    m = re.fullmatch(
        r"(?:play|open|show|list|start|listen to)\s+(?:me\s+)?(?:my|all|some|the|a)?\s*(\w+)",
        query,
    )
    return _kind(m.group(1)) if m else None


def _browse(kind):
    ask_source(kind) if kind in ("music", "video") else show_library(kind)


def _menu(title, labels, footer=None):
    print(f"\n--- {title} ---")
    for i, label in enumerate(labels, 1):
        print(f"{i:4}. {label}")
    if footer:
        print(footer)
    print("---")


def sources_for(kind):
    options = list(apps.openers(files.KINDS[kind]))
    if kind in ("music", "video"):
        options.append(("YouTube", None))
    return options


def ask_source(kind):
    global _pending
    options = sources_for(kind)
    if not options:
        speak(f"I couldn't find anything installed to open {kind} files.")
        return
    labels = [name for name, _ in options]
    _menu(f"where to play {kind} from", labels)
    _pending = ("source", kind)
    speak(f"I can use {', '.join(labels[:-1])} or {labels[-1]}. Which one?")


def show_library(kind, exe=None):
    global _pending
    items = files.library(kind)
    if not items:
        speak(f"I couldn't find any {kind} files on this computer.")
        return
    _menu(f"your {kind} files ({len(items)})",
          [f"{name}   [{os.path.dirname(path)}]" for name, path in items[:LIST_LIMIT]],
          f"     ... and {len(items) - LIST_LIMIT} more" if len(items) > LIST_LIMIT else None)
    _pending = ("pick", kind, exe)
    speak(f"I found {len(items)} {kind} files. Say the name or the number.")


def open_item(kind, spoken, exe=None):
    """Open the item the user named or numbered from a listing."""
    hit = files.find(kind, spoken, fuzzy=False)
    if not hit:
        return False
    name, path = hit
    return _open_path(kind, name, path, exe)


def open_any_file(name, kinds=("document", "image", "video", "music")):
    """Open a file of any kind, asking when more than one across all kinds matches."""
    global _pending
    several = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not several:
        return False
    if len(several) == 1:
        return _open_path(*several[0])
    _menu("which one?", [f"{n}   ({k}) [{os.path.dirname(p)}]" for k, n, p in several])
    _pending = ("files", several)
    _ask_choice([n for _, n, _ in several], "files")
    return True


def _open_path(kind, name, path, exe=None):
    context.file = path
    speak(f"Playing {name}." if kind == "music" else f"Opening {name}.")
    try:
        if exe and os.path.isfile(exe):
            subprocess.Popen([exe, path])
        else:
            files.open_file(path)
    except OSError as e:
        speak(f"I couldn't open {name}. {e.strerror or 'It refused to start'}.")
    return True


def open_app(name):
    """Launch an app, or ask which one when the name is ambiguous."""
    global _pending
    found = apps.candidates(name)
    if not found:
        return False
    if len(found) > 1:
        labels = [d for d, _ in found]
        _menu("which one?", labels)
        _pending = ("app", found)
        _ask_choice(labels, "apps")
        return True
    return _launch(*found[0])


def _launch(display, launch_id):
    speak(f"Opening {display}.")
    context.app = display
    try:
        apps.launch(launch_id)
    except OSError as e:
        speak(f"I couldn't open {display}. {e.strerror or 'It refused to start'}.")
    return True


def _folder_labels(found):
    """Two folders can share a name, so say which one by its parent."""
    return [f"{n} in {os.path.basename(os.path.dirname(p)) or p}" for n, p in found]


def _open_folder_path(name, path):
    context.folder = path
    speak(f"Opening {name}.")
    try:
        files.open_file(path)
    except OSError as e:
        speak(f"I couldn't open {name}. {e.strerror or 'It refused to open'}.")
    return True


def open_folder(name):
    """Open a known folder, else search the disk — and ask when several match."""
    global _pending
    path = system.open_folder(name)
    if path:
        context.folder = path
        speak(f"Opened your {name} folder.")
        return True
    found = files.folder_matches(name)
    if not found:
        speak(f"I couldn't find a {name} folder anywhere.")
        return True
    if len(found) > 1:
        labels = _folder_labels(found)
        _menu("which one?", [f"{lab}   [{p}]" for lab, (_, p) in zip(labels, found)])
        _pending = ("folder", found)
        _ask_choice(labels, "folders")
        return True
    return _open_folder_path(*found[0])


def web_search(query, site="google"):
    context.query = query
    speak(f"Searching {site} for {query}.")
    webbrowser.open(SEARCH[site].format(quote_plus(query)))


def play_online(text):
    """Search YouTube and play the top hit — never stop at the results page."""
    hits = online.search(text)
    if not hits:
        speak(f"I couldn't find {text} on YouTube.")
        return True
    context.remember_search(text, hits)
    return play_step(1)


def play_step(delta):
    hit = context.step(delta)
    if not hit:
        return False
    title, video_id = hit
    speak(f"Playing {title[:70]}.")
    online.play(video_id)
    return True


def show_in_folder(kind, folder_name=None):
    global _pending
    path = system.folder(folder_name) if folder_name else context.folder
    if folder_name and not path:
        found = files.folder_matches(folder_name)
        path = found[0][1] if found else None
    if not path:
        speak("Which folder?")
        return True
    items = files.in_folder(path, kind)
    where = os.path.basename(path.rstrip("\\")) or path
    if not items:
        speak(f"There are no {kind} files in {where}.")
        return True
    context.folder = path
    _menu(f"{kind} files in {path}", [name for name, _ in items[:LIST_LIMIT]])
    _pending = ("files", [(kind, n, p) for n, p in items])
    speak(f"{where} has {len(items)} {kind} files. Say a number to open one.")
    return True


INFO = [
    (r"\b(?:my |the )?ip(?: address)?\b", shell.ip_address, "Your I P is {}."),
    (r"\bwi-?fi\b(?!\s+(?:on|off))|\bnetwork\b", shell.wifi_status, "Wi-Fi is {}."),
    (r"\bbattery\b|\bcharge\b", shell.battery_percent, "Battery's at {} percent."),
    (r"\bcomputer(?:'s)? name\b|\bhostname\b", shell.computer_name, "This machine is called {}."),
    (r"\buptime\b|how long .*(?:running|on)\b", shell.uptime, "It's been running since {}."),
    (r"\b(?:disk|storage|free space|space left)\b",
     lambda: ", ".join(f"{free} of {total} gigs free on {c}" for c, free, total in shell.disk_free()),
     "You've got {}."),
    (r"what(?:'s| is)? running\b|\brunning (?:apps|programs)\b|\btask list\b",
     lambda: ", ".join(shell.running_apps()), "Right now you've got {} open."),
]


def system_info(query):
    for pattern, get, template in INFO:
        if re.search(pattern, query):
            value = get()
            return template.format(value) if value not in (None, "") else "Couldn't read that."
    return None


def ask_confirm(phrase, action):
    global _pending
    _pending = ("confirm", phrase, action)
    speak(f"You sure you want me to {phrase}?")
    return True


def _match_option(query, labels):
    number = re.fullmatch(r"(?:number\s+|the\s+)?(\d{1,2})(?:st|nd|rd|th)?", query)
    if number and 1 <= int(number.group(1)) <= len(labels):
        return labels[int(number.group(1)) - 1]
    exact = next((n for n in labels if n.lower() == query), None)
    if exact:
        return exact
    # a label buried in the utterance: the longest one explains most of it
    hit = next((n for n in sorted(labels, key=len, reverse=True) if n.lower() in query), None)
    if not hit and len(query) > 2:
        # the utterance is a fragment of a label: the shortest one adds least
        hit = next((n for n in sorted(labels, key=len) if query in n.lower()), None)
    if hit:
        return hit
    best = process.extractOne(query, [n.lower() for n in labels],
                              scorer=fuzz.ratio, score_cutoff=65)
    return labels[best[2]] if best else None


def _ask_choice(labels, noun="matches"):
    if len(labels) > 3:
        speak(f"I found {len(labels)} {noun}. Say the number, or a fuller name.")
    else:
        speak(f"Did you mean {', '.join(labels[:-1])} or {labels[-1]}?")


def _answer_pending(what, query):
    global _pending
    if what[0] == "confirm":
        _, phrase, action = what
        answer = gate._reply_kind(query)
        if answer == "yes":
            action()
            speak(f"Okay, {phrase}.")
            return True
        if answer == "no":
            speak("Okay, cancelled.")
            return True
        # Neither. Don't cancel — a misheard word is not a refusal. Returning False lets the
        # rest of dispatch try to read it as a fresh command; if nothing does, the question
        # is put back and asked again at the end of _dispatch.
        return False

    if what[0] == "app":
        found = what[1]
        chosen = _match_option(query, [d for d, _ in found])
        if not chosen:
            return False
        return _launch(*next(f for f in found if f[0] == chosen))

    if what[0] == "folder":
        found = what[1]
        labels = _folder_labels(found)
        chosen = _match_option(query, labels)
        if not chosen:
            return False
        return _open_folder_path(*found[labels.index(chosen)])

    if what[0] == "files":
        several = what[1]
        chosen = _match_option(query, [n for _, n, _ in several])
        if not chosen:
            return False
        return _open_path(*next(s for s in several if s[1] == chosen))

    kind = what[1]
    if what[0] == "pick":
        return open_item(kind, query, exe=what[2])
    if what[0] == "online":
        if not query:
            return False
        web_search(query, ONLINE)
        return True

    options = dict(sources_for(kind))
    chosen = _match_option(query, list(options))
    if not chosen:
        return False
    if chosen == "YouTube":
        _pending = ("online", kind)
        speak("Which one should I search on YouTube?")
    else:
        show_library(kind, exe=options[chosen])
    return True


def do(action, target):
    """Run one resolved intent. True if it was handled."""
    if action == "open_app":
        return open_app(target)
    if action == "open_folder":
        return open_folder(target)
    if action == "open_site" and target.lower() in SITES:
        speak(f"Opening {target}.")
        webbrowser.open(SITES[target.lower()])
        return True
    if action == "web_search":
        web_search(target)
        return True
    if action == "windows_search":
        system.windows_search(target)
        speak(f"Searching Windows for {target}.")
        return True
    if action in ("play_media", "show_library"):
        _browse(_kind(target.rsplit(" ", 1)[-1]) or "music")
        return True
    if action == "type_text":
        system.type_text(target)
        speak(f"Typed {target}.")
        return True
    if action in ("volume_up", "volume_down"):
        system.volume_step("up" if action == "volume_up" else "down")
        speak("Volume up." if action == "volume_up" else "Volume down.")
        return True
    if action == "mute":
        system.mute()
        speak("Muted.")
        return True
    if action == "media":
        running = system.media_app_running()
        if not running:
            ask_source("music")
            return True
        system.media(target)
        said = {"play_pause": "Toggled playback", "next": "Skipped to the next track",
                "previous": "Went back a track", "stop": "Stopped playback"}[target]
        speak(f"{said} on {running[0]}.")
        return True
    if action == "set_volume":
        number = re.search(r"\d{1,3}", target)
        if not number:
            return False
        speak(f"Volume set to {system.set_volume(number.group(0))} percent.")
        return True
    if action == "speech_speed":
        now = voice.current()[3]
        number = re.search(r"-?\d{1,3}", target)
        step = int(number.group(0)) if number else SPEED_STEP
        if number and not RELATIVE.search(target):
            level = step
        else:
            level = now - step if SLOWER.search(target) else now + step
        speak(f"Talking at {voice.set_speed(level)} percent now.")
        return True
    if action == "set_brightness":
        number = re.search(r"\d{1,3}", target)
        current = system.get_brightness()
        if number:
            level = int(number.group(0))
        elif current is not None:
            level = current - 20 if DOWN.search(target) else current + 20
        else:
            speak("This screen doesn't report its brightness, so I can't change it.")
            return True
        done = system.set_brightness(level)
        speak(f"Brightness set to {done} percent." if done else "I couldn't change the brightness.")
        return True
    if action in ("wifi_on", "wifi_off"):
        ok = system.wifi(action == "wifi_on")
        state = "on" if action == "wifi_on" else "off"
        speak(f"Wi-Fi turned {state}." if ok else "I need administrator rights to change Wi-Fi.")
        return True
    if action == "time":
        speak(f"Sir, the time is {datetime.datetime.now():%H bajke %M} minutes")
        return True
    if action == "open_settings":
        page = system.settings_page(target)
        if page is None:
            return False
        system.open_settings(target)
        speak(f"Opening {page.replace('-', ' ')} settings." if page else "Opening Settings.")
        return True
    if action == "shutdown":
        return ask_confirm("shut it down", lambda: shell.shutdown(False))
    if action == "restart":
        return ask_confirm("restart it", lambda: shell.shutdown(True))
    if action == "empty_recycle_bin":
        return ask_confirm("empty the recycle bin", shell.empty_recycle_bin)
    if action == "cancel_shutdown":
        shell.cancel_shutdown()
        speak("Cancelled the shutdown.")
        return True
    if action == "lock":
        speak("Locking up.")
        shell.lock()
        return True
    if action == "sleep":
        speak("Going to sleep.")
        shell.sleep()
        return True
    if action == "close_app":
        _close(target)
        return True
    return False


# "can you please just open notepad for me" -> "open notepad": every fullmatch below
# only ever saw the polite wrapper, so the whole command fell through to chat
# People don't start sentences with the verb. "Now can you open Spotify" used to match nothing
# at all, because the politeness stripper insisted the sentence BEGIN with "can you" — one
# stray "now" and the whole command fell through as if it had never been understood. These are
# allowed to repeat and to appear on either side of the "can you", in any order.
FILLER = (r"(?:hey|hi|hello|ok|okay|so|now|well|um+|uh+|erm|like|actually|alright|right|"
          r"listen|please|just|kindly|quickly|maybe|then|also|and)")
POLITE = re.compile(
    r"^(?:" + FILLER + r"[\s,]+)*(?:" + NAME + r"[\s,]*)?(?:" + FILLER + r"[\s,]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|u)\s+)?"
    r"(?:(?:i\s+(?:want|need)\s+(?:you\s+)?to|i'?d\s+like\s+(?:you\s+)?to)\s+)?"
    r"(?:" + FILLER + r"[\s,]+)*")
TRAILING = re.compile(r"(?:[\s,]+(?:please|for\s+me|mate|buddy|bro|now|" + NAME + r"|thanks?))+$")


def _bare(query):
    """Strip the politeness a person speaks but a regex can't read past."""
    return TRAILING.sub("", POLITE.sub("", query)).strip(STRIP) or query


SPLIT_RE = re.compile(r"\s+(?:and then|and also|then|and)\s+")
VERBS = ("open", "show", "play", "search", "google", "find", "type", "write", "set",
         "turn", "go to", "list", "close", "pause", "next", "previous", "stop",
         "mute", "volume", "brightness", "launch", "start")


FAST_WORDS = 9
QUESTION = re.compile(
    r"^(?:what|why|how|when|where|who|which|whose|whom|whats|what's|"
    r"is|are|was|were|do|does|did|should|shall|may|might|"
    r"tell|explain|define|describe|compare|suggest|recommend|think)\b")


def _for_the_agent(query):
    """True when the pattern table should not get first refusal at this sentence.

    The fast path matches keywords, not meaning. "What is the volume of a sphere" contains the
    word volume, so it turned the volume up; "why is screen brightness bad for eyes" changed
    the brightness. Questions and long multi-part sentences are precisely where keyword
    matching guesses wrong, and precisely where a second of real thinking costs nothing.

    Short imperatives — "volume up", "open notepad", "pause" — stay on the instant path.
    """
    bare = _bare(query)
    return bool(QUESTION.match(bare)) or len(bare.split()) > FAST_WORDS


def _split_compound(query):
    """Split only when each later part really starts another command."""
    parts = [p.strip(STRIP) for p in SPLIT_RE.split(query) if p.strip(STRIP)]
    # test the bare part: "and then just play music" starts with filler, not with a verb
    if len(parts) > 1 and all(_bare(p).startswith(VERBS) for p in parts[1:]):
        return parts
    return [query]


def handle(query):
    """Run one command. Return False to quit, True to keep listening."""
    query = query.strip(STRIP)

    # Anything that isn't a short, plain order goes straight to the agent. It reads the whole
    # sentence and has every tool, so it can act OR answer — where the pattern table can only
    # spot a keyword and hope. A menu waiting for an answer takes priority over this.
    if _pending is None and _for_the_agent(query):
        agent.respond(query)
        return True

    parts = _split_compound(query)

    if len(parts) == 1:
        result = _dispatch(query)
        if result == "command" and ASK_WHAT_NEXT and _pending is None:
            _next()
        return result is not False

    done, failed = [], []
    for part in parts:
        result = _dispatch(part, allow_chat=False)
        if result is False:
            return False
        (done if result == "command" else failed).append(part)
        if _pending is not None:
            break
    if failed:
        # The regex table couldn't do all of it — but that was never a reason to give up.
        # The agent has the tools and can chain them, so it gets the whole sentence rather
        # than a half-finished job being reported as a failure. What already ran is named
        # so it doesn't happen twice.
        agent.respond(query, already_done=done)
    elif ASK_WHAT_NEXT and _pending is None:
        _next()
    return True


def _follow_up(query):
    """Resolve 'next one', 'play it' and friends against what we just did."""
    step = re.fullmatch(
        r"(?:play|open|go\s+to)?\s*(?:the\s+)?(next|previous|last)\s*(?:one|song|video|track)?",
        query)
    if step and context.results:
        if play_step(1 if step.group(1) == "next" else -1):
            return "command"
        speak("That's the end of the list.")
        return "command"

    m = re.fullmatch(r"close\b\s*(.*)", query)
    if m:
        return _close(m.group(1).strip(STRIP))

    if re.fullmatch(r"what(?:'s| is| was)\s+(?:that|it|this|playing)"
                    r"|what did (?:you play|i search(?: for)?)", query):
        current = context.current()
        if current:
            speak(f"That's {current[0][:70]}.")
        elif context.query:
            speak(f"You last searched for {context.query}.")
        elif context.file:
            speak(f"The last thing I opened was {os.path.basename(context.file)}.")
        elif context.app:
            speak(f"The last thing I opened was {context.app}.")
        else:
            speak("Nothing yet.")
        return "command"

    if re.fullmatch(r"(?:play|resume|open)\s*(?:it|that|this|the\s+same|again)?", query):
        current = context.current()
        if current:
            speak(f"Playing {current[0][:70]}.")
            online.play(current[1])
        elif context.results:
            play_step(1)
        elif context.file:
            speak(f"Opening {os.path.basename(context.file)} again.")
            files.open_file(context.file)
        else:
            speak("Play what? Nothing's queued.")
        return "command"
    return None


# "close this browser tab" and "close the tab in chrome" used to miss this and fall through
# to taskkill — which killed the whole browser when all that was wanted was one tab
FILLER = r"(?:this|that|the|current|my|active|open|browser|chrome)"
SCOPE = re.compile(rf"(?:{FILLER}\s+)*(tab|window)s?(?:\s+(?:in|on|of)\s+(?:the\s+|my\s+)?(.+))?$")
ITSELF = ("", "it", "that", "this", "the app", "this app", "the application")
# "close everything" is not "close the thing in front" — it needs asking about, not guessing
VAGUE = re.compile(r"(?:everything|all|all of (?:it|them)|all (?:the )?(?:apps|windows|tabs))")


def _close(name):
    """Close a tab, a window, a named app, or whatever is in front."""
    scope = SCOPE.fullmatch(name)
    if scope:
        kind, where = scope.group(1), (scope.group(2) or "").strip(STRIP)
        acted = system.close_tab(where) if kind == "tab" else system.close_window(where)
        if not acted:
            speak(f"I couldn't find a {where or 'browser'} window to close a {kind} in.")
            return "command"
        speak(f"Closed a {kind} in {acted[:60]}." if kind == "tab" else f"Closed {acted[:60]}.")
        return "command"

    if VAGUE.fullmatch(name):
        return None  # the agent can ask which, and see what's actually open

    target = name
    if name in ITSELF:
        # "close the app" means the one in front, whether or not Wilco is what opened it
        target = context.app or system.foreground_window()[1]
    if not target:
        speak("Close what? Nothing's in front and I haven't opened anything.")
        return "command"
    closed = shell.close_app(target)
    if not closed:
        # nothing by that name is running. The agent can look at the open windows and work
        # out what "the browser" or "my editor" meant, which a name match never will
        return None
    speak(f"Closed {target}.")
    if target == context.app:
        context.app = None
    return "command"


def _dispatch(query, allow_chat=True):
    global _pending
    spoken = query.strip(STRIP)
    query = _bare(spoken)

    if re.fullmatch(r"(?:" + NAME + r"[ ,]*)?(?:quit|exit|goodbye|bye)", query):
        speak("See you later!")
        return False

    if re.fullmatch(r"(?:start over|new task|forget (?:it|that|everything))", query):
        context.clear()
        agent.reset()
        speak("Starting fresh.")
        return "command"

    resolved = _follow_up(query)
    if resolved:
        return resolved

    unanswered = None
    if _pending is not None:
        unanswered, _pending = _pending, None
        if _answer_pending(unanswered, query):
            return "command"

    site = next((s for s in SITES if f"open {s}" in query), None)
    if site:
        speak(f"Opening {site}.")
        webbrowser.open(SITES[site])
        return "command"
    if "the time" in query:
        do("time", "")
        return "command"
    if "using artificial intelligence" in query:
        ai(query)
        return "command"
    if "reset chat" in query:
        agent.reset()
        speak("Chat history reset.")
        return "command"

    m = re.match(r"(?:type|write)\s+(.+)", query)
    if m:
        # type what was actually said, politeness and all — it's literal text
        exact = re.search(r"(?:type|write)\s+(.+)", spoken, re.I)
        do("type_text", (exact or m).group(1).strip(STRIP))
        return "command"
    m = re.match(r"show\s+(?:me\s+)?(?:the\s+|all\s+)?(\w+)"
                 r"(?:\s+(?:in|from|inside)\s+(?:my\s+|the\s+)?([\w ]+?)(?:\s+folder)?)?$", query)
    if m:
        kind = _kind(m.group(1))
        if kind:
            return "command" if show_in_folder(kind, m.group(2)) else "unhandled"

    m = re.match(r"(?:search|find)\s+(?:for\s+)?(.+?)\s+(?:in|on)\s+windows$", query)
    if m:
        do("windows_search", m.group(1).strip(STRIP))
        return "command"
    m = re.match(r"(?:open|go to)\s+(?:my\s+|the\s+)?([\w ]+?)\s+folder", query)
    if m:
        do("open_folder", m.group(1))
        return "command"
    if re.fullmatch(r"(?:mute|unmute)(?:\s+(?:the\s+)?(?:sound|volume|audio))?", query):
        do("mute", "")
        return "command"
    if re.search(r"\bvolume\b|\blouder\b|\bquieter\b|\bsofter\b", query):
        if re.search(r"\d", query):
            do("set_volume", query)
        else:
            do("volume_down" if DOWN.search(query) else "volume_up", "")
        return "command"
    if TALK.search(query):
        do("speech_speed", query)
        return "command"
    if BRIGHT.search(query):
        do("set_brightness", query)
        return "command"
    m = re.fullmatch(r"(?:turn\s+)?(?:(on|off)\s+)?(?:the\s+)?wi-?fi(?:\s+(on|off))?", query)
    if m and (m.group(1) or m.group(2)):
        do("wifi_on" if (m.group(1) or m.group(2)) == "on" else "wifi_off", "")
        return "command"

    word = re.fullmatch(r"(?:media\s+)?(pause|resume|next|skip|previous|back|stop)"
                        r"(?:\s+(?:the\s+)?(?:song|track|video|music))?", query)
    if word and do("media", MEDIA_WORDS[word.group(1)]):
        return "command"

    if re.fullmatch(r"cancel (?:the )?(?:shutdown|restart)|(?:don't|do not) shut ?down", query):
        do("cancel_shutdown", "")
        return "command"
    action = next((a for p, a in POWER if re.fullmatch(f"(?:{p}){THIS_PC}", query)), None)
    if action:
        do(action, "")
        return "command"
    if re.search(r"empty (?:the )?(?:recycle bin|trash)", query):
        do("empty_recycle_bin", "")
        return "command"
    m = re.fullmatch(r"ping\s+([\w.:-]+)", query)
    if m:
        speak(shell.ping(m.group(1)) or f"Couldn't reach {m.group(1)}.")
        return "command"

    said = system_info(query)
    if said:
        speak(said)
        return "command"

    kind = _kind_asked_for(query)
    if kind:
        _browse(kind)
        return "command"

    m = re.match(r"(?:play|put on)\s+(?:the\s+)?(.+?)(?:\s+on\s+youtube)?$", query)
    if m:
        play_online(m.group(1).strip(STRIP))
        return "command"

    # only an explicitly named destination takes the instant path. A bare "search for X" or
    # "find X" goes to the agent instead, which can actually read the web and answer, or
    # look for a file — opening a results page was never what was being asked for.
    m = re.match(r"(?:search|google|look up|find)\s+(?:for\s+)?(.+)", query)
    if m:
        text = m.group(1).strip(STRIP)
        on = re.search(r"\s+(?:on|in)\s+(\w+)$", text)
        site = on.group(1) if on and on.group(1) in SEARCH else None
        if text and (site or query.startswith("google")):
            if site:
                text = text[: on.start()].strip(STRIP)
            if text:
                play_online(text) if site == ONLINE else web_search(text, site or "google")
                return "command"

    if re.search(r"\bsettings?\b|\boptions?\b", query) and do("open_settings", query):
        return "command"

    m = re.match(r"(?:open|launch|start)\s+(?:my\s+|the\s+)?(.+)", query)
    if m:
        name = re.sub(r"\s+(?:app|application|file)$", "", m.group(1).strip(STRIP))
        if open_app(name) or open_any_file(name):
            return "command"

    # A fresh order abandons an unanswered menu. Without this a menu nobody wanted to answer
    # sat there swallowing every following command with "which one did you mean?", and the
    # only way out was to answer a question the user had already moved on from.
    if unanswered is not None and not query.startswith(VERBS) and not QUESTION.match(query):
        _pending = unanswered  # keep the question alive — this really did look like an answer
        if unanswered[0] == "confirm":
            speak(f"Sorry, I didn't catch that. Should I {unanswered[1]}? Say yes or no.")
        else:
            speak("Sorry, which one did you mean?")
        return "command"

    if not allow_chat:
        return "unhandled"
    # everything the patterns didn't catch goes to the agent, which has the tools and can
    # both act and talk — so an unmatched phrasing is a conversation, not a dead end
    agent.respond(spoken)
    return "chat"
