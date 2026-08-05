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

import pythoncom
import win32com.client
from rapidfuzz import fuzz, process

import config

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


_state = {"voice": config.VOICE if config.VOICE in VOICES else "ava",
          "speed": _clamp(config.SPEED)}


def current():
    """The voice in use, as (name, id, description, speed)."""
    name = _state["voice"]
    voice_id, description = VOICES[name]
    return name, voice_id, description, _state["speed"]


def use(name):
    """Switch voice pack. Returns the name switched to, or None if there's no such voice."""
    chosen = _resolve(name)
    if chosen:
        _state["voice"] = chosen
    return chosen


def set_speed(percent):
    """Set the talking pace as a percentage of normal. Returns what it settled on."""
    try:
        _state["speed"] = _clamp(percent)
    except (TypeError, ValueError):
        pass
    return _state["speed"]


def _resolve(name):
    """Match what was said to a voice pack — by name, by accent, or near enough."""
    wanted = str(name or "").strip().lower()
    if wanted in VOICES:
        return wanted
    if not wanted:
        return None
    labels = {n: f"{n} {i} {d}".lower() for n, (i, d) in VOICES.items()}
    spoken_id = next((n for n, label in labels.items() if wanted in label), None)
    if spoken_id:
        return spoken_id
    best = process.extractOne(wanted, labels, scorer=fuzz.token_set_ratio, score_cutoff=60)
    return best[2] if best else None


def speak(text):
    print(f"Wilco: {text}")
    text = (text or "").strip()
    if not text:
        return
    voice_id = VOICES[_state["voice"]][0]
    if edge_tts is None or voice_id.startswith(LOCAL):
        _speak_local(text, voice_id)
    else:
        _speak_neural(text, voice_id)


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
        _play(*made)


def _synthesise(groups, voice_id, rate, ready):
    for group in groups:
        try:
            ready.put(_download(group, voice_id, rate))
        except Exception as e:
            print("Neural voice unavailable, falling back to the Windows one:", e)
            ready.put(None)
            return


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
                                  connect_timeout=5, receive_timeout=20)
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
