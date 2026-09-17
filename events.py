"""Everything that happens, published in one place, for whoever is watching.

Wilco's state is spread across a voice engine that blocks, an agent loop that thinks in
steps, and a listener that is deliberately deaf while it talks. None of that is observable
after the fact — by the time a browser could ask "is it speaking?", the sentence is over.
So the moments worth showing are published here as they happen, and the UI subscribes
instead of polling.

Two rules keep this from becoming a liability. It imports nothing, so any layer can publish
to it without a cycle, and it sits at the root next to config.py for exactly that reason.
And it never blocks a producer: each subscriber gets its own bounded queue, and a slow one
has its oldest event dropped rather than being allowed to stall the assistant mid-sentence.
With nothing subscribed — the normal case when the frontend isn't open — every call here
costs one list append.

    events.emit("state", value="thinking")
    events.emit("transcript", role="assistant", text="Volume is at 40 percent.")

The event kinds are the contract the frontend codes against, and they are listed in
Frontend/README.md rather than here, so there is one description of them instead of two.
"""
import queue
import threading
import time
from collections import deque

# Enough that a tab opened — or reloaded mid-sentence — can still be caught up.
_HISTORY = 200
# Per subscriber. A window left open for hours is the realistic case, not a fast reader.
_BACKLOG = 256

_lock = threading.Lock()
_subscribers = {}
_history = deque(maxlen=_HISTORY)
_seq = 0


def emit(kind, **fields):
    """Publish one event. Thread-safe, and safe to call with nobody listening."""
    global _seq
    with _lock:
        _seq += 1
        event = {"seq": _seq, "kind": kind, "at": time.time(), **fields}
        _history.append(event)
        stale = []
        for token, inbox in _subscribers.items():
            try:
                inbox.put_nowait(event)
            except queue.Full:
                # Drop this subscriber's oldest event and try once more: losing a frame of
                # UI history is survivable, blocking the next spoken word is not.
                try:
                    inbox.get_nowait()
                    inbox.put_nowait(event)
                except (queue.Empty, queue.Full):
                    stale.append(token)
        for token in stale:
            _subscribers.pop(token, None)
    return event


def subscribe():
    """One subscriber's own inbox, plus the replay of what happened before it arrived."""
    inbox = queue.Queue(maxsize=_BACKLOG)
    with _lock:
        token = object()
        _subscribers[token] = inbox
        missed = list(_history)
    return token, inbox, missed


def unsubscribe(token):
    with _lock:
        _subscribers.pop(token, None)


def subscribers():
    """How many watchers are attached — one browser window is one subscriber."""
    with _lock:
        return len(_subscribers)
