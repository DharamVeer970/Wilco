"""How Wilco sounds: Edge neural voices, with the built-in Windows voice as the backup.

Windows only ships David and Zira, and they sound like a 2003 satnav — one flat pace, one
flat tone, no way to make either interesting. Edge's neural voices are the ones Read Aloud
and Copilot speak with: free, no key, three hundred of them. A dozen are exposed here as
voice packs that can be switched mid-conversation, and the two local ones stay on the list
because they need no network and start instantly.

Two things make it feel quick rather than merely pleasant. Speed is a percentage on top of
the voice's own pace, because these voices are tuned for audiobooks and a conversation wants
about a quarter faster. And a reply is synthesised group-of-sentences at a time, in the
background, while the previous group is already playing — so Wilco starts talking after the
first short group instead of after the whole paragraph. Short lines it says a lot ("Volume
up.") are cached on disk, so the second time they come out with no wait at all.

WILCO_VOICE and WILCO_SPEED in .env decide where it starts. Switching by voice lasts the
session and is deliberately not written anywhere: .env is the one place settings live, and a
second file that quietly outranked it was only ever confusing.
"""
import asyncio
import ctypes
import hashlib
import itertools
import os
import queue
import re
import tempfile
import threading
import time

import pythoncom
import win32com.client
from rapidfuzz import fuzz, process

import config
import events

try:
    import edge_tts
except ImportError:
    edge_tts = None

VOICES = {
    "ava": ("en-US-AvaMultilingualNeural", "American, female, warm and natural"),
    "andrew": ("en-US-AndrewMultilingualNeural", "American, male, relaxed and easy"),
    "emma": ("en-US-EmmaMultilingualNeural", "American, female, bright and light"),
    "brian": ("en-US-BrianMultilingualNeural", "American, male, deep and calm"),
    "sonia": ("en-GB-SoniaNeural", "British, female, crisp"),
    "ryan": ("en-GB-RyanNeural", "British, male, dry"),
    "neerja": ("en-IN-NeerjaNeural", "Indian English, female"),
    "prabhat": ("en-IN-PrabhatNeural", "Indian English, male"),
    "natasha": ("en-AU-NatashaNeural", "Australian, female"),
    "madhur": ("hi-IN-MadhurNeural", "Hindi, male"),
    "swara": ("hi-IN-SwaraNeural", "Hindi, female"),
    "david": ("sapi:Microsoft David", "Built-in Windows male, robotic but instant and offline"),
    "zira": ("sapi:Microsoft Zira", "Built-in Windows female, robotic but instant and offline"),
}
LOCAL = "sapi:"
SLOWEST, FASTEST = -50, 100  # what the voice service itself accepts, not a preference

CACHE = os.path.join(tempfile.gettempdir(), "wilco_tts")
SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]*")

_serial = itertools.count()
_local = threading.local()
_speech_lock = threading.RLock()
_last_spoken = ("", float("-inf"))
# Up while audio is playing. speak() blocks, so the microphone normally cannot hear Wilco talk
# because there is only one thread; the frontend added a second one for commands, and this is
# what keeps that new thread from recording Wilco's own voice back into the mic.
_busy = threading.Event()
# Counts lines spoken this session. A listener that starts recording just before Wilco begins
# talking cannot catch that with _busy — it is already recording — so it compares this before and
# after instead, and drops a phrase that overlaps a reply rather than queueing the reply as the
# next command, over and over.
_spoken = 0
# Set by stop() to abort an in-progress reply. Checked by both _speak_local (SAPI) and
# _play (MCI) so a user can cut Wilco off mid-sentence from the UI or by voice.
_stop_event = threading.Event()


def _sapi():
    """The Windows voice for THIS thread — SAPI is apartment-threaded, so a shared object
    raises or goes quiet when a reminder fires off its own timer thread."""
    if not hasattr(_local, "sapi"):
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        _local.sapi = win32com.client.Dispatch("SAPI.SpVoice")
    return _local.sapi


def _clamp(speed):
    return max(SLOWEST, min(FASTEST, int(speed)))


