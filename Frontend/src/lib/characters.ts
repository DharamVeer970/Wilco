/**
 * Character Registry — maps every Wilco voice to a video-entity avatar.
 *
 * Single source of truth for the avatar system. Wilco speaks with the Edge voice packs in
 * windows/voice.py (ava, andrew, brian, ...), and each pack is drawn as one of seven
 * personas named after its lead voice, so a voice change carries the face, the clips and
 * the accent with it. One persona may own several voices — they sound alike, so they
 * look alike. Every voice in windows/voice.py VOICES appears in exactly one list below.
 *
 * Clips live in /assets/videos/<asset>_<state>.webm (idle, thinking, talking), rendered
 * from the persona PNG by scripts/generate_hd_videos.py. A persona without a clip falls
 * back to the shared /assets/<state>.webm set, and that failing too lands on the poster
 * frame, so a missing file can never blank the stage.
 */

export interface CharacterDef {
  /** Path to the character image (served from /assets/characters/). */
  image: string;
  /** Display name shown under the avatar. */
  name: string;
  /** Short personality description. */
  desc: string;
  /** Accent hex color for glow ring / UI highlights. */
  accent: string;
  /** Secondary glow color (slightly different hue). */
  accentGlow: string;
  /** Every Wilco voice pack that appears as this character. */
  voices: readonly string[];
}

export const CHARACTERS: Record<string, CharacterDef> = {
  ava: {
    image: "/assets/characters/aoede.png",
    name: "Ava",
    desc: "Warm and natural",
    accent: "#0284c7",    // vibrant blue
    accentGlow: "#38bdf8",// cyan glow
    voices: ["ava", "aoede", "luna", "zira"],
  },
  brian: {
    image: "/assets/characters/charon.png",
    name: "Brian",
    desc: "Deep and authoritative",
    accent: "#1e3a5f",    // dark navy
    accentGlow: "#3b82f6",
    voices: ["brian", "charon", "erebus", "david"],
  },
  blaze: {
    image: "/assets/characters/fenrir.png",
    name: "Blaze",
    desc: "Bold and confident",
    accent: "#dc2626",    // red
    accentGlow: "#f97316",
    voices: ["blaze", "fenrir", "sonia", "ryan"],
  },
  swara: {
    image: "/assets/characters/swara.png",
    name: "Swara",
    desc: "Melodious and expressive",
    accent: "#0284c7",    // vibrant blue
    accentGlow: "#38bdf8",// cyan glow
    voices: ["swara"],
  },
  madhur: {
    image: "/assets/characters/madhur.png",
    name: "Madhur",
    desc: "Charismatic and articulate",
    accent: "#2563eb",    // sapphire blue
    accentGlow: "#60a5fa",
    voices: ["madhur", "prabhat"],
  },
  neerja: {
    image: "/assets/characters/leda.png",
    name: "Neerja",
    desc: "Calm and composed",
    accent: "#64748b",    // silver/slate
    accentGlow: "#94a3b8",
    voices: ["neerja", "leda", "athena"],
  },
  iris: {
    image: "/assets/characters/kore.png",
    name: "Iris",
    desc: "Soft and gentle",
    accent: "#c084fc",    // purple/pink
    accentGlow: "#e879f9",
    voices: ["iris", "kore", "emma"],
  },
  andrew: {
    image: "/assets/characters/puck.png",
    name: "Andrew",
    desc: "Energetic and playful",
    accent: "#10b981",    // emerald/teal
    accentGlow: "#34d399",
    voices: ["andrew", "puck", "spark"],
  },
  natasha: {
    image: "/assets/characters/zephyr.png",
    name: "Natasha",
    desc: "Light and breezy",
    accent: "#0ea5e9",    // sky blue
    accentGlow: "#38bdf8",
    voices: ["natasha", "zephyr", "aria"],
  },
};

/** The persona a voice pack is drawn as, defaulting to Ava so nothing is ever faceless. */
export function characterForVoice(voice: string | undefined): CharacterDef {
  const wanted = (voice || "").trim().toLowerCase();
  if (!wanted) return CHARACTERS.ava;
  const matchKey = Object.keys(CHARACTERS).find((k) => k.toLowerCase() === wanted);
  if (matchKey) return CHARACTERS[matchKey];
  const found = Object.values(CHARACTERS).find(
    (char) => char.name.toLowerCase() === wanted || char.voices.some((v) => v.toLowerCase() === wanted),
  );
  return found || CHARACTERS.ava;
}

/** Legacy helper: the character registered under a Gemini-style key, with a fallback. */
export function getCharacter(voiceId: string | undefined): CharacterDef {
  return characterForVoice(voiceId);
}

/** Registry seat of a voice's character — switches walk toward the neighbouring seat. */
export function characterSeat(voice: string | undefined): number {
  const target = characterForVoice(voice);
  return Object.keys(CHARACTERS).findIndex((key) => CHARACTERS[key] === target);
}

/** All characters, in registry order — the voice picker walks this list. */
export const CHARACTER_LIST: CharacterDef[] = Object.values(CHARACTERS);

/** The three clip states the stage cycles through. */
export type CharacterClipState = "idle" | "thinking" | "talking";

/**
 * The clip path that will actually play for a character and state, honouring what the browser
 * reports about earlier load attempts. A 404 webm resolves to null so the caller can fall back
 * in the same tick instead of showing a black video element. Per-character clips are tried first
 * (/assets/videos/<key>_<state>.webm), then the shared set, then the poster frame — each
 * resolved by what actually loaded, not by what the table hopes is there.
 */
const clipStatus = new Map<string, "loading" | "ok" | "missing">();

export function characterClip(character: CharacterDef, state: CharacterClipState): string | null {
  const name = character.name.toLowerCase();
  if (name === "ava" || character.voices.includes("ava")) {
    return `/assets/${state}.webm`;
  }
  if (name === "swara" || character.voices.includes("swara")) {
    return `/assets/videos/swara_${state}.webm`;
  }
  if (name === "blaze" || character.voices.includes("blaze") || character.voices.includes("fenrir")) {
    return `/assets/videos/fenrir_${state}.webm`;
  }
  if (name === "andrew" || character.voices.includes("andrew") || character.voices.includes("puck")) {
    return `/assets/videos/puck_${state}.webm`;
  }
  const perCharacter = `/assets/videos/${character.image
    .split("/")
    .pop()!
    .replace(/\.png$/, "")}_${state}.webm`;
  const status = clipStatus.get(perCharacter);
  if (status === "missing") return `/assets/${state}.webm`;
  if (status === "ok") return perCharacter;
  // Untried clips optimistically resolve — the stage reports the result back via noteClip().
  return perCharacter;
}

/** The stage reports what a clip element managed to load, so the next pick uses the truth. */
export function noteClip(src: string, loaded: boolean): void {
  clipStatus.set(src, loaded ? "ok" : "missing");
}

/** Poster shown before a clip has its first frame, and when every clip is missing. */
export const CHARACTER_POSTER = "/assets/frame.jpg";

/** Preload all character images in the background so voice switching is instantaneous. */
if (typeof window !== "undefined") {
  const preload = () => {
    Object.values(CHARACTERS).forEach((char) => {
      const img = new Image();
      img.src = char.image;
    });
  };
  if ("requestIdleCallback" in window) {
    (window as any).requestIdleCallback(preload);
  } else {
    setTimeout(preload, 300);
  }
}

