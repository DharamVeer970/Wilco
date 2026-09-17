/**
 * The one shared type for how Wilco's live state is named.
 *
 * Once, this file also carried a WebSocket client for a browser-side voice model. That path is
 * gone: Wilco speaks in Python, through windows/voice.py, and the browser only shows what the
 * SSE stream reports. The state names here are what the backend emits - disconnected, connecting,
 * listening, thinking, speaking - and every component that draws state reads them from here.
 */

export type LiveState = "disconnected" | "connecting" | "listening" | "speaking" | "idle" | "thinking";
