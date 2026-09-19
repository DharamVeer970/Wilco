"""The browser's door into Wilco: the built frontend, an event stream, and a command box.

Wilco already has a front door — main.py, the microphone — and a machine-facing one over
JSON-RPC, mcp_server.py. This is the human-facing one, and it is deliberately the same shape: a
second way in, not a second brain. A command typed here goes into the same queue a spoken one
does, so the same thread runs it, the same conversation answers it, and a parked confirmation is
answered by a click or by a word with no difference between the two.

stdlib only, on purpose. Wilco needs no web framework, and requiring one would mean the browser
tab could not work until somebody installed it. ThreadingHTTPServer plus Server-Sent Events is
plenty for a stream that only ever flows one way — state, transcript, tool results — with a POST
back for the occasional command.

    python frontend_server.py      the UI on its own: a command box with no microphone
    python main.py                 the UI and the microphone, one queue and one conversation

It binds to loopback because the tools behind it drive the whole machine. See _same_origin() for
the other half of that argument.
"""
import datetime
import hashlib
import json
import mimetypes
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import config
import events
# Imported here rather than inside the handlers on purpose: loading this graph costs seconds the
# first time (controlling Comtypes and UIAutomation especially), and paying it inside a request
# thread would stall the very first command a user typed, or worse, load COM on a thread that
# never asked for it. Everything the bridge needs is therefore already loaded by the time the
# socket opens, and a handler only ever queues and answers.
from core import commands
from mcp_tool import TOOLS, gate
from windows import speech, voice

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "Frontend" / "dist"
# Long enough that a quiet stream is still visibly alive.
HEARTBEAT = 15.0
LOOPBACK = ("localhost", "127.0.0.1", "[::1]", "::1")

INDEX_HTML = "index.html"
NOT_FOUND = "not found"
ASSETS_PREFIX = "assets/"

# Windows resolves some of these through the registry, and .js lands on text/plain often enough
# to break an ES module import. The build's own file types are stated here instead of guessed.
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
         ".webm": "video/webm", ".mp4": "video/mp4", ".svg": "image/svg+xml",
         ".woff2": "font/woff2", ".json": "application/json", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
         ".ico": "image/x-icon", ".woff": "font/woff", ".ttf": "font/ttf"}


def _iso_now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _memory_id(text):
    """A stable id for a remembered line, so the dashboard can delete the one it is showing."""
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _mic_running():
    """Whether the microphone loop from main.py is up in this process.

    The frontend can be started on its own, and then it must not claim Wilco is listening for a
    voice that nothing is recording.
    """
    return any(t.name == "wilco-listener" and t.is_alive() for t in threading.enumerate())


def _stored_at():
    """When memory was last written, as a real timestamp rather than a made-up one."""
    from core.memory import MEMORY_FILE
    try:
        return datetime.datetime.fromtimestamp(MEMORY_FILE.stat().st_mtime).isoformat(
            timespec="seconds")
    except OSError:
        return _iso_now()


def memories():
    """The things the user has told Wilco to remember, in the shape the dashboard expects.

    Wilco's durable memory is deliberately narrow: corrections and standing instructions, which
    are fed back into the system prompt on every turn. They are listed as preferences because
    that is exactly what they are — adding one here really does change how Wilco answers.
    """
    from core.learning import get_corrections
    when = _stored_at()
    return [{"id": _memory_id(text), "category": "preference", "text": text,
             "createdAt": when, "updatedAt": when}
            for text in get_corrections()]


def voices():
    """The voice packs, as the settings screen needs them."""
    return [{"name": name, "id": voice_id, "description": description}
            for name, (voice_id, description) in voice.VOICES.items()]


def _initial_state(speaking, listening):
    """Map the two live signals onto the one state string the UI draws."""
    if speaking:
        return "speaking"
    if listening:
        return "listening"
    return "idle"


def snapshot():
    """Everything the UI needs to draw itself on load, in one call."""
    name, voice_id, description, speed = voice.current()
    speaking = voice.is_speaking()
    listening = _mic_running()
    return {
        "state": _initial_state(speaking, listening),
        "voice": name,
        "voiceId": voice_id,
        "voiceDescription": description,
        "speed": speed,
        "platform": config.platform,
        "model": config.chat_model,
        "alwaysAct": config.ALWAYS_ACT,
        "mic": listening,
        "micDevice": speech.current_device(),
        "toolCount": len(TOOLS),
        "voices": voices(),
        "watchers": events.subscribers(),
    }


