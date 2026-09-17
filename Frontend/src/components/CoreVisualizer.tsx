import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { LiveState } from "../lib/audio";
import {
  characterClip,
  characterSeat,
  getCharacter,
  noteClip,
  CHARACTER_POSTER,
  type CharacterClipState,
  type CharacterDef,
} from "../lib/characters";
import { envelope } from "../lib/speechbus";
import { Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";

export type WilcoEmotion =
  | "idle"
  | "happy"
  | "excited"
  | "curious"
  | "thinking"
  | "proud"
  | "sad"
  | "confused"
  | "surprised"
  | "embarrassed"
  | "playful";

interface WilcoCoreVisualizerProps {
  state: LiveState;
  themeColor: string;
  activeEmotion?: WilcoEmotion;
  characterState: "idle" | "thinking" | "talking";
  backgroundVideo?: string;
  avatarStyle: "character" | "orb" | "image";
  voiceId?: string;
}

interface GlowColors {
  primary: string;
  secondary: string;
  glow: string;
}

interface Particle {
  x: number;
  y: number;
  speed: number;
  size: number;
  opacity: number;
}

/** Visual-only randomness (particles, drift). Not for ids, tokens, or security. */
// NOSONAR - decorative canvas dust only, no security decision uses this value
function visualRandom(): number {
  return Math.random(); // NOSONAR
}

function createParticles(width: number, height: number): Particle[] {
  const count = Math.min(30, Math.floor(width / 36));
  return Array.from({ length: count }, () => ({
    x: visualRandom() * width,
    y: visualRandom() * height + height * 0.1,
    speed: visualRandom() * 0.35 + 0.12,
    size: visualRandom() * 1.5 + 0.5,
    opacity: visualRandom() * 0.6 + 0.2,
  }));
}

const ORB_GLOWS: Record<string, GlowColors> = {
  violet: { primary: "rgba(147, 51, 234, 1)", secondary: "rgba(192, 38, 211, 0.8)", glow: "rgba(168, 85, 247, 0.7)" },
  crimson: { primary: "rgba(225, 29, 72, 1)", secondary: "rgba(234, 88, 12, 0.8)", glow: "rgba(244, 63, 94, 0.7)" },
  emerald: { primary: "rgba(5, 150, 105, 1)", secondary: "rgba(13, 148, 136, 0.8)", glow: "rgba(16, 185, 129, 0.7)" },
  celestial: { primary: "rgba(2, 132, 199, 1)", secondary: "rgba(8, 145, 178, 0.8)", glow: "rgba(14, 165, 233, 0.7)" },
  gold: { primary: "rgba(202, 138, 4, 1)", secondary: "rgba(217, 119, 6, 0.8)", glow: "rgba(234, 179, 8, 0.7)" },
  rose: { primary: "rgba(219, 39, 119, 1)", secondary: "rgba(220, 38, 38, 0.8)", glow: "rgba(236, 72, 153, 0.7)" },
};

const DEFAULT_ORB_GLOW: GlowColors = {
  primary: "rgba(34, 211, 238, 1)",
  secondary: "rgba(79, 70, 229, 0.8)",
  glow: "rgba(6, 182, 212, 0.7)",
};

const SOLID_BACKGROUNDS: Record<string, string> = {
  violet: "bg-[#0f0724]",
  crimson: "bg-[#1a0508]",
  emerald: "bg-[#04140d]",
  celestial: "bg-[#040f1a]",
  gold: "bg-[#1a1103]",
  rose: "bg-[#1a0611]",
};

const NEBULA_GRADIENTS: Record<string, string> = {
  violet: "from-purple-900/50 via-violet-600/20 to-fuchsia-900/10",
  crimson: "from-rose-900/50 via-red-600/20 to-orange-900/10",
  emerald: "from-emerald-900/50 via-teal-600/20 to-emerald-900/10",
  celestial: "from-sky-900/50 via-indigo-600/20 to-cyan-900/10",
  gold: "from-amber-900/50 via-yellow-600/20 to-orange-900/10",
  rose: "from-rose-900/50 via-pink-600/20 to-purple-900/10",
};

const DEFAULT_NEBULA = "from-sky-900/40 via-indigo-950/20 to-blue-900/10";
const VIDEO_FILTER = "contrast(1.02) saturate(1.04)";
const WALK_EASE_IN: [number, number, number, number] = [0.16, 1, 0.3, 1];
const WALK_EASE_OUT: [number, number, number, number] = [0.32, 0, 0.67, 0];

function getGlowColors(themeColor: string, avatarStyle: string, displayedVoice: string): GlowColors {
  if (avatarStyle === "image" || avatarStyle === "character") {
    const char = getCharacter(displayedVoice);
    return { primary: char.accent, secondary: char.accentGlow, glow: char.accentGlow };
  }
  return ORB_GLOWS[themeColor] ?? DEFAULT_ORB_GLOW;
}

export function hexToRgba(hex: string, alpha: number): string {
  const r = Number.parseInt(hex.slice(1, 3), 16);
  const g = Number.parseInt(hex.slice(3, 5), 16);
  const b = Number.parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function getSolidBackgroundClass(themeColor: string): string {
  return SOLID_BACKGROUNDS[themeColor] ?? "bg-[#020817]";
}

function getBackgroundFill(avatarStyle: string, backgroundVideo: string | undefined, themeColor: string): string {
  if (avatarStyle === "orb") {
    return "bg-[#030718]";
  }
  if (backgroundVideo === "solid") {
    return getSolidBackgroundClass(themeColor);
  }
  return "bg-[#020817]";
}

function getNebulaGradient(themeColor: string): string {
  return NEBULA_GRADIENTS[themeColor] ?? DEFAULT_NEBULA;
}

function getNebulaMotion(characterState: string): string {
  if (characterState === "talking") {
    return "scale-110 animate-pulse";
  }
  if (characterState === "thinking") {
    return "scale-95 opacity-20";
  }
  return "scale-100";
}

function shouldShowNebula(backgroundVideo: string | undefined, avatarStyle: string): boolean {
  return backgroundVideo !== "solid" && avatarStyle !== "orb";
}

function shouldShowVideoBg(backgroundVideo: string | undefined, avatarStyle: string): boolean {
  return Boolean(backgroundVideo) && backgroundVideo !== "solid" && avatarStyle !== "orb";
}

function getCharacterFilter(characterState: string): string {
  if (characterState === "thinking") {
    return "brightness(0.85) saturate(0.85)";
  }
  if (characterState === "talking") {
    return "brightness(1.08) contrast(1.04) saturate(1.1)";
  }
  return "brightness(1) saturate(1)";
}

function getVideoFilter(characterState: string): string {
  if (characterState === "thinking") {
    return "brightness(0.94) contrast(1.02)";
  }
  if (characterState === "talking") {
    return "brightness(1.06) contrast(1.05) saturate(1.1)";
  }
  return "brightness(1) saturate(1)";
}

function getOrbClass(characterState: string): string {
  if (characterState === "idle") {
    return "scale-90 opacity-90";
  }
  if (characterState === "thinking") {
    return "scale-75 opacity-70";
  }
  return "scale-100 opacity-100";
}

function isClipActive(activeState: string, clipState: CharacterClipState): boolean {
  return activeState === clipState;
}

function clipVisibilityClass(active: boolean): string {
  if (active) {
    return "opacity-100 z-10 scale-100 pointer-events-auto";
  }
  return "opacity-0 z-0 scale-[0.99] pointer-events-none";
}

function clipImageVisibility(active: boolean): string {
  if (active) {
    return "opacity-100 z-10 pointer-events-auto";
  }
  return "opacity-0 z-0 pointer-events-none";
}

function computeRawLevel(liveState: LiveState, systemTime: number): number {
  if (liveState === "speaking") {
    return envelope();
  }
  if (liveState === "listening") {
    return 0.18 + 0.12 * Math.sin(systemTime * 0.0025);
  }
  return 0;
}

function computeTargetRing(liveState: LiveState, vol: number): number {
  if (liveState === "speaking") {
    return vol * 1.3;
  }
  if (liveState === "listening") {
    return vol * 0.8;
  }
  return 0;
}

function applyCharacterMotion(
  el: HTMLElement,
  opts: { liveState: LiveState; characterState: string; vol: number; time: number },
): void {
  const { liveState, characterState, vol, time } = opts;
  if (characterState === "talking" || liveState === "speaking") {
    const bob = -vol * 15 + Math.sin(time * 0.002) * 3;
    const emphasis = 1.0 + vol * 0.065;
    const sway = Math.sin(time * 0.007) * (vol * 3.2);
    const gestures = Math.cos(time * 0.0035) * (vol * 5);
    el.style.transform = `translate(${gestures}px, ${bob}px) scale(${emphasis}) rotate(${sway}deg)`;
    return;
  }
  if (liveState === "listening") {
    const lean = 1.025 + vol * 0.03;
    const nod = Math.sin(time * 0.004) * (2 + vol * 5);
    const tilt = Math.sin(time * 0.0018) * 1.5;
    el.style.transform = `translateY(${nod - 6}px) scale(${lean}) rotate(${tilt}deg)`;
    return;
  }
  if (characterState === "thinking") {
    const bob = Math.sin(time * 0.0025) * 4;
    el.style.transform = `translateY(${bob - 3}px) scale(0.985) rotate(-1.8deg)`;
    return;
  }
  const breath = Math.sin(time * 0.0018) * 5;
  const tilt = Math.sin(time * 0.0012) * 0.8;
  el.style.transform = `translateY(${breath}px) scale(1) rotate(${tilt}deg)`;
}

function drawParticles(
  ctx: CanvasRenderingContext2D,
  particles: Particle[],
  width: number,
  height: number,
  time: number,
): void {
  for (let i = 0; i < particles.length; i++) {
    const p = particles[i];
    p.y -= p.speed;
    if (p.y < -10) {
      p.y = height + 10;
      p.x = visualRandom() * width; // NOSONAR
    }
    p.x += Math.sin(time * 0.001 + i) * 0.08;
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
    const alpha = p.opacity * (0.6 + 0.4 * Math.sin(time * 0.002 + i * 0.5));
    ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`;
    ctx.fill();
  }
}

interface PedestalFrame {
  ctx: CanvasRenderingContext2D;
  centerX: number;
  ringY: number;
  ringRadius: number;
  pulse: number;
  boost: number;
  glow: number;
}

function drawPedestalCharacter(
  frame: PedestalFrame,
  char: CharacterDef,
): void {
  const { ctx, centerX, ringY, ringRadius, pulse, boost, glow } = frame;
  const gradient = ctx.createRadialGradient(centerX, ringY, 0, centerX, ringY, ringRadius);
  gradient.addColorStop(0, hexToRgba(char.accent, 0.65));
  gradient.addColorStop(0.3, hexToRgba(char.accentGlow, 0.28));
  gradient.addColorStop(0.7, hexToRgba(char.accentGlow, 0.08));
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(centerX - ringRadius - 20, ringY - ringRadius, (ringRadius + 20) * 2, ringRadius + 20);
  ctx.beginPath();
  ctx.ellipse(centerX, ringY, ringRadius * 0.9, 8 * pulse * boost, 0, 0, Math.PI * 2);
  ctx.strokeStyle = hexToRgba(char.accent, 0.2 + glow * 0.35);
  ctx.lineWidth = 2;
  ctx.stroke();
}

function withAlpha(rgba: string, replacement: string, fallback: string): string {
  if (!rgba.startsWith("rgba(") || !rgba.endsWith(")")) {
    return fallback;
  }
  const lastComma = rgba.lastIndexOf(",");
  if (lastComma === -1) {
    return fallback;
  }
  return `${rgba.slice(0, lastComma + 2)}${replacement}`;
}

function drawPedestalOrb(
  frame: PedestalFrame,
  colors: GlowColors,
): void {
  const { ctx, centerX, ringY, ringRadius, pulse, boost, glow } = frame;
  const gradient = ctx.createRadialGradient(centerX, ringY, 0, centerX, ringY, ringRadius);
  gradient.addColorStop(0, withAlpha(colors.primary, "0.6)", "rgba(34,211,238,0.6)"));
  gradient.addColorStop(0.3, withAlpha(colors.secondary, "0.25)", "rgba(79,70,229,0.25)"));
  gradient.addColorStop(0.7, withAlpha(colors.glow, "0.08)", "rgba(6,182,212,0.08)"));
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(centerX - ringRadius - 20, ringY - ringRadius, (ringRadius + 20) * 2, ringRadius + 20);
  ctx.beginPath();
  ctx.ellipse(centerX, ringY, ringRadius * 0.9, 8 * pulse * boost, 0, 0, Math.PI * 2);
  const alpha = (0.15 + glow * 0.3).toFixed(3);
  ctx.strokeStyle = withAlpha(colors.primary, `${alpha})`, `rgba(34,211,238,${alpha})`);
  ctx.lineWidth = 2;
  ctx.stroke();
}

function drawScanlines(ctx: CanvasRenderingContext2D, width: number, height: number, time: number): void {
  ctx.fillStyle = "rgba(0, 255, 255, 0.012)";
  const offset = (time * 0.02) % 12;
  for (let y = offset; y < height; y += 12) {
    ctx.fillRect(0, y, width, 1.2);
  }
}

function drawGrid(ctx: CanvasRenderingContext2D, width: number, height: number): void {
  ctx.strokeStyle = "rgba(100, 200, 255, 0.012)";
  ctx.lineWidth = 1;
  const spacing = width / 20;
  for (let x = 0; x < width; x += spacing) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
}

function drawRays(
  ctx: CanvasRenderingContext2D,
  centerX: number,
  ringY: number,
  ringRadius: number,
  time: number,
  glow: number,
): void {
  for (let i = 0; i < 12; i++) {
    const angle = (i / 12) * Math.PI * 2 + time * 0.0001;
    const len = ringRadius * (2 + 0.5 * Math.sin(time * 0.001 + i));
    ctx.beginPath();
    ctx.moveTo(centerX, ringY);
    ctx.lineTo(centerX + Math.cos(angle) * len, ringY + Math.sin(angle) * len * 0.15);
    const rayColor = i % 2 === 0 ? "150, 100, 255" : "100, 200, 255";
    ctx.strokeStyle = `rgba(${rayColor}, ${0.03 + glow * 0.06})`;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }
}

function WalkShell({
  walkKey,
  walkDirection,
  children,
}: Readonly<{
  walkKey: string;
  walkDirection: number;
  children: React.ReactNode;
}>): React.JSX.Element {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={walkKey}
        initial={{ x: walkDirection * 480, opacity: 0 }}
        animate={{
          x: 0,
          opacity: 1,
          y: [0, -18, 0, -15, 2, -10, 0],
          rotate: [0, walkDirection * 2.8, -walkDirection * 2, walkDirection * 1.5, 0],
          transition: {
            x: { duration: 0.95, ease: WALK_EASE_IN },
            opacity: { duration: 0.45 },
            y: { duration: 0.95, times: [0, 0.2, 0.4, 0.6, 0.8, 0.9, 1] },
            rotate: { duration: 0.95, times: [0, 0.25, 0.5, 0.75, 1] },
          },
        }}
        exit={{
          x: -walkDirection * 480,
          opacity: 0,
          y: [0, -18, 2, -14, 0],
          rotate: [0, -walkDirection * 2.5, walkDirection * 1.8, 0],
          transition: {
            x: { duration: 0.7, ease: WALK_EASE_OUT },
            opacity: { duration: 0.35, delay: 0.1 },
            y: { duration: 0.7 },
            rotate: { duration: 0.7 },
          },
        }}
        className="relative flex flex-col items-center select-none"
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

function CharacterBadge({ character }: Readonly<{ character: CharacterDef }>): React.JSX.Element {
  return (
    <div className="absolute -bottom-2 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 z-20">
      <span
        className="text-[10px] font-mono font-bold tracking-[0.3em] uppercase px-4 py-1 rounded-full border backdrop-blur-xl shadow-lg"
        style={{
          color: character.accentGlow,
          borderColor: hexToRgba(character.accent, 0.4),
          backgroundColor: hexToRgba(character.accent, 0.15),
        }}
      >
        {character.name}
      </span>
    </div>
  );
}

function StageBackground({
  themeColor,
  avatarStyle,
  backgroundVideo,
  characterState,
}: Readonly<{
  themeColor: string;
  avatarStyle: string;
  backgroundVideo: string | undefined;
  characterState: string;
}>): React.JSX.Element {
  const fill = getBackgroundFill(avatarStyle, backgroundVideo, themeColor);
  const showNebula = shouldShowNebula(backgroundVideo, avatarStyle);
  const showVideo = shouldShowVideoBg(backgroundVideo, avatarStyle);
  return (
    <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-0 overflow-hidden">
      {/* Dark blue background */}
      <div className={`absolute inset-0 transition-colors duration-1000 ${fill}`} />
      
      {/* Soft light glow in center behind character (halka light glow) */}
      <div className="absolute w-[80vw] h-[75vh] top-[15%] left-1/2 -translate-x-1/2 rounded-full blur-[100px] opacity-35 bg-[radial-gradient(ellipse_at_center,rgba(56,189,248,0.3)_0%,rgba(37,99,235,0.18)_45%,transparent_75%)] pointer-events-none" />

      {showNebula && (
        <div
          className={`absolute w-[150vw] h-[150vh] rounded-full blur-[140px] opacity-25 bg-linear-to-tr transition-all duration-1000 ease-in-out ${getNebulaGradient(themeColor)} ${getNebulaMotion(characterState)}`}
        />
      )}
      {showVideo && (
        <div className="absolute inset-0 w-full h-full opacity-100 transition-opacity duration-1000">
          <video
            key={`bg-video-${backgroundVideo}`}
            src={`/assets/${backgroundVideo}`}
            loop
            muted
            playsInline
            autoPlay
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLVideoElement).style.display = "none";
            }}
          />
        </div>
      )}
      {/* Deep vignette smoothly fading to dark blue at outer edges */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_20%,rgba(2,8,23,0.7)_70%,#020817_100%)] opacity-90" />
    </div>
  );
}

function ClipVideo({
  clipState,
  activeState,
  src,
  isDead,
  clipKey,
  videoRef,
  onLoaded,
  onError,
}: Readonly<{
  clipState: CharacterClipState;
  activeState: string;
  src: string;
  isDead: boolean;
  clipKey: string;
  videoRef: React.Ref<HTMLVideoElement>;
  onLoaded: (el: HTMLVideoElement) => void;
  onError: (el: HTMLVideoElement) => void;
}>): React.JSX.Element {
  const active = isClipActive(activeState, clipState);
  if (isDead) {
    return (
      <img
        src={CHARACTER_POSTER}
        alt=""
        className={`absolute inset-0 h-full w-full object-contain object-bottom transition-opacity duration-300 ${clipImageVisibility(active)}`}
        style={{ mixBlendMode: "screen", filter: VIDEO_FILTER }}
      />
    );
  }
  const usesStageBg = Boolean(
    src &&
      (src.includes("swara") ||
        src.includes("fenrir") ||
        src.includes("blaze") ||
        src.includes("puck") ||
        src.includes("andrew")),
  );
  const videoStyle: React.CSSProperties = usesStageBg
    ? {
        WebkitMaskImage: "radial-gradient(ellipse 78% 74% at 50% 55%, black 50%, rgba(0, 0, 0, 0.85) 70%, transparent 98%)",
        maskImage: "radial-gradient(ellipse 78% 74% at 50% 55%, black 50%, rgba(0, 0, 0, 0.85) 70%, transparent 98%)",
      }
    : {
        mixBlendMode: "screen",
        filter: VIDEO_FILTER,
        WebkitMaskImage: "radial-gradient(ellipse 78% 74% at 50% 55%, black 50%, rgba(0, 0, 0, 0.85) 70%, transparent 98%)",
        maskImage: "radial-gradient(ellipse 78% 74% at 50% 55%, black 50%, rgba(0, 0, 0, 0.85) 70%, transparent 98%)",
      };

  return (
    <video
      key={clipKey}
      ref={videoRef}
      src={src}
      loop
      muted
      playsInline
      autoPlay
      className={`absolute inset-0 h-full w-full object-contain object-bottom transition-opacity duration-300 ease-out will-change-[opacity] ${clipVisibilityClass(active)}`}
      style={videoStyle}
      onLoadedData={(e) => onLoaded(e.target as HTMLVideoElement)}
      onError={(e) => onError(e.target as HTMLVideoElement)}
    />
  );
}

export const WilcoCoreVisualizer: React.FC<WilcoCoreVisualizerProps> = ({
  state,
  themeColor,
  activeEmotion = "idle",
  characterState,
  backgroundVideo,
  avatarStyle,
  voiceId = "ava",
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationRef = useRef<number | null>(null);
  const idleVideoRef = useRef<HTMLVideoElement | null>(null);
  const thinkingVideoRef = useRef<HTMLVideoElement | null>(null);
  const talkingVideoRef = useRef<HTMLVideoElement | null>(null);
  const [displayedVoice, setDisplayedVoice] = useState<string>(voiceId);
  const [walkDirection, setWalkDirection] = useState<number>(1);
  const characterContainerRef = useRef<HTMLDivElement | null>(null);
  const [clipVersion, setClipVersion] = useState<number>(0);
  const [deadClips, setDeadClips] = useState<Set<CharacterClipState>>(new Set());
  const mouseRef = useRef<{ x: number; y: number }>({ x: 0.5, y: 0.4 });
  const targetMouseRef = useRef<{ x: number; y: number }>({ x: 0.5, y: 0.4 });
  const speechVolumeRef = useRef<number>(0);
  const glowRingRef = useRef<number>(0);
  const emotionFlashRef = useRef<number>(0);
  const lastEmotionRef = useRef<WilcoEmotion>(activeEmotion);
  const particlesRef = useRef<Particle[]>([]);

  const character = useMemo(() => getCharacter(displayedVoice), [displayedVoice]);
  const glowColors = useMemo(
    () => getGlowColors(themeColor, avatarStyle, displayedVoice),
    [themeColor, avatarStyle, displayedVoice],
  );

  useEffect(() => {
    if (voiceId === displayedVoice) {
      return;
    }
    const direction = characterSeat(voiceId) >= characterSeat(displayedVoice) ? 1 : -1;
    setWalkDirection(direction);
    setDisplayedVoice(voiceId);
    setDeadClips(new Set());
  }, [voiceId, displayedVoice]);

  const handleClipError = useCallback((clipState: CharacterClipState, src: string | null) => {
    if (src) {
      noteClip(src, false);
    }
    if (!src || src.startsWith("/assets/videos/")) {
      setClipVersion((v) => v + 1);
    } else {
      setDeadClips((prev) => {
        if (prev.has(clipState)) {
          return prev;
        }
        return new Set(prev).add(clipState);
      });
    }
  }, []);

  const handleClipLoaded = useCallback((el: HTMLVideoElement) => {
    noteClip(el.getAttribute("src") || "", true);
  }, []);

  const handleClipFailed = useCallback(
    (clipState: CharacterClipState) => (el: HTMLVideoElement) => {
      handleClipError(clipState, el.getAttribute("src"));
    },
    [handleClipError],
  );

  const clipSrc = useCallback(
    (clipState: CharacterClipState): string => characterClip(character, clipState) || `/assets/${clipState}.webm`,
    [character],
  );

  useEffect(() => {
    if (avatarStyle !== "character") {
      return;
    }
    let raf = 0;
    let lastUpdate = 0;
    const tick = (now: number) => {
      const talking = talkingVideoRef.current;
      if (talking && talking.readyState >= 2) {
        if (characterState === "talking") {
          // Throttle rate changes to at most once per 120ms and significant delta to prevent decoder pipeline thrashing
          if (now - lastUpdate > 120) {
            const env = envelope();
            const targetRate = env < 0.15 ? 0.6 : 0.9 + env * 0.4;
            if (Math.abs(talking.playbackRate - targetRate) > 0.15) {
              talking.playbackRate = targetRate;
              lastUpdate = now;
            }
          }
        } else if (talking.playbackRate !== 1) {
          talking.playbackRate = 1;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (talkingVideoRef.current) {
        talkingVideoRef.current.playbackRate = 1;
      }
    };
  }, [characterState, avatarStyle, displayedVoice]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      targetMouseRef.current = {
        x: e.clientX / window.innerWidth,
        y: e.clientY / window.innerHeight,
      };
    };
    window.addEventListener("mousemove", handleMouseMove);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }
    let width = canvas.width = canvas.offsetWidth;
    let height = canvas.height = canvas.offsetHeight;
    particlesRef.current = createParticles(width, height);

    const handleResize = () => {
      width = canvas.width = canvas.offsetWidth;
      height = canvas.height = canvas.offsetHeight;
      particlesRef.current = createParticles(width, height);
    };
    window.addEventListener("resize", handleResize);

    const renderFrame = () => {
      ctx.clearRect(0, 0, width, height);
      const time = performance.now();
      const rawLevel = computeRawLevel(state, time);
      speechVolumeRef.current += (rawLevel - speechVolumeRef.current) * 0.22;
      const vol = speechVolumeRef.current;
      if (lastEmotionRef.current !== activeEmotion) {
        emotionFlashRef.current = 1;
        lastEmotionRef.current = activeEmotion;
      }
      emotionFlashRef.current *= 0.96;
      const targetRing = computeTargetRing(state, vol);
      glowRingRef.current += (targetRing - glowRingRef.current) * 0.15;
      mouseRef.current.x += (targetMouseRef.current.x - mouseRef.current.x) * 0.05;
      mouseRef.current.y += (targetMouseRef.current.y - mouseRef.current.y) * 0.05;
      const centerX = width >= 768 ? width * 0.58 : width / 2;
      const container = characterContainerRef.current;
      if (avatarStyle !== "orb" && container) {
        applyCharacterMotion(container, { liveState: state, characterState, vol, time });
      }
      drawParticles(ctx, particlesRef.current, width, height, time);
      const ringY = height - 35;
      const pulse = 1 + 0.02 * Math.sin(time * 0.002);
      const boost = 1 + glowRingRef.current * 0.35;
      const radius = width * 0.18 * pulse * boost;
      const frame: PedestalFrame = {
        ctx, centerX, ringY, ringRadius: radius, pulse, boost, glow: glowRingRef.current,
      };
      if (avatarStyle !== "orb") {
        const liveChar = getCharacter(displayedVoice);
        drawPedestalCharacter(frame, liveChar);
      } else {
        drawPedestalOrb(frame, glowColors);
      }
      drawScanlines(ctx, width, height, time);
      drawGrid(ctx, width, height);
      drawRays(ctx, centerX, ringY, radius, time, glowRingRef.current);
      animationRef.current = requestAnimationFrame(renderFrame);
    };
    renderFrame();
    return () => {
      window.removeEventListener("resize", handleResize);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [state, activeEmotion, characterState, avatarStyle, displayedVoice, glowColors]);

  const showImageStage = avatarStyle === "image";
  const showVideoStage = avatarStyle === "character";
  const showOrbStage = avatarStyle === "orb";
  const allClipsDead = deadClips.size >= 3;

  return (
    <div className="relative w-full h-full flex items-center justify-center overflow-hidden">
      <StageBackground
        themeColor={themeColor}
        avatarStyle={avatarStyle}
        backgroundVideo={backgroundVideo}
        characterState={characterState}
      />
      <div className="absolute inset-0 z-8 pointer-events-none">
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[60vw] h-[60vh] bg-linear-to-t from-indigo-900/10 via-transparent to-transparent blur-[60px]" />
      </div>
      <canvas
        id="wilco-hologram-living-canvas"
        ref={canvasRef}
        className="absolute inset-0 w-full h-full pointer-events-none z-6"
      />
      <div
        id="wilco-animated-presence"
        className="absolute inset-0 z-10 w-full h-full pointer-events-auto transform-[translateZ(0)]"
      >
        <div className="relative w-full h-full select-none pointer-events-none overflow-hidden">
          {showImageStage && (
            <div className="absolute inset-0 flex items-end justify-center md:justify-[58%] pointer-events-none overflow-hidden">
              <WalkShell walkKey={displayedVoice} walkDirection={walkDirection}>
                <div
                  ref={characterContainerRef}
                  className="relative will-change-transform transition-[filter] duration-300"
                  style={{ filter: getCharacterFilter(characterState) }}
                >
                  <img
                    src={character.image}
                    alt={character.name}
                    loading="eager"
                    decoding="async"
                    className="h-[78vh] max-h-205 w-auto object-contain object-bottom select-none pointer-events-none drop-shadow-[0_15px_35px_rgba(0,0,0,0.7)]"
                    draggable={false}
                  />
                  <div
                    className="absolute inset-0 -z-10 blur-[85px] transition-opacity duration-300"
                    style={{
                      background: `radial-gradient(ellipse at center bottom, ${hexToRgba(character.accent, 0.35)} 0%, transparent 70%)`,
                      opacity: characterState === "talking" || state === "listening" ? 1 : 0.45,
                    }}
                  />
                  <CharacterBadge character={character} />
                </div>
              </WalkShell>
            </div>
          )}
          {showVideoStage && (
            <div className="absolute inset-0 flex items-end justify-center md:justify-[58%] pointer-events-none overflow-hidden">
              <WalkShell walkKey={displayedVoice} walkDirection={walkDirection}>
                <div
                  ref={characterContainerRef}
                  className="relative flex flex-col items-center select-none h-[82vh] max-h-215 aspect-video will-change-transform transition-[filter] duration-300"
                  style={{ filter: getVideoFilter(characterState) }}
                >
                  <div
                    className="absolute inset-0 -z-10 blur-[85px] transition-opacity duration-300 pointer-events-none"
                    style={{
                      background: `radial-gradient(ellipse at center bottom, ${hexToRgba(character.accent, 0.45)} 0%, transparent 70%)`,
                      opacity: characterState === "talking" || state === "listening" ? 1 : 0.5,
                    }}
                  />
                  <ClipVideo
                    clipState="idle"
                    activeState={characterState}
                    src={clipSrc("idle")}
                    isDead={deadClips.has("idle")}
                    clipKey={`idle-${displayedVoice}-${clipVersion}`}
                    videoRef={idleVideoRef}
                    onLoaded={handleClipLoaded}
                    onError={handleClipFailed("idle")}
                  />
                  <ClipVideo
                    clipState="thinking"
                    activeState={characterState}
                    src={clipSrc("thinking")}
                    isDead={deadClips.has("thinking")}
                    clipKey={`thinking-${displayedVoice}-${clipVersion}`}
                    videoRef={thinkingVideoRef}
                    onLoaded={handleClipLoaded}
                    onError={handleClipFailed("thinking")}
                  />
                  <ClipVideo
                    clipState="talking"
                    activeState={characterState}
                    src={clipSrc("talking")}
                    isDead={deadClips.has("talking")}
                    clipKey={`talking-${displayedVoice}-${clipVersion}`}
                    videoRef={talkingVideoRef}
                    onLoaded={handleClipLoaded}
                    onError={handleClipFailed("talking")}
                  />
                  <div className="absolute -bottom-2 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 z-20 pointer-events-none">
                    <span
                      className="text-[10px] font-mono font-bold tracking-[0.3em] uppercase px-4 py-1 rounded-full border backdrop-blur-xl shadow-lg"
                      style={{
                        color: character.accentGlow,
                        borderColor: hexToRgba(character.accent, 0.4),
                        backgroundColor: hexToRgba(character.accent, 0.15),
                      }}
                    >
                      {character.name}
                    </span>
                  </div>
                </div>
              </WalkShell>
              {allClipsDead && (
                <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#05060f]/90 backdrop-blur-md rounded-3xl p-6 text-center z-50 pointer-events-auto border border-white/5 shadow-2xl">
                  <Sparkles className="text-cyan-400 mb-2 animate-pulse" size={32} />
                  <h3 className="text-sm font-bold tracking-widest font-mono text-white select-none">AWAITING VIDEO CORES</h3>
                  <p className="text-xs text-slate-400 mt-2 max-w-xs leading-relaxed font-sans">
                    Place your character video assets inside the <code className="text-cyan-300 font-mono">/assets/videos</code> directory
                    (or the shared <code className="text-cyan-300 font-mono">/assets</code> set).
                  </p>
                </div>
              )}
            </div>
          )}
          {showOrbStage && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <img
                src="/assets/orb2.gif"
                alt="Aegis Core"
                className={`transition-all duration-700 ease-in-out object-contain w-full h-full ${getOrbClass(characterState)}`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
