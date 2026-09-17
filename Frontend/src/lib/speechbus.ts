/**
 * The speech bus: what the backend's mouth is doing, as one number.
 *
 * Wilco speaks in Python, through the machine's own speakers — the browser never has the audio,
 * only the announcements the backend emits while it talks: a line starting, the sentence groups
 * inside it, and the line ending. Those arrive on the same SSE stream as everything else, and
 * App.tsx feeds them here. The visualizer asks `envelope()` once a frame and gets a 0..1 value
 * that rises and falls with the sentences actually being said, which is what lets the talking
 * clip's playback rate — and any mouth-driven overlay — follow the voice instead of guessing.
 *
 * Between chunks the envelope rests, the way a speaker breathes; while a chunk is open it
 * oscillates at a syllable-ish cadence scaled by the chunk's length, so short lines snap and
 * long ones flow. No timers of its own: it is pure state, read by the stage's existing rAF loop.
 */

export type SpeakPhase = "start" | "chunk" | "end";

export interface SpeakEvent {
  phase: SpeakPhase;
  /** How long the current sentence group is, in characters — longer means a slower cadence. */
  length?: number;
}

/** One opened sentence group: when it began, how fast it reads, and for how long. */
interface Chunk {
  startedAt: number;
  /** Radians per millisecond of the mouth's oscillation. */
  cadence: number;
  /** Estimated reading time, in milliseconds. */
  duration: number;
}

const OPEN: Chunk[] = [];
let speakingUntil = 0;

/** Speech speed set by the backend (percent on top of the voice's own pace). */
let speedPercent = 0;

/** Feed one `speak` event from the SSE stream. */
export function onSpeakEvent(event: SpeakEvent): void {
  const now = performance.now();
  if (event.phase === "start") {
    OPEN.length = 0;
    // A line with no known length still reads for a believable moment.
    speakingUntil = now + 1200;
  } else if (event.phase === "chunk") {
    const length = Math.max(8, event.length ?? 60);
    // Roughly 15 characters a second, quicker when Wilco's speed is up.
    const seconds = length / (15 * (1 + speedPercent / 250));
    OPEN.push({ startedAt: now, cadence: (Math.PI * 2) / (seconds * 260), duration: seconds * 1000 });
    speakingUntil = now + seconds * 1000;
  } else {
    OPEN.length = 0;
    // The mouth closes gently rather than the instant the last mp3 ends.
    speakingUntil = Math.min(speakingUntil, now + 120);
  }
}

/** Backend told us the speech speed changed; cadence follows it. */
export function onSpeedEvent(percent: number): void {
  speedPercent = percent;
}

/**
 * The 0..1 mouth value for this instant. A gentle oscillation while a sentence group is being
 * said, easing to rest in the pauses between groups — reading `Math.sin` of wall time with a
 * per-chunk cadence is what keeps it stable no matter how often it is sampled.
 */
export function envelope(): number {
  const now = performance.now();
  // A chunk whose estimated reading time has passed with a little grace is done, event or not —
  // a dropped frame on the stream can never leave the mouth chewing at nothing.
  while (OPEN.length && now - OPEN[0].startedAt > OPEN[0].duration + 250) {
    OPEN.shift();
  }
  if (!OPEN.length) {
    return now < speakingUntil ? 0.12 : 0;
  }
  // The oldest open chunk drives the mouth; newer ones are already queued behind it.
  const chunk = OPEN[0];
  const wave = 0.5 + 0.5 * Math.sin((now - chunk.startedAt) * chunk.cadence);
  // Never fully closed while a group is open — the face is mid-word.
  return 0.18 + 0.82 * wave;
}