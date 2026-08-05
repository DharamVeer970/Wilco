import speech_recognition as sr
from huggingface_hub import InferenceClient

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


def calibrate(source, seconds=1.0):
    global _calibrated
    if not _calibrated:
        r.adjust_for_ambient_noise(source, duration=seconds)
        _calibrated = True


def takeCommand():
    global _calibrated
    try:
        with sr.Microphone() as source:
            calibrate(source)
            print("Listening...")
            audio = r.listen(source, timeout=config.LISTEN_TIMEOUT,
                             phrase_time_limit=config.MAX_PHRASE_SECONDS)
    except sr.WaitTimeoutError:
        _calibrated = False  # heard nothing at all, so the room's noise floor has moved
        return ""
    except Exception as e:
        print("Error while listening:", e)
        return ""

    print("Recognizing...")
    try:
        query = hf.automatic_speech_recognition(audio.get_wav_data(), model=stt_model).text
    except Exception as e:
        print("Speech recognition failed:", e)
        speak("I didn't catch that.")  # say it, or a dead API just looks like deafness
        return ""
    print(f"User said: {query}")
    return query.strip().lower()
