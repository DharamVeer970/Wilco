import io
import math
import time
import wave

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
from config import hf_token, stt_model
from windows.voice import speak

r = sr.Recognizer()
r.pause_threshold = config.PAUSE_SECONDS
# how much silence is kept on each end of the clip, not what ends it — it must stay below
# pause_threshold or speech_recognition trims audio it hasn't finished collecting
r.non_speaking_duration = min(0.5, config.PAUSE_SECONDS / 2)
r.phrase_threshold = config.MIN_PHRASE_SECONDS
r.dynamic_energy_threshold = True

hf = InferenceClient(
    api_key=hf_token, provider="hf-inference",
    headers={"Content-Type": "audio/wav"}, timeout=30,  # else a cold model hangs the loop
)
_calibrated = False
_backend = None


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
                           dtype="int16") as stream:
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
                with sr.Microphone() as source:
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
        _calibrated = False  # heard nothing at all, so the room's noise floor has moved
        return ""
    except Exception as e:
        print("Error while listening:", e)
        return ""

    print("Recognizing...")
    try:
        query = hf.automatic_speech_recognition(wav_data, model=stt_model).text
    except Exception as e:
        print("Speech recognition failed:", e)
        speak("I didn't catch that.")  # say it, or a dead API just looks like deafness
        return ""
    print(f"User said: {query}")
    return query.strip().lower()
