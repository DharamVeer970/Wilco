import io
import math
import time
import wave
import base64

import requests

try:
    import audioop  # C-speed RMS; present via audioop-lts on Python 3.13+/3.14 (SpeechRecognition's dep)
except ImportError:
    audioop = None

import speech_recognition as sr
from huggingface_hub import InferenceClient

try:
    import sounddevice as sd
except ImportError:
    sd = None

import config
from config import stt_language
from windows.voice import speak

r = sr.Recognizer()
r.pause_threshold = config.PAUSE_SECONDS
# how much silence is kept on each end of the clip, not what ends it — it must stay below
# pause_threshold or speech_recognition trims audio it hasn't finished collecting
r.non_speaking_duration = min(0.5, config.PAUSE_SECONDS / 2)
r.phrase_threshold = config.MIN_PHRASE_SECONDS
r.dynamic_energy_threshold = True

_calibrated = False
_backend = None
# The capture device to record from, matched by name against the system's own list. "" means
# whatever Windows has set as default, which is what the microphone has always used.
_device = ""
_SESSION = requests.Session()
_HF_CLIENTS: dict[str, InferenceClient] = {}


def _level(samples):
    """Root-mean-square loudness of 16-bit mono PCM audio."""
    if audioop is not None:
        return audioop.rms(samples, 2)  # one C call per block, not 1024 Python iterations
    values = memoryview(samples).cast("h")
    return math.sqrt(sum(sample * sample for sample in values) / max(1, len(values)))


def _wav(frames, sample_rate):
    """Package raw microphone frames as the WAV data Hugging Face expects."""
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(sample_rate)
        file.writeframes(b"".join(frames))
    return output.getvalue()


def _transcribe_openai_compatible(settings, wav_data):
    """Send WAV audio to any OpenAI-compatible transcription endpoint."""
    response = _SESSION.post(
        f"{settings['base_url']}/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings['api_key']}"},
        files={"file": ("speech.wav", wav_data, "audio/wav")},
        data={"model": settings["model"], "response_format": "json",
              **({"language": stt_language} if stt_language else {})},
        timeout=30,
    )
    if not response.ok:
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"STT provider returned HTTP {response.status_code}: {detail}")
    try:
        text = response.json().get("text", "")
    except ValueError as e:
        raise RuntimeError("STT provider returned invalid JSON") from e
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("STT provider returned an empty transcription")
    return text


def _transcribe_openrouter(settings, wav_data):
    """Use OpenRouter's documented JSON/base64 STT endpoint."""
    response = _SESSION.post(
        f"{settings['base_url']}/audio/transcriptions",
        headers={"Authorization": f"Bearer {settings['api_key']}", "Content-Type": "application/json"},
        json={"input_audio": {"data": base64.b64encode(wav_data).decode("ascii"), "format": "wav"},
              "model": settings["model"]},
        timeout=30,
    )
    if not response.ok:
        detail = response.text[:300].replace("\n", " ")
        raise RuntimeError(f"STT provider returned HTTP {response.status_code}: {detail}")
    try:
        text = response.json().get("text", "")
    except ValueError as e:
        raise RuntimeError("STT provider returned invalid JSON") from e
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("STT provider returned an empty transcription")
    return text


def _transcribe_hf(settings, wav_data):
    """Ask the Hugging Face Inference API for text, pinned to the configured language when set."""
    key = settings["api_key"]
    client = _HF_CLIENTS.get(key)
    if client is None:
        client = InferenceClient(
            api_key=key, provider="hf-inference",
            headers={"Content-Type": "audio/wav"}, timeout=30,
        )
        _HF_CLIENTS[key] = client
    kwargs = {"language": stt_language} if stt_language else {}
    return client.automatic_speech_recognition(wav_data, model=settings["model"], **kwargs).text


_TRANSPORTS = {
    "openai": _transcribe_openai_compatible,
    "openrouter": _transcribe_openrouter,
    "huggingface": _transcribe_hf,
}


