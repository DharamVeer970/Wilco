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
from config import ALWAYS_ACT, ASK_WHAT_NEXT, LIST_LIMIT, SPEED_STEP
from core import roman
from core.brain import ai
from mcp_tool import gate
from windows import voice
from windows.speech import speak

from core.commands.patterns import (
    SITES, SEARCH, KIND_WORDS, ONLINE, DOWN, BRIGHT, TALK, SLOWER, COMPOSE, RELATIVE, BY_N,
    POWER, THIS_PC, MEDIA_WORDS, STRIP, WHICH, NAME, HINDI, _HINDI, PLAIN, RECALL,
    KIND_ASKED, FILLER, POLITE, TRAILING, SPLIT_RE, VERBS, QUESTION,
    STEP, CLOSE, WHAT_IS_IT, PLAY_IT, SCOPE, ITSELF, VAGUE, FILLER_RE,
    QUIT, FRESH, TYPE, TYPE_SPOKEN, CODE_WRITE, SHOW, IN_WINDOWS, NAMED_FOLDER,
    FILE_SEARCH, DIR_NAMED, DIR_PATH, DRIVES, LIST_DRIVES, FILE_INFO, MUTE, VOLUME,
    DIGIT, WIFI, MEDIA, CANCEL, RECYCLE, PING, PLAY, SEARCH_FOR, ON_SITE, SETTINGS,
    OPEN, APP_SUFFIX, MEDIA_SAID,
)

# what Wilco is waiting for: None | ("source", kind) | ("pick", kind, exe) | ("online", kind) | ("app", [candidates])
_pending = None


def _hindi(query):
    """The English command a Hindi one means, or None. Costs nothing but a lookup table."""
    latin = (roman.romanise(query) if roman.has_devanagari(query) else query).lower().strip(STRIP)
    for pattern, english in _HINDI:
        found = pattern.search(latin)
        if found:
            filled = english.format(*found.groups()) if found.groups() else english
            return filled.strip()
    return None


def _next():
    speak("What would you like to do next?")


def _kind(word):
    return next((k for k, w in KIND_WORDS.items() if word in w), None)


# KIND_ASKED imported from commands_patterns


def _kind_asked_for(query):
    m = KIND_ASKED.fullmatch(query)
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
    # A complete path is already the answer. Avoid scanning every drive.
    direct = os.path.abspath(os.path.expanduser(name.strip().strip('"')))
    if os.path.isfile(direct):
        kind = files.EXT_KIND.get(os.path.splitext(direct)[1].lower(), "document")
        return _open_path(kind, os.path.splitext(os.path.basename(direct))[0], direct)
    several = [(k, n, p) for k in kinds for n, p in files.matches(k, name)]
    if not several:
        return False
    if len(several) == 1:
        return _open_path(*several[0])
    _menu(WHICH, [f"{n}   ({k}) [{os.path.dirname(p)}]" for k, n, p in several])
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
        _menu(WHICH, labels)
        _pending = ("app", found)
        _ask_choice(labels, "apps")
        return True
    return _launch(*found[0])


def _launch(display, launch_id):
    speak(f"Opening {display}.")
    context.app = display
    try:
        apps.launch(launch_id)
        # A following "type ..." must land in the app we just opened, not the old window.
        system.focus_window(display, wait=4)
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
        _menu(WHICH, [f"{lab}   [{p}]" for lab, (_, p) in zip(labels, found)])
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
        return
    items = files.in_folder(path, kind)
    where = os.path.basename(path.rstrip("\\")) or path
    if not items:
        speak(f"There are no {kind} files in {where}.")
        return
    context.folder = path
    _menu(f"{kind} files in {path}", [name for name, _ in items[:LIST_LIMIT]])
    _pending = ("files", [(kind, n, p) for n, p in items])
    speak(f"{where} has {len(items)} {kind} files. Say a number to open one.")


