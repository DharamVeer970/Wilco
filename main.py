"""Wilco's own front door: the microphone, feeding one worker that also serves the frontend.

Two threads and one queue. The worker owns handle(), so a browser tab and the microphone can
never run commands at the same time — the pending question, the context and the conversation are
module state with no lock, and interleaving them would answer one request with another's
question. It is also the thread that speaks, which is what keeps the alternation the voice engine
relies on.

The listener only ever records. It stays quiet while Wilco is talking, and it drops a phrase that
overlapped a reply, because speak() blocks the worker rather than the listener now: without that
check the microphone would hear Wilco's own voice through the speakers and queue it as the next
command, forever.
"""
import logging
import sys
import threading
import time

import config
import events
from core.commands import submit, work
from windows import voice
from windows.speech import speak, take_command

if sys.platform != "win32":
    # Fail here, clearly, rather than letting a win32com/ctypes import crash cryptically.
    sys.exit("Wilco drives Windows (win32com, ctypes, ms-settings) and can't run on "
             f"{sys.platform!r}. Use Windows 10 or 11.")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

class _ComtypesFilter(logging.Filter):
    """Filter out noisy comtypes client cache messages."""

    def filter(self, record):
        return "comtypes.client._code_cache" not in record.name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("wilco.log", encoding="utf-8"),
              logging.StreamHandler()],
)
logging.getLogger().addFilter(_ComtypesFilter())
logging.getLogger("comtypes.client._code_cache").addFilter(_ComtypesFilter())
log = logging.getLogger("wilco")


def _thread_died(args):
    """A thread that ends on an exception says which one, in wilco.log, instead of on the console.

    Wilco runs the microphone, the frontend, the greeting and the voice engine on their own
    threads, and a bare traceback from one of them — "Traceback (most recent call last):" and
    nothing else — gives no clue which part of the program raised it, or what it was doing. This
    puts the thread's name beside it and writes the whole thing where the scrollback can't lose it.
    """
    name = getattr(args.thread, "name", "?")
    log.error("thread %s died: %r", name, args.exc_value,
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


threading.excepthook = _thread_died


def _listen_forever():
    """Queue one utterance at a time, and never queue Wilco's own voice."""
    while True:
        try:
            if voice.is_speaking():
                time.sleep(0.3)
                continue
            before = voice.spoken_count()
            events.emit("state", value="listening")
            query = take_command()
            # A phrase recorded while Wilco was talking is Wilco coming back through the speakers,
            # and once it is text there is no way to tell it from the user. Dropping it here is what
            # stops a reply being heard as the next command, over and over.
            if voice.spoken_count() != before:
                continue
            if query:
                submit(query)
        except Exception as e:
            log.warning("Listener loop exception: %s", e)
            time.sleep(1.0)


def _terminal_loop():
    """Allow typing commands directly into the terminal while listening on the mic."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if line:
                submit(line)
        except Exception:
            break


def _serve_frontend():
    """Start the browser frontend, if it is switched on. Never fatal — voice still works."""
    if not config.UI_ENABLED:
        return
    try:
        import frontend_server
        frontend_server.serve_in_background(config.UI_HOST, config.UI_PORT)
        log.info("frontend on http://%s:%s", config.UI_HOST, config.UI_PORT)
    except Exception as e:
        log.warning("frontend not started: %s", e)


def main():
    """Run Wilco until the user says goodbye. Returns the process exit code."""
    log.info("Wilco starting")
    _serve_frontend()

    banner = (
        "\n===============================================================\n"
        "  Wilco AI is ONLINE\n"
        f"  Web Interface: http://{config.UI_HOST}:{config.UI_PORT}\n"
        "  Microphone:    Listening for voice commands...\n"
        "  Terminal:      Type any command here and press Enter\n"
        "===============================================================\n"
    )
    print(banner)

    # Greet in background so startup and web server are instantly responsive
    def _greet():
        try:
            speak("Welcome to Wilco AI")
        except Exception as e:
            log.warning("Initial greeting failed: %s", e)

    threading.Thread(target=_greet, daemon=True, name="wilco-greeting").start()
    threading.Thread(target=_listen_forever, daemon=True, name="wilco-listener").start()
    threading.Thread(target=_terminal_loop, daemon=True, name="wilco-terminal").start()

    # Blocks here until someone says goodbye, which is also the only way out of the process.
    work()
    log.info("Wilco stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
