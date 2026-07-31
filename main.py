import sys

from core.commands import handle
from windows.speech import speak, takeCommand

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if __name__ == "__main__":
    print("Welcome to Jarvis A.I")
    speak("Welcome to Jarvis AI")

    while True:
        query = takeCommand()
        if not query:
            continue
        try:
            if not handle(query):
                break
        except Exception as e:  # one bad command shouldn't take the assistant down
            print("Error:", e)
            speak("Something went wrong with that one.")