INFO = [
    (r"\b(?:my |the )?ip(?: address)?\b", shell.ip_address, "Your I P is {}."),
    # Asked first: "wifi password", "password of my wifi", "tell me the wifi password".
    # In all-access mode the password is spoken back directly so the user can read it to
    # connect another device; this entry sits ahead of the status match so the word
    # "password" always wins over a plain "wifi is up" reply.
    (r"\b(?:wi-?fi|network)\b[^.\n]{0,24}\bpassword\b" +
     r"|\bpassword\b[^.\n]{0,24}\b(?:wi-?fi|network)\b" +
     r"|\b(?:wi-?fi|network)\b\s+(?:key|pass)\b",
     shell.wifi_password, "The Wi-Fi password is {}."),
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


def ask_confirm(phrase, action):  # NOSONAR - always True = handled, not success/failure
    global _pending
    if ALWAYS_ACT:
        # All-access mode: the user already spoke the command — do it, no question.
        action()
        speak(f"Okay, {phrase}.")
        return True
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


def _answer_confirm(what, query):
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


def _answer_app(what, query):
    found = what[1]
    chosen = _match_option(query, [d for d, _ in found])
    if not chosen:
        return False
    return _launch(*next(f for f in found if f[0] == chosen))


def _answer_folder(what, query):
    found = what[1]
    labels = _folder_labels(found)
    chosen = _match_option(query, labels)
    if not chosen:
        return False
    return _open_folder_path(*found[labels.index(chosen)])


def _answer_files(what, query):
    several = what[1]
    chosen = _match_option(query, [n for _, n, _ in several])
    if not chosen:
        return False
    return _open_path(*next(s for s in several if s[1] == chosen))


def _answer_pick(what, query):
    return open_item(what[1], query, exe=what[2])


def _answer_online(what, query):
    if not query:
        return False
    web_search(query, ONLINE)
    return True


def _answer_source(what, query):
    global _pending
    kind = what[1]
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


ANSWERS = {"confirm": _answer_confirm, "app": _answer_app, "folder": _answer_folder,
           "files": _answer_files, "pick": _answer_pick, "online": _answer_online}


def _answer_pending(what, query):
    """Read the utterance as an answer to the question we asked. True if it was one."""
    return ANSWERS.get(what[0], _answer_source)(what, query)


def _do_site(target):
    if target.lower() not in SITES:
        return False
    speak(f"Opening {target}.")
    webbrowser.open(SITES[target.lower()])
    return True


def _do_web_search(target):
    web_search(target)
    return True


def _do_windows_search(target):
    system.windows_search(target)
    speak(f"Searching Windows for {target}.")
    return True


def _do_library(target):
    _browse(_kind(target.rsplit(" ", 1)[-1]) or "music")
    return True


def _do_type(target):
    system.type_text(target)
    speak(f"Typed {target}.")
    return True


def _do_volume(way):
    def step(_target):
        system.volume_step(way)
        speak(f"Volume {way}.")
        return True
    return step


def _do_mute(_target):
    system.mute()
    speak("Muted.")
    return True


def _do_media(target):
    running = system.media_app_running()
    if not running:
        ask_source("music")
        return None
    system.media(target)
    speak(f"{MEDIA_SAID[target]} on {running[0]}.")
    return True


def _do_set_volume(target):
    number = re.search(r"\d{1,3}", target)
    if not number:
        return False
    speak(f"Volume set to {system.set_volume(number.group(0))} percent.")
    return True


def _do_speech_speed(target):
    now = voice.current()[3]
    number = re.search(r"-?\d{1,3}", target)
    step = int(number.group(0)) if number else SPEED_STEP
    if number and not RELATIVE.search(target):
        level = step
    else:
        level = now - step if SLOWER.search(target) else now + step
    speak(f"Talking at {voice.set_speed(level)} percent now.")
    return True


def _do_brightness(target):
    # "by N" is a step size ("decrease by 10" from 60 -> 50), never an absolute level —
    # treating that 10 as the target used to slam the screen to 10 percent.
    down = bool(DOWN.search(target))
    by = BY_N.search(target)
    number = re.search(r"\d{1,3}", target)
    if by or not number:
        current = system.get_brightness()
        if current is None:
            speak("This screen doesn't report its brightness, so I can't change it.")
            return None
        delta = int(by.group(1)) if by else 20
        level = current - delta if down else current + delta
    else:
        level = int(number.group(0))
    done = system.set_brightness(level)
    speak(f"Brightness set to {done} percent." if done else "I couldn't change the brightness.")
    return True


def _do_wifi(on):
    def switch(_target):
        ok = system.wifi(on)
        state = "on" if on else "off"
        speak(f"Wi-Fi turned {state}." if ok else "I need administrator rights to change Wi-Fi.")
        return True
    return switch


def _oclock(hour, minute):
    """The hour and minute the way a person says them out loud."""
    if minute == 0:
        return f"{hour} o'clock"
    if minute < 10:
        return f"{hour} oh {minute}"
    if minute == 30:
        return f"half past {hour}"
    if minute < 45:
        return f"{hour} {minute}"
    return f"{60 - minute} to {hour % 12 + 1}"


def _part_of_day(hour):
    if hour < 12:
        return "in the morning"
    if hour < 17:
        return "in the afternoon"
    return "in the evening"


def _do_time(_target):
    now = datetime.datetime.now()
    speak(f"The time is {_oclock(now.hour % 12 or 12, now.minute)} {_part_of_day(now.hour)}.")
    return True


def _do_settings(target):
    page = system.settings_page(target)
    if page is None:
        return False
    system.open_settings(target)
    speak(f"Opening {page.replace('-', ' ')} settings." if page else "Opening Settings.")
    return True


def _do_cancel_shutdown(_target):
    shell.cancel_shutdown()
    speak("Cancelled the shutdown.")
    return True


def _do_lock(_target):
    speak("Locking up.")
    shell.lock()
    return True


def _do_sleep(_target):
    speak("Going to sleep.")
    shell.sleep()
    return True


def _do_close(target):
    _close(target)
    return True


ACTIONS = {
    "open_app": open_app,
    "open_folder": open_folder,
    "open_site": _do_site,
    "web_search": _do_web_search,
    "windows_search": _do_windows_search,
    "play_media": _do_library,
    "show_library": _do_library,
    "type_text": _do_type,
    "volume_up": _do_volume("up"),
    "volume_down": _do_volume("down"),
    "mute": _do_mute,
    "media": _do_media,
    "set_volume": _do_set_volume,
    "speech_speed": _do_speech_speed,
    "set_brightness": _do_brightness,
    "wifi_on": _do_wifi(True),
    "wifi_off": _do_wifi(False),
    "time": _do_time,
    "open_settings": _do_settings,
    "shutdown": lambda _t: ask_confirm("shut it down", lambda: shell.shutdown(False)),
    "restart": lambda _t: ask_confirm("restart it", lambda: shell.shutdown(True)),
    "empty_recycle_bin": lambda _t: ask_confirm("empty the recycle bin", shell.empty_recycle_bin),
    "cancel_shutdown": _do_cancel_shutdown,
    "lock": _do_lock,
    "sleep": _do_sleep,
    "close_app": _do_close,
}


def do(action, target):
    """Run one resolved intent. True if it was handled."""
    run = ACTIONS.get(action)
    if run is None:
        return False
    # False means the input did not match; None is a handled command with no result to return.
    return run(target) is not False


# FILLER/POLITE/TRAILING imported from commands_patterns


def _bare(query):
    """Strip the politeness a person speaks but a regex can't read past."""
    return TRAILING.sub("", POLITE.sub("", query)).strip(STRIP) or query


# SPLIT_RE / VERBS / QUESTION imported from commands_patterns


def _for_the_agent(query):
    """True when the pattern table should not get first refusal at this sentence.

    The fast path matches keywords, not meaning. "What is the volume of a sphere" contains the
    word volume, so it turned the volume up; "why is screen brightness bad for eyes" changed
    the brightness. Questions need the agent first so a keyword cannot be mistaken for an
    instruction. Imperatives get one local attempt; unknown ones still reach the agent.

    Short imperatives — "volume up", "open notepad", "pause" — stay on the instant path.
    """
    bare = _bare(query)
    if RECALL.match(bare):
        return False  # these are answered from the instant path's own memory, not the agent
    return bool(QUESTION.match(bare))


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
    query = _hindi(query) or query

    # Anything that isn't a short, plain order goes straight to the agent. It reads the whole
    # sentence and has every tool, so it can act OR answer — where the pattern table can only
    # spot a keyword and hope. A menu waiting for an answer takes priority over this.
    # a couple of questions are not ambiguous at all, and paying two API calls to be told
    # the time is waste the question-gate was never meant to cause
    if _pending is None and not PLAIN.match(_bare(query)) and _for_the_agent(query):
        agent.respond(query)
        return True

    parts = _split_compound(query)

    if len(parts) == 1:
        result = _dispatch(query)
        if result == "command" and not FRESH.fullmatch(_bare(query)):
            _remember_local_command(query)
        if result == "command" and ASK_WHAT_NEXT and _pending is None:
            _next()
        return result is not False
    return _run_parts(parts, query)


def _run_parts(parts, query):
    """Run a compound sentence part by part, handing the rest to the agent."""
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
    else:
        _remember_local_command(query)
        if ASK_WHAT_NEXT and _pending is None:
            _next()
    return True


# STEP / CLOSE / WHAT_IS_IT / PLAY_IT imported from commands_patterns


def _up_next(query):
    step = STEP.fullmatch(query)
    if not (step and context.results):
        return None
    if not play_step(1 if step.group(1) == "next" else -1):
        speak("That's the end of the list.")
    return "command"


def _close_it(query):
    m = CLOSE.fullmatch(query)
    return _close(m.group(1).strip(STRIP)) if m else None


def _last_thing():
    """What the instant path remembers doing most recently."""
    current = context.current()
    if current:
        return f"That's {current[0][:70]}."
    if context.query:
        return f"You last searched for {context.query}."
    if context.file:
        return f"The last thing I opened was {os.path.basename(context.file)}."
    if context.app:
        return f"The last thing I opened was {context.app}."
    return "Nothing yet."


def _what_was_that(query):
    if not WHAT_IS_IT.fullmatch(query):
        return None
    speak(_last_thing())
    return "command"


def _play_it_again(query):
    if not PLAY_IT.fullmatch(query):
        return None
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


FOLLOW_UPS = (_up_next, _close_it, _what_was_that, _play_it_again)


def _follow_up(query):
    """Resolve 'next one', 'play it' and friends against what we just did."""
    for check in FOLLOW_UPS:
        resolved = check(query)
        if resolved:
            return resolved
    return None


# SCOPE / ITSELF / VAGUE / FILLER_RE imported from commands_patterns


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
        # nothing recorded and nothing in front, but the agent can read the open windows and
        # work out what "this" meant — better than telling the user to rephrase
        return None
    closed = shell.close_app(target)
    if not closed:
        # nothing by that name is running. The agent can look at the open windows and work
        # out what "the browser" or "my editor" meant, which a name match never will
        return None
    speak(f"Closed {target}.")
    if target == context.app:
        context.app = None
    return "command"


from core.commands.steps import STEPS


def _reask(unanswered):
    global _pending
    _pending = unanswered  # keep the question alive — this really did look like an answer
    if unanswered[0] == "confirm":
        speak(f"Sorry, I didn't catch that. Should I {unanswered[1]}? Say yes or no.")
    else:
        speak("Sorry, which one did you mean?")
    return "command"


def _dispatch(query, allow_chat=True):
    global _pending
    spoken = query.strip(STRIP)
    query = _bare(spoken)

    if QUIT.fullmatch(query):
        speak("See you later!")
        return False

    if FRESH.fullmatch(query):
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

    for step in STEPS:
        resolved = step(query, spoken)
        if resolved:
            return resolved

    # A fresh order abandons an unanswered menu. Without this a menu nobody wanted to answer
    # sat there swallowing every following command with "which one did you mean?", and the
    # only way out was to answer a question the user had already moved on from.
    if unanswered is not None and not query.startswith(VERBS) and not QUESTION.match(query):
        return _reask(unanswered)

    if not allow_chat:
        return "unhandled"
    # everything the patterns didn't catch goes to the agent, which has the tools and can
    # both act and talk — so an unmatched phrasing is a conversation, not a dead end
    agent.respond(spoken)
    return "chat"


def _remember_local_command(query):
    """Give a later AI follow-up the outcome of an instant, non-AI command."""
    detail = f"The active app is {context.app}." if context.app else "The local command completed."
    agent.remember_local_turn(query, detail)