def _transcribe(wav_data):
    """Try each configured provider in order; the first one that answers wins."""
    failures = []
    for index, settings in enumerate(config.STT_CHAIN):
        if not settings["api_key"]:
            print(f"STT: {settings['provider']} skipped — no {settings['key_env']} key set.")
            continue
        try:
            return _TRANSPORTS[settings["transport"]](settings, wav_data)
        except Exception as error:
            failures.append(f"{settings['provider']}: {error}")
            print(f"STT: {settings['provider']} failed ({error}).")
            following = [entry for entry in config.STT_CHAIN[index + 1:] if entry["api_key"]]
            if following:
                print(f"STT: falling back to {following[0]['provider']}.")
    raise RuntimeError("every speech provider failed — " + " | ".join(failures))


def _recognition_error_message(error):
    """A useful spoken recovery hint for the common provider-side failures."""
    detail = str(error).lower()
    if "every speech provider failed" in detail:
        return ("Every speech provider failed just now. Check your internet connection and the "
                "speech API keys in your configuration, then try again.")
    if "429" in detail or "rate limit" in detail:
        return "The speech provider's limit is busy right now. Please wait a moment and try again."
    if "401" in detail or "403" in detail or "api key" in detail:
        return "The speech service key needs attention. Check the STT provider settings in your configuration."
    if "402" in detail or "credit" in detail or "quota" in detail:
        return "The speech service quota is unavailable. Use local Whisper or add provider credit."
    return "I didn't catch that."


# Whisper invents lines like these out of silence, room noise, and Wilco's own voice coming back
# through the speakers — usually in a language nobody in the room is speaking. They arrive looking
# exactly like commands, so a quiet moment put "Thank you." and "Спасибо." in the queue ahead of
# the real request and Wilco answered those instead, minutes late. Matched as whole utterances
# only, never as a phrase inside one: "thank you for opening the file" is a real sentence.
NOISE = {
    "thank you", "thanks", "thanks a lot", "thank you very much", "thanks for watching",
    "thank you for watching", "please subscribe", "subscribe", "like and subscribe",
    "you", "okay", "hmm", "спасибо", "спасибо за просмотр", "продолжение следует",
    "подписывайтесь", "það er það", "takk fyrir", "sous-titres", "abonnez-vous", "amaraorg",
    "ご視聴ありがとうございました", "धन्यवाद", "सदस्यता लें", "gracias", "شكرا",
}


def _is_noise(text):
    """True when a transcription is one of the recogniser's own inventions, not something said.

    Punctuation, case and spacing are ignored; everything else has to match exactly, so a real
    sentence that happens to contain "thank you" is still a command.
    """
    plain = "".join(ch for ch in (text or "").casefold() if ch.isalnum() or ch.isspace())
    return " ".join(plain.split()) in ("", *NOISE)


def _match(names, wanted):
    """The first of `names` containing `wanted`, case-insensitively. None if nothing matches."""
    needle = (wanted or "").strip().lower()
    if not needle:
        return None
    return next((name for name in names if needle in str(name).lower()), None)


def use_device(spec):
    """Record from a named device instead of the system default.

    The name comes from the browser's settings screen, because a browser device id is an opaque
    per-origin hash that means nothing on this side. Sounddevice and PyAudio each keep their own
    device list and their own indices, so the name is what is stored — and matched again for
    whichever backend ends up recording.

    Returns the name it settled on. "" means the system default, either because none was asked for
    or because nothing matched it.
    """
    global _device
    wanted = (spec or "").strip()
    if not wanted:
        _device = ""
        return _device
    if sd is None:
        _device = wanted
        return _device
    try:
        matched = _match([d["name"] for d in sd.query_devices()], wanted)
    except Exception:
        matched = None
    # An unmatched name is kept as given: sounddevice matches substrings itself, and its device
    # list can legitimately be empty until the audio service is up.
    _device = matched or wanted
    return _device