def _count_line():
    global _spoken
    _spoken += 1


_state = {"voice": config.VOICE if config.VOICE in VOICES else "ava",
          "speed": _clamp(config.SPEED)}


def current():
    """The voice in use, as (name, id, description, speed)."""
    name = _state["voice"]
    voice_id, description = VOICES[name]
    return name, voice_id, description, _state["speed"]


def is_speaking():
    """True while a line is being played aloud."""
    return _busy.is_set()


def spoken_count():
    """How many lines have been spoken — a listener compares this to spot its own echo."""
    return _spoken


def use(name):
    """Switch voice pack. Returns the name switched to, or None if there's no such voice.

    Switching to the voice already in use announces nothing. The frontend mirrors every voice
    event back to this machine as a settings save, so re-announcing a voice it already has
    would bounce that save straight back here as another event, forever — a page left open was
    enough to pin a core and make the whole machine crawl.
    """
    chosen = resolve(name)
    if chosen and chosen != _state["voice"]:
        _state["voice"] = chosen
        name, voice_id, description, speed = current()
        events.emit("voice", name=name, id=voice_id, description=description, speed=speed)
    return chosen


def set_speed(percent):
    """Set the talking pace as a percentage of normal. Returns what it settled on."""
    try:
        _state["speed"] = _clamp(percent)
    except (TypeError, ValueError):
        pass
    events.emit("speed", value=_state["speed"])
    return _state["speed"]


CHARACTER_VOICE_ALIASES = {
    # Female
    "ava": "ava",
    "aoede": "ava",
    "luna": "ava",
    "swara": "swara",      # Hindi female
    "hindi female": "swara",
    "neerja": "neerja",    # Indian English female
    "blaze": "sonia",      # Bold female
    "fenrir": "sonia",
    "iris": "emma",
    "kore": "emma",
    "leda": "neerja",
    "athena": "neerja",
    "natasha": "natasha",
    "zephyr": "natasha",
    "aria": "natasha",
    # Male
    "madhur": "madhur",    # Hindi male
    "hindi male": "madhur",
    "prabhat": "prabhat",  # Indian English male
    "brian": "brian",      # Deep male
    "charon": "brian",
    "erebus": "brian",
    "andrew": "andrew",    # Youthful male
    "puck": "andrew",
    "spark": "andrew",
    "ryan": "ryan",
    "david": "david",
}


# The words people put around a voice name — "switch your voice TO the SWARA voice". Stripped from
# both sides before anything is compared, so a sentence can be handed over whole.
VOICE_FILLER = re.compile(
    r"\b(?:change|switch|set|use|pick|make|put|speak|talk|speaking|talking|say|saying|"
    r"voices?|packs?|your|my|the|a|an|of|for|to|as|in|into|like|is|named|called|"
    r"please|now|wilco|sounds?|me|it|one|ones|that|this|instead|any|some)\b")
# How close a spoken name has to be before it is taken as that voice, without asking again.
# Deliberately strict: at 65 "sora" is as close to sonia as it is to swara, and a voice nobody
# asked for is worse than one short question. See candidates() for the ones that fall short.
CONFIDENT = 80


def _voice_words(name):
    """The words of a spoken voice request that could be a name: "change it to swara" -> "swara"."""
    plain = re.sub(r"[^\w\s]", " ", str(name or "").lower())
    return " ".join(word for word in VOICE_FILLER.sub(" ", plain).split() if len(word) > 1)


def spoken_name(name):
    """What the user actually called the voice, once the words around it are gone.

    "the swara voice" -> "swara". Public so a caller can tell a name it recognised from one it had
    to guess at, and say which one it settled on.
    """
    return _voice_words(name)


