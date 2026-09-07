import logging
import sys
from core.commands import handle
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


if __name__ == "__main__":
    log.info("Wilco starting")
    print("Welcome to Wilco AI")
    speak("Welcome to Wilco AI")

    # MCP servers are loaded via plugins/plugin_mcp.py when WILCO_PLUGINS_ENABLED=1

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