def current_device():
    """The capture device the microphone is pointed at. "" means the system default."""
    return _device


def _pyaudio_index():
    """The chosen device's index in SpeechRecognition's list, which is not sounddevice's.

    The name is matched a second time rather than reusing an index, because the two backends
    enumerate the same hardware in a different order — handing one list's index to the other would
    quietly record from the wrong device, which is worse than ignoring the choice.
    """
    if not _device:
        return None
    try:
        names = sr.Microphone.list_microphone_names()
    except Exception:
        return None
    for index, name in enumerate(names):
        if _device.lower() in str(name).lower():
            return index
    return None


def _listen_with_sounddevice():
    """Record one spoken phrase without PyAudio, using sounddevice's Windows backend."""
    if sd is None:
        raise RuntimeError("No microphone backend is installed. Run: python -m pip install -r requirements.txt")

    sample_rate, block_size = 16_000, 1_024
    silence_limit = int(config.PAUSE_SECONDS * sample_rate / block_size)
    start_deadline = time.monotonic() + config.LISTEN_TIMEOUT
    phrase_deadline = time.monotonic() + config.MAX_PHRASE_SECONDS
    threshold = max(250, r.energy_threshold)
    frames, started, quiet_blocks = [], False, 0

    with sd.RawInputStream(samplerate=sample_rate, blocksize=block_size, channels=1,
                           dtype="int16", device=_device or None) as stream:
        while time.monotonic() < phrase_deadline:
            block, overflowed = stream.read(block_size)
            if overflowed:
                continue
            loud = _level(block) >= threshold
            if not started:
                if loud:
                    started = True
                    frames.append(block)
                elif time.monotonic() >= start_deadline:
                    raise sr.WaitTimeoutError("listening timed out while waiting for phrase to start")
                continue
            frames.append(block)
            quiet_blocks = 0 if loud else quiet_blocks + 1
            if quiet_blocks >= silence_limit:
                break

    if len(frames) * block_size / sample_rate < config.MIN_PHRASE_SECONDS:
        raise sr.WaitTimeoutError("phrase was too short")
    return _wav(frames, sample_rate)


def calibrate(source, seconds=1.0):
    global _calibrated
    if not _calibrated:
        r.adjust_for_ambient_noise(source, duration=seconds)
        _calibrated = True


def take_command():
    global _backend, _calibrated
    try:
        if _backend != "sounddevice":
            try:
                with sr.Microphone(device_index=_pyaudio_index()) as source:
                    calibrate(source)
                    print("Listening...")
                    audio = r.listen(source, timeout=config.LISTEN_TIMEOUT,
                                     phrase_time_limit=config.MAX_PHRASE_SECONDS)
                    wav_data = audio.get_wav_data()
                _backend = "pyaudio"
            except AttributeError as e:
                # SpeechRecognition only imports PyAudio when Microphone() is constructed.
                if "PyAudio" not in str(e):
                    raise
                _backend = "sounddevice"
                print("PyAudio is unavailable; using sounddevice instead.")
        if _backend == "sounddevice":
            print("Listening...")
            wav_data = _listen_with_sounddevice()
    except sr.WaitTimeoutError:
        return ""
    except Exception as e:
        print("Error while listening:", e)
        time.sleep(1.0)
        return ""

    print("Recognizing...")
    try:
        query = _transcribe(wav_data)
    except Exception as e:
        print("Speech recognition failed:", e)
        speak(_recognition_error_message(e))
        return ""
    if _is_noise(query):
        # Silence, a fan, or Wilco's own reply through the speakers. Queueing it would make the
        # next real command wait behind a question nobody asked.
        print(f"Heard {query!r} — the recogniser filling a silence, ignoring it.")
        return ""
    print(f"User said: {query}")
    return query.strip().lower()