def candidates(name, limit=3, cutoff=60):
    """Voice packs a spoken name might have meant, best first — for asking instead of guessing.

    Kept apart from resolve() because "close enough to offer" and "close enough to act on" are not
    the same thing: "swadha" has one plausible reading, "sora" has two.
    """
    wanted = _voice_words(name)
    if not wanted:
        return []
    scored = [(pack, max(fuzz.ratio(wanted, pack),
                         fuzz.partial_ratio(wanted, pack) if len(wanted) > len(pack) else 0))
              for pack in VOICES]
    # sorted() is stable, so equally close packs keep the order the list has always been read in
    return [pack for pack, score in sorted(scored, key=lambda pair: -pair[1])
            if score >= cutoff][:limit]


def resolve(name):
    """The voice pack a name means — by pack name, by avatar name, by accent, or near enough."""
    wanted = str(name or "").strip().lower()
    if wanted in CHARACTER_VOICE_ALIASES:
        return CHARACTER_VOICE_ALIASES[wanted]
    if wanted in VOICES:
        return wanted
    spoken = _voice_words(wanted)
    if not spoken:
        return None
    if spoken in CHARACTER_VOICE_ALIASES:
        return CHARACTER_VOICE_ALIASES[spoken]
    if spoken in VOICES:
        return spoken
    labels = {pack: _voice_words(f"{pack} {voice_id} {description}")
              for pack, (voice_id, description) in VOICES.items()}
    by_label = next((pack for pack, label in labels.items() if spoken in label), None)
    if not by_label:
        # "a British accent", "something warm": one word of it naming a kind of voice is enough.
        by_label = next((pack for word in spoken.split() if len(word) > 3
                         for pack, label in labels.items() if word in label), None)
    if by_label:
        return by_label
    options = {pack: pack for pack in VOICES}
    options.update(CHARACTER_VOICE_ALIASES)  # avatar names the frontend sends ("blaze", "kore")
    best = process.extractOne(spoken, options, scorer=fuzz.ratio, score_cutoff=CONFIDENT)
    return options[best[2]] if best else None


def speak(text):
    text = (text or "").strip()
    if not text:
        return
    # Replies can arrive at the same time from a command, an agent, or a reminder thread.
    # Serialise audio playback and suppress an immediate identical replay; this fixes doubled
    # speech without discarding distinct messages that happen to arrive close together.
    global _last_spoken
    fingerprint = " ".join(text.casefold().split())
    with _speech_lock:
        previous, finished_at = _last_spoken
        if (fingerprint == previous
                and time.monotonic() - finished_at < config.SPEECH_DEDUP_SECONDS):
            print(f"Wilco: duplicate reply suppressed: {text}")
            return
        print(f"Wilco: {text}")
        # Every spoken line in the program passes through here — an instant command, an agent
        # reply, a reminder and a failure notice alike — so this is the one place the UI can be
        # told what was said without any of those callers having to remember to tell it.
        events.emit("transcript", role="assistant", text=text, voice=_state["voice"])
        events.emit("speak", phase="start", voice=_state["voice"], text=text)
        events.emit("state", value="speaking")
        _busy.set()
        _count_line()
        try:
            voice_id = VOICES[_state["voice"]][0]
            if edge_tts is None or voice_id.startswith(LOCAL):
                _speak_local(text, voice_id)
            else:
                _speak_neural(text, voice_id)
        except Exception as e:
            # The user is waiting for a line, not for a stack trace: a synthesis that fails (no
            # network, a stalled voice, a clip Windows refuses to play) is said by the built-in
            # Windows voice instead, so the turn still ends in words.
            print(f"voice: {_state['voice']} failed to speak ({e}) — using the Windows voice.")
            try:
                _speak_local(text, LOCAL)
            except Exception as fallback:
                print("voice: the built-in Windows voice failed too:", fallback)
        finally:
            _busy.clear()
            events.emit("speak", phase="end", voice=_state["voice"])
            events.emit("state", value="idle")
            _last_spoken = (fingerprint, time.monotonic())


def _speak_local(text, voice_id=LOCAL):
    """Say it with the built-in Windows voice — no network, no wait, no charm."""
    sapi = _sapi()
    sapi.Rate = max(-10, min(10, round(_state["speed"] / 12)))
    wanted = voice_id.split(":", 1)[-1].lower()
    for token in sapi.GetVoices():
        if wanted and wanted in token.GetDescription().lower():
            sapi.Voice = token
            break
    sapi.Speak(text)


