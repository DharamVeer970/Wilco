/** Wilco Settings Store — persistent user preferences (V2).
 *
 * Establishes the persistence pattern for Wilco: settings are mirrored to
 * localStorage (instant local read) AND synced to the backend (settings.json)
 * so auto-start / wake-word preferences survive across browsers and the
 * Python desktop agent can read them too.
 *
 * Pattern follows the existing codebase conventions: plain state + ref mirrors.
 * No Context/Zustand — this is deliberately lightweight to match audio.ts/memoryTypes.ts.
 */

export interface Settings {
  /** Launch Wilco (backends + browser tab) silently on Windows login. */
  autoStart: boolean;
  /** Enable the always-listening wake-word detector. */
  wakeWordEnabled: boolean;
  /** Phrase that activates Wilco (case-insensitive substring match). */
  wakePhrase: string;
  /** Preferred microphone device id ("" = system default). Browser-side only — it is an opaque
   *  per-origin hash that the Python microphone cannot resolve. */
  micDeviceId: string;
  /** Human-readable name of the same device. This is what windows/speech.py matches on. */
  micDeviceLabel: string;
  /** Wake-word sensitivity: 0 (strict) .. 100 (loose). Affects debounce window. */
  sensitivity: number;
  /** Master toggle for UI animations. */
  animations: boolean;
  /** Selected backend voice name (ava, sonia, madhur, ...). */
  voice: string;
  /** Selected background video filename. */
  backgroundVideo: string;
  /** Avatar style ("character" for video, "orb" for Aegis, or "image"). */
  avatarStyle: "character" | "orb" | "image";
}

export const DEFAULT_SETTINGS: Settings = {
  autoStart: false,
  wakeWordEnabled: false,
  wakePhrase: "hey wilco",
  micDeviceId: "",
  micDeviceLabel: "",
  sensitivity: 60,
  animations: true,
  voice: "ava",
  backgroundVideo: "solid",
  avatarStyle: "character",
};

/** Wilco Settings Store — persistent user preferences (V2).
 *
 * Establishes the persistence pattern for Wilco: settings are mirrored to
 * localStorage and (best-effort) the backend so both layers stay in sync.
 */
const STORAGE_KEY = "wilco.settings.v2";

/** Settings keys that the browser should never persist (security). */
const NEVER_PERSIST: ReadonlySet<keyof Settings> = new Set([]);

/**
 * Load settings from localStorage, merged over defaults so new keys always
 * have a sane value even when an older payload is present.
 */
export function loadSettings(): Settings {
  if (typeof window === "undefined") return { ...DEFAULT_SETTINGS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

/**
 * Persist a full or partial settings update to localStorage.
 * Returns the fully merged settings object.
 */
export function saveSettings(patch: Partial<Settings>): Settings {
  const current = loadSettings();
  // A save that changes nothing is not a save. The stream announces the voice the backend is
  // already using, and echoing that announcement back as a settings write would post to the
  // backend forever — which is exactly the loop that made the browser crawl.
  const changed = (Object.keys(patch) as (keyof Settings)[]).some(
    (key) => patch[key] !== undefined && patch[key] !== current[key],
  );
  if (!changed) {
    // Same object back, so React also skips re-rendering the whole tree for an echo.
    return current;
  }
  const next: Settings = { ...current, ...patch };
  if (typeof window !== "undefined") {
    try {
      // Strip any sensitive keys before writing to localStorage.
      const safe: Record<string, unknown> = {};
      (Object.keys(next) as (keyof Settings)[]).forEach((k) => {
        if (!NEVER_PERSIST.has(k)) safe[k] = next[k];
      });
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(safe));
    } catch {
      /* localStorage may be unavailable (private mode) — fail silently. */
    }
  }
  // Best-effort sync to backend so the Python agent can read auto-start state.
  void syncSettingsToBackend(next).catch(() => {});
  return next;
}

/** Push settings to the backend (server.ts persists to settings.json). */
async function syncSettingsToBackend(settings: Settings): Promise<void> {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings),
    });
  } catch {
    /* Backend may be briefly unavailable during boot — non-fatal. */
  }
}
