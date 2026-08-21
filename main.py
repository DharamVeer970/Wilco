import logging
import sys

if sys.platform != "win32":
    # Fail here, clearly, rather than letting a win32com/ctypes import crash cryptically.
    sys.exit("Wilco drives Windows (win32com, ctypes, ms-settings) and can't run on "
             f"{sys.platform!r}. Use Windows 10 or 11.")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# One bad command shouldn't take the assistant down, but it also shouldn't vanish: every
# failure lands in wilco.log next to main.py, with the full traceback, so a crash that
# happened while nobody was watching is still diagnosable afterwards.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("wilco.log", encoding="utf-8"),
              logging.StreamHandler()],
)
log = logging.getLogger("wilco")

from core.commands import handle
from windows.speech import speak, take_command

if __name__ == "__main__":
    log.info("Wilco starting")
    print("Welcome to Wilco AI")
    speak("Welcome to Wilco AI")

    while True:
        query = take_command()
        if not query:
            continue
        try:
            if not handle(query):
                break
        except Exception:
            log.exception("command failed: %r", query)
            speak("Something went wrong with that one.")