def _speak_neural(text, voice_id):
    """Play each group as it lands, while the next one is still being made."""
    groups = _groups(text)
    ready = queue.Queue()
    rate = f"{_state['speed']:+d}%"
    threading.Thread(target=_synthesise, args=(groups, voice_id, rate, ready),
                     daemon=True).start()
    for i, group in enumerate(groups):
        made = ready.get()
        if made is None:
            _speak_local(" ".join(groups[i:]))
            return
        # A group is one spoken breath. Telling the UI where each one begins is what lets the
        # avatar's mouth move with the sentence instead of at some unrelated rhythm.
        events.emit("speak", phase="chunk", voice=voice_id, index=i, total=len(groups),
                    text=group)
        _play(*made)


def _synthesise(groups, voice_id, rate, ready):
    gave_up = False
    for group in groups:
        if gave_up:
            # The network already failed: don't keep hanging on it, just read the rest
            # out loud on the built-in Windows voice.
            ready.put(None)
            continue
        try:
            try:
                ready.put(_download(group, voice_id, rate))
            except Exception as e:
                # A single stalled chunk shouldn't drop the neural voice for the whole turn.
                print("neural voice stalled, retrying once:", e)
                ready.put(_download(group, voice_id, rate))
        except Exception as e:
            print("neural voice unavailable, reading the rest locally:", e)
            ready.put(None)
            gave_up = True


def _download(text, voice_id, rate):
    """Fetch one group as mp3. Returns (path, keep) — cached clips are never deleted."""
    os.makedirs(CACHE, exist_ok=True)
    keep = len(text) <= config.SPEECH_CACHEABLE
    if keep:
        key = hashlib.md5(f"{voice_id}|{rate}|{text}".encode("utf-8"),
                          usedforsecurity=False).hexdigest()
        path = os.path.join(CACHE, f"{key}.mp3")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path, True
    else:
        path = os.path.join(CACHE, f"say{os.getpid()}_{next(_serial)}.mp3")
    audio = asyncio.run(_stream(text, voice_id, rate))
    if not audio:
        raise OSError(f"{voice_id} returned no audio")
    partial = f"{path}.{os.getpid()}.part"
    with open(partial, "wb") as f:
        f.write(audio)
    os.replace(partial, path)
    return path, keep


async def _stream(text, voice_id, rate):
    speech = edge_tts.Communicate(text, voice_id, rate=rate,
                                  connect_timeout=4, receive_timeout=10)
    return b"".join([p["data"] async for p in speech.stream() if p["type"] == "audio"])


def _play(path, keep):
    mci = ctypes.windll.winmm.mciSendStringW
    alias = f"wilco{os.getpid()}x{next(_serial)}"
    if mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None) == 0:
        mci(f"play {alias} wait", None, 0, None)
        mci(f"close {alias}", None, 0, None)
    if not keep:
        try:
            os.remove(path)
        except OSError:
            pass


def _warm():
    """Pay the first-connection cost now, not while somebody is waiting to be answered."""
    voice_id = VOICES[_state["voice"]][0]
    if edge_tts is None or voice_id.startswith(LOCAL):
        return
    try:
        _download("Ready.", voice_id, f"{_state['speed']:+d}%")
    except Exception:
        pass


def _groups(text):
    """Sentence groups, the first deliberately short so the talking starts sooner."""
    groups, current_group, limit = [], "", config.SPEECH_FIRST_GROUP
    for sentence in SENTENCE.findall(text):
        if (len(current_group) >= config.SPEECH_LEAST_GROUP
                and len(current_group) + len(sentence) > limit):
            groups.append(current_group.strip())
            current_group, limit = sentence, config.SPEECH_LATER_GROUP
        else:
            current_group += sentence
    groups.append(current_group.strip())
    return [g for g in groups if re.search(r"\w", g)] or [text]


threading.Thread(target=_warm, daemon=True).start()