class _Handler(BaseHTTPRequestHandler):
    """One request per thread. The only long-lived one is the event stream."""

    protocol_version = "HTTP/1.1"
    server_version = "Wilco"

    # --------------------------------- sending ---------------------------------
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _chunk(self, data):
        """Frame one piece of an endless response by hand: it has no Content-Length to give."""
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii"))
        self.wfile.write(data + b"\r\n")
        self.wfile.flush()

    def _event(self, kind, payload):
        self._chunk(f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
                    .encode("utf-8"))

    # -------------------------------- receiving --------------------------------
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")) or {}
        except ValueError:
            # UnicodeDecodeError subclasses ValueError, so one clause covers both.
            return {}

    def _same_origin(self):
        """Refuse a request that some other web page made on the user's behalf.

        The tools behind this drive the whole machine, so a site the user happens to have open
        must not be able to POST a command here. A browser sends Origin on every cross-site
        request and cannot forge or hide it, so a mismatched one is a reliable refusal. No Origin
        at all means a local client — curl, or this app's own page.
        """
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = origin.split("://", 1)[-1].rstrip("/")
        if host == (self.headers.get("Host") or ""):
            return True
        # A dev server on this machine (vite on :5173, proxying here) is the user's own browser
        # talking to the user's own backend, which is the entire point of a dev server.
        return host.split(":")[0] in LOOPBACK

    def log_message(self, fmt, *args):
        """Stay quiet — this console belongs to the user, not to a web server."""

    # ---------------------------------- reading ----------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/events":
            return self._stream()
        if path == "/api/state":
            return self._send_json(snapshot())
        if path == "/api/voices":
            return self._send_json({"voices": voices()})
        if path == "/api/memories":
            return self._send_json(memories())
        return self._send_file(path)

    def _stream(self):
        """Everything that happens, as it happens, until the tab goes away.

        The recent past is replayed on connect, so a window opened — or reloaded mid-sentence —
        is caught up instead of starting blank.
        """
        token, inbox, missed = events.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self._event("snapshot", snapshot())
            for event in missed:
                self._event(event.get("kind", "event"), event)
            while True:
                try:
                    event = inbox.get(timeout=HEARTBEAT)
                except queue.Empty:
                    self._chunk(b": keep-alive\n\n")
                    continue
                self._event(event.get("kind", "event"), event)
        except OSError:
            pass  # the window was closed or reloaded, which is how most streams end
        finally:
            events.unsubscribe(token)
            try:
                self.wfile.write(b"0\r\n\r\n")  # the terminating chunk
            except OSError:
                pass

    def _not_found(self):
        return self._send_json({"error": NOT_FOUND}, 404)

    def _is_asset_request(self, clean):
        return clean.startswith(ASSETS_PREFIX) or any(clean.endswith(ext) for ext in TYPES)

    def _resolve_target(self, clean):
        """Map a URL path onto a file, with dev fallbacks. Returns None if outside root."""
        # Explicit traversal stays a 404 — never fall through to the SPA shell.
        if ".." in clean.split("/") or "\\" in clean:
            return None
        target = (DIST / clean).resolve()
        if not target.is_file() and clean.startswith(ASSETS_PREFIX):
            pub = (ROOT / "Frontend" / "public" / clean).resolve()
            if pub.is_file():
                target = pub
            else:
                raw_asset = (ROOT / "Frontend" / ASSETS_PREFIX[:-1] / clean[len(ASSETS_PREFIX):]).resolve()
                if raw_asset.is_file():
                    target = raw_asset
        try:
            target.relative_to((ROOT / "Frontend").resolve())
        except ValueError:
            return None
        if target.is_dir():
            target = target / INDEX_HTML
        if target.is_file():
            return target
        # Never send the SPA shell for a missing static asset (browser decode errors).
        if self._is_asset_request(clean):
            return None
        fallback = (DIST / INDEX_HTML)
        return fallback if fallback.is_file() else None

    def _parse_byte_range(self, file_size):
        """Parse the Range header. Returns (start, end), "unsatisfiable", or None."""
        header = self.headers.get("Range")
        if not header or not header.startswith("bytes="):
            return None
        try:
            first, _, last = header[6:].partition("-")
            start = int(first) if first else 0
            end = int(last) if last else file_size - 1
        except ValueError:
            return None
        if start < 0 or start >= file_size:
            return "unsatisfiable"
        return (start, min(end, file_size - 1))

    def _serve_range(self, target, kind, file_size, span):
        if span == "unsatisfiable":
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return True
        if span is None:
            return False
        start, end = span
        length = end - start + 1
        try:
            with target.open("rb") as f:
                f.seek(start)
                chunk = f.read(length)
        except OSError:
            return False
        self.send_response(206)
        self.send_header("Content-Type", kind or "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(chunk)
        return True

    def _serve_full(self, target, kind):
        try:
            body = target.read_bytes()
        except OSError:
            return self._not_found()
        self.send_response(200)
        self.send_header("Content-Type", kind or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        # A fingerprinted asset is safe to hold onto; the shell is not, or a rebuild stays
        # invisible until a hard refresh.
        self.send_header("Cache-Control",
                         "no-store" if target.name == INDEX_HTML else "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        """Serve the built app, or explain how to build it."""
        if not DIST.is_dir():
            return self._send_page(_NOT_BUILT, 200)
        clean = path.lstrip("/") or INDEX_HTML
        target = self._resolve_target(clean)
        if target is None:
            return self._not_found()
        suffix = target.suffix.lower()
        kind = TYPES.get(suffix) or mimetypes.guess_type(str(target))[0]
        try:
            file_size = target.stat().st_size
        except OSError:
            return self._not_found()
        if self._serve_range(target, kind, file_size, self._parse_byte_range(file_size)):
            return
        self._serve_full(target, kind)

    def _send_page(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------- changing ----------------------------------
    def do_POST(self):
        if not self._same_origin():
            return self._send_json({"error": "cross-origin request refused"}, 403)
        # A JSON content type is not one a browser sends cross-site without a preflight first,
        # and the preflight is refused above by the same check — so a page on another site cannot
        # reach any of this even as a "simple" request.
        kind = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if kind != "application/json":
            return self._send_json({"error": "send JSON with Content-Type: application/json"}, 415)
        path = self.path.split("?", 1)[0]
        body = self._read_json()
        if path == "/api/command":
            return self._command(body)
        if path == "/api/voice":
            return self._voice(body)
        if path == "/api/confirm":
            return self._confirm(body)
        if path == "/api/memories":
            return self._add_memory(body)
        if path == "/api/settings":
            return self._settings(body)
        return self._not_found()

    def do_DELETE(self):
        if not self._same_origin():
            return self._send_json({"error": "cross-origin request refused"}, 403)
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/memories/"):
            return self._forget_memory(path.rsplit("/", 1)[-1])
        return self._not_found()

    def _command(self, body):
        """One spoken-equivalent command, into the same queue the microphone fills."""
        text = str(body.get("text") or "").strip()
        if not text:
            return self._send_json({"ok": False, "error": "nothing to do"}, 400)
        commands.submit(text)
        return self._send_json({"ok": True, "queued": text})

    def _voice(self, body):
        """Change how Wilco sounds. The next line it says is already in the new voice."""
        if body.get("speed") is not None:
            voice.set_speed(body["speed"])
        wanted = str(body.get("voice") or "").strip()
        if wanted and not voice.use(wanted):
            return self._send_json({"ok": False, "error": f"no voice called {wanted}"}, 400)
        return self._send_json({"ok": True, **snapshot()})

    def _confirm(self, body):
        """Answer a parked action the way a spoken yes or no would."""
        result = gate.confirm_yes() if body.get("approve") else gate.cancel_action()
        # Said as well as shown: the same answer given by voice is spoken back, so a click does
        # not leave the conversation half-answered for anyone listening to the room.
        threading.Thread(target=voice.speak, args=(result,), daemon=True).start()
        return self._send_json({"ok": True, "result": result})

    def _settings(self, body):
        """Apply the settings screen's save. Only the parts that live on this machine.

        Both halves are applied rather than whichever key came first: the page posts its whole
        settings blob on every change, so a save carrying a voice and a microphone has to set both.
        A microphone arrives as a name, because the browser's device id is an opaque per-origin
        hash that identifies nothing on this side.
        """
        if "micDevice" in body or "micDeviceLabel" in body:
            speech.use_device(body.get("micDevice") or body.get("micDeviceLabel") or "")
        return self._voice(body)

    def _add_memory(self, body):
        from core.learning import add_correction
        text = str(body.get("text") or "").strip()
        if not text:
            return self._send_json({"success": False, "error": "nothing to remember"}, 400)
        add_correction(text)
        when = _iso_now()
        return self._send_json({"id": _memory_id(text), "category": "preference", "text": text,
                                "createdAt": when, "updatedAt": when})

    def _forget_memory(self, memory_id):
        from core.learning import get_corrections, remove_correction
        remembered = next((text for text in get_corrections()
                           if _memory_id(text) == memory_id), None)
        if remembered is None or not remove_correction(remembered):
            return self._send_json({"success": False, "error": "nothing remembered by that id"}, 404)
        return self._send_json({"success": True})


class _Server(ThreadingHTTPServer):
    """Daemon threads, so quitting Wilco never waits on a browser window still being open."""

    daemon_threads = True
    allow_reuse_address = True
    # A client sitting on the event stream with the connection open is the normal state of this
    # server, not a leak to wait for. Without this, closing down joins that handler and blocks
    # until its next keep-alive write fails — fifteen seconds of a program that is trying to quit.
    block_on_close = False

    def handle_error(self, request, client_address):
        """A window closing mid-stream is normal here, not a fault worth a traceback.

        The default prints the whole traceback for any handler error, and the event stream makes a
        dropped connection an everyday event — a reloaded tab, or Wilco quitting while one is open.
        """
        error = sys.exc_info()[1]
        # All three connection-drop errors subclass OSError, so one check covers them.
        if isinstance(error, OSError):
            return
        super().handle_error(request, client_address)


def _server(host=None, port=None):
    """Build the server. Both are explicit so a test can ask for an ephemeral port."""
    return _Server((host or config.UI_HOST,
                    int(port if port is not None else config.UI_PORT)), _Handler)


def _ensure_worker():
    """Ensure a background worker thread is draining commands if main.py is not running it."""
    if not any(t.name in ("wilco-worker", "wilco-listener") and t.is_alive() for t in threading.enumerate()):
        threading.Thread(target=commands.work, daemon=True, name="wilco-worker").start()


def serve(host=None, port=None):
    """Serve until interrupted — the UI on its own, with no microphone behind it."""
    _ensure_worker()
    server = _server(host, port)
    # Loopback-only UI (see _same_origin): plain HTTP on 127.0.0.1 is intentional — there is no
    # network path for TLS to protect, and a self-signed cert would only train click-through.
    where = f"http://{host or config.UI_HOST}:{server.server_address[1]}"  # NOSONAR
    print(f"Wilco frontend on {where}")
    if not _mic_running():
        print("No microphone in this process — start python main.py to talk to it as well.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


def serve_in_background(host=None, port=None):
    """Serve on a daemon thread, so main.py's own loop stays the program's foreground."""
    server = _server(host, port)
    threading.Thread(target=server.serve_forever, daemon=True,
                     name="wilco-frontend").start()
    return server


_NOT_BUILT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Wilco — build the frontend</title>
<style>
  body { margin:0; background:#05060f; color:#cbd5e1; font:15px/1.6 system-ui, sans-serif;
         display:flex; min-height:100vh; align-items:center; justify-content:center; }
  main { max-width:44rem; padding:2rem; }
  h1 { color:#e2e8f0; font-size:1.4rem; letter-spacing:.02em; }
  code { background:#0f172a; border:1px solid #1e293b; border-radius:.4rem;
         padding:.15rem .4rem; color:#67e8f9; font-family:ui-monospace, monospace; }
  pre { background:#0f172a; border:1px solid #1e293b; border-radius:.6rem; padding:1rem; }
  p { color:#94a3b8; }
</style></head>
<body><main>
  <h1>Wilco is running — the frontend just hasn't been built yet</h1>
  <p>The backend is up and answering, but there is no <code>Frontend/dist</code> to serve.
     Build it once, and reload this page:</p>
  <pre>cd Frontend
npm install
npm run build</pre>
  <p>While you are working on the UI, <code>npm run dev</code> serves it on
     <code>http://localhost:5173</code> with hot reload and proxies back here — the backend port
     does not change either way.</p>
  <p>The microphone works regardless: <code>python main.py</code> starts talking to Wilco without
     any of this.</p>
</main></body></html>
"""


# No standalone entry point on purpose. `python main.py` is the only thing that ever starts
# this server (see _serve_frontend in main.py) — that way there is exactly one process bound
# to the UI port, and UI changes are made here and picked up by main.py on its next run.
# The serve()/serve_in_background() functions above remain importable for tests and tooling.
