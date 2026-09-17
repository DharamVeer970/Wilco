import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import type { LiveState } from "./lib/audio";
import { WilcoCoreVisualizer } from "./components/CoreVisualizer";
import type { WilcoEmotion } from "./components/CoreVisualizer";
import { saveSettings, loadSettings } from "./lib/settingsStore";
import type { Settings } from "./lib/settingsStore";
import type { Memory, MemoryCategory } from "./lib/memoryTypes";
import { WilcoWakeWordDetector } from "./lib/wakeWord";
import { onSpeakEvent, onSpeedEvent } from "./lib/speechbus";
import type { SpeakPhase } from "./lib/speechbus";
import { characterForVoice } from "./lib/characters";
import { log, warn, error as logError } from "./lib/logger";
import { BrowserAgent } from "./components/BrowserAgent";
import { MemoryDashboard } from "./components/MemoryDashboard";
import { TranscriptPanel } from "./components/TranscriptPanel";
import type { TranscriptEntry } from "./components/TranscriptPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { useToast, ToastContainer } from "./components/Toast";
import { SudoPopup } from "./components/SudoPopup";
import { TextChatFallback } from "./components/TextChatFallback";
import { motion, AnimatePresence } from "motion/react";
import {
  Compass,
  Brain,
  Monitor,
  Settings as SettingsIcon,
  X,
  CircleAlert,
  Power,
  Mic,
  Volume2,
  Square,
  MessageSquare,
} from "lucide-react";

type CharacterVisualState = "idle" | "thinking" | "talking";
type SubtitleKind = "model" | "user" | "status";

interface TerminalLog {
  id: string;
  tool: string;
  args: unknown;
  output: string;
  time: number;
}

interface BrowserTrigger {
  type: string;
  args: Record<string, unknown>;
  id: string;
  callback: (res: unknown) => void;
}

interface PendingRequest {
  id: string;
  command: string;
  package?: string;
  requestedBy: string;
  timestamp: Date;
  expiresAt: Date;
  status: "pending";
}

/** Display-safe string conversion: objects become JSON, never "[object Object]". */
function stringifyForDisplay(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  if (value instanceof Error) {
    return value.message;
  }
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}

function textLengthOf(value: unknown): number | undefined {
  if (typeof value === "string") {
    return value.length;
  }
  return undefined;
}

function toDisplayPackage(payload: unknown): string | undefined {
  if (payload === null || payload === undefined) {
    return undefined;
  }
  if (typeof payload === "string") {
    return payload;
  }
  try {
    return JSON.stringify(payload);
  } catch {
    return undefined;
  }
}

const WAVE_BASES = [10, 24, 14, 28, 18, 8] as const;
const MAX_TERMINAL_LOGS = 50;
const AMBIENT_CLASS = "from-black/40 via-transparent to-black/60";

let idCounter = 0;

/** Secure unique id for transcript / terminal rows. No Math.random involved. */
function createId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  idCounter += 1;
  return `${prefix}-${Date.now()}-${idCounter}`;
}

const EMOTION_RULES: Array<{ emotion: WilcoEmotion; keys: string[] }> = [
  { emotion: "playful", keys: ["haha", "lol", "funny", "joke", "hehe", "wink"] },
  { emotion: "happy", keys: ["happy", "harmony", "glad", "joy", "wonderful", "love", "smile"] },
  { emotion: "excited", keys: ["wow", "awesome", "excited", "amazing", "yay", "incredible", "hype"] },
  { emotion: "curious", keys: ["really?", "curious", "interest", "tell me more", "why", "how", "wonder"] },
  { emotion: "thinking", keys: ["think", "calculat", "analyz", "hmmm", "process", "let me see", "conclude"] },
  { emotion: "proud", keys: ["proud", "achieved", "expert", "skill", "confidence", "succeed"] },
  { emotion: "sad", keys: ["sad", "sorry", "unfortunate", "grief", "bad", "regret", "alas", "cry"] },
  { emotion: "surprised", keys: ["shock", "surprise", "gasp", "unexpected", "seriously", "oh my"] },
  { emotion: "embarrassed", keys: ["blush", "shy", "embarrass", "nervous", "oops", "sorry about"] },
  { emotion: "confused", keys: ["what?", "confus", "puzzled", "dont know", "not sure", "wait"] },
];

function detectEmotionFromText(text: string): WilcoEmotion {
  const lower = text.toLowerCase();
  for (const rule of EMOTION_RULES) {
    if (rule.keys.some((k) => lower.includes(k))) {
      return rule.emotion;
    }
  }
  return "idle";
}

function getWaveBarClass(state: LiveState): string {
  if (state === "speaking") {
    return "bg-purple-500 shadow-[0_0_8px_rgba(168,85,247,0.5)]";
  }
  if (state === "listening") {
    return "bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.5)]";
  }
  return "bg-slate-600";
}

function getStateDotClass(state: LiveState): string {
  if (state === "speaking") {
    return "bg-purple-400 animate-ping shadow-[0_0_8px_rgba(168,85,247,0.8)]";
  }
  if (state === "listening") {
    return "bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.8)]";
  }
  if (state === "connecting") {
    return "bg-amber-400 animate-spin shadow-[0_0_8px_rgba(251,191,36,0.8)]";
  }
  return "bg-slate-500";
}

function getSpeakerLabel(state: LiveState, voiceName: string): string {
  if (state === "speaking") {
    return `${characterForVoice(voiceName).name} Speaking`;
  }
  if (state === "listening") {
    return "User Speaking";
  }
  if (state === "connecting") {
    return "Linking Neural Core";
  }
  return "Wilco AI Core";
}

function getPowerButtonClass(state: LiveState): string {
  if (state === "disconnected") {
    return "border border-white/20 text-slate-300 hover:text-white hover:scale-105 bg-white/5 hover:bg-white/10 hover:border-white/40";
  }
  if (state === "listening") {
    return "border border-cyan-400/50 text-cyan-300 hover:scale-105 bg-cyan-950/40 shadow-[0_0_25px_rgba(34,211,238,0.4)]";
  }
  if (state === "speaking") {
    return "border border-purple-400/50 text-purple-300 hover:scale-105 bg-purple-950/40 shadow-[0_0_25px_rgba(168,85,247,0.4)]";
  }
  return "border border-amber-400/50 text-amber-400 animate-spin bg-black/40";
}

function getSubtitle(state: LiveState, userCaption: string, modelCaption: string): { kind: SubtitleKind; text: string } {
  if (modelCaption) {
    return { kind: "model", text: modelCaption };
  }
  if (userCaption) {
    return { kind: "user", text: userCaption };
  }
  if (state === "listening") {
    return { kind: "status", text: "I am listening. Speak freely..." };
  }
  if (state === "connecting") {
    return { kind: "status", text: "Materializing presence links..." };
  }
  return { kind: "status", text: "Connect memory core to awaken my voice." };
}

function getConnectionLabel(isConnected: boolean, state: LiveState): string {
  if (!isConnected) {
    return "OFFLINE";
  }
  if (state === "disconnected") {
    return "IDLE";
  }
  return state;
}

function stopRecognizer(ref: React.RefObject<{ stop?: () => void } | null>): void {
  try {
    ref.current?.stop?.();
  } catch {
    // Already stopped — closing the mic is idempotent.
  }
}

function parseJson(data: string): Record<string, never> | null {
  try {
    const value = JSON.parse(data);
    if (value !== null && typeof value === "object") {
      return value;
    }
    return null;
  } catch {
    return null;
  }
}

/** Waveform bars that animate on their own clock — rAF straight onto style, never a re-render. */
function WaveBars({ state }: Readonly<{ state: LiveState }>) {
  const barsRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const bars = barsRef.current?.children;
    if (state !== "speaking" && state !== "listening") {
      if (bars) {
        for (let i = 0; i < bars.length; i++) {
          const base = WAVE_BASES[i] ?? 12;
          const factor = i % 2 === 0 ? 0.25 : 0.12;
          (bars[i] as HTMLElement).style.height = `${Math.max(4, base * factor)}px`;
        }
      }
      return;
    }
    let raf = 0;
    const tick = () => {
      if (bars) {
        const now = performance.now();
        for (let i = 0; i < bars.length; i++) {
          const base = WAVE_BASES[i] ?? 12;
          let factor = i % 2 === 0 ? 0.25 : 0.12;
          if (state === "speaking") {
            factor = 0.35 + Math.abs(Math.sin(now * 0.02 + i * 0.9)) * 0.65;
          } else if (state === "listening") {
            factor = 0.2 + Math.sin(now * 0.01 + i * 0.5) * 0.4;
          }
          (bars[i] as HTMLElement).style.height = `${Math.max(4, base * factor)}px`;
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state]);
  const barClass = getWaveBarClass(state);
  return (
    <div ref={barsRef} className="flex items-center gap-1.5 h-7">
      {WAVE_BASES.map((base) => (
        <div
          key={`wave-${base}`}
          className={`w-1 rounded-full transition-colors duration-300 ${barClass}`}
          style={{ height: `${Math.max(4, base * 0.25)}px` }}
        />
      ))}
    </div>
  );
}

function PowerIcon({ state }: Readonly<{ state: LiveState }>) {
  if (state === "disconnected") {
    return <Power size={20} className="opacity-80" />;
  }
  if (state === "connecting") {
    return <div className="w-5 h-5 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />;
  }
  if (state === "listening") {
    return <Mic size={20} />;
  }
  return <Volume2 size={20} />;
}

function SubtitleView({ subtitle }: Readonly<{ subtitle: { kind: SubtitleKind; text: string } }>) {
  if (subtitle.kind === "model") {
    return (
      <p className="text-sm sm:text-base font-normal text-white leading-relaxed tracking-wide font-sans">
        {subtitle.text}
      </p>
    );
  }
  if (subtitle.kind === "user") {
    return (
      <p className="text-cyan-300 font-mono text-xs sm:text-sm tracking-wide leading-relaxed flex items-start gap-2">
        <span className="mt-1 w-1.5 h-1.5 rounded-full bg-cyan-400 shrink-0 shadow-[0_0_6px_cyan]" />
        <span>&ldquo;{subtitle.text}&rdquo;</span>
      </p>
    );
  }
  return (
    <span className="text-[11px] sm:text-xs font-mono tracking-wider text-slate-400 leading-relaxed">
      {subtitle.text}
    </span>
  );
}

const GUIDE_ITEMS = [
  { quote: "Wilco, change atmosphere of your core to crimson", hint: "Shifts theme color background" },
  { quote: "Open youtube.com on my screen please", hint: "Invokes browser projector panel" },
  { quote: "Tell me a witty joke and change background to gold", hint: "Combines tools & voice" },
] as const;

function GuidePanel({ onClose }: Readonly<{ onClose: () => void }>) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95, y: 10 }}
      className="mt-6 p-5 rounded-3xl border border-white/10 bg-white/5 backdrop-blur-3xl max-w-md text-left w-full absolute z-40 shadow-[0_8px_32px_rgba(0,0,0,0.6)]"
    >
      <div className="flex items-center justify-between mb-3 text-white">
        <div className="flex items-center gap-1.5 font-display text-sm font-bold tracking-wide">
          <Compass size={16} className="text-cyan-400" />
          <span>PLAYFUL CORE SUGGESTIONS</span>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-white transition" aria-label="Close guide">
          <X size={14} />
        </button>
      </div>
      <p className="text-xs text-slate-300 mb-4 font-mono leading-relaxed">
        Wilco is equipped with dynamic visual modules and browser projectors. Here are clever triggers to try speaking aloud:
      </p>
      <div className="space-y-2 text-xs font-serif italic text-cyan-300">
        {GUIDE_ITEMS.map((item) => (
          <div
            key={item.quote}
            className="p-2.5 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition cursor-pointer font-sans normal-case text-slate-200"
          >
            ⚡ &quot;{item.quote}&quot;{" "}
            <span className="text-[10px] font-mono text-cyan-500 block mt-0.5 font-bold">{item.hint}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

function ToggleButton({
  active,
  onToggle,
  title,
  activeClass,
  children,
}: Readonly<{
  active: boolean;
  onToggle: () => void;
  title: string;
  activeClass: string;
  children: React.ReactNode;
}>) {
  const cls = active ? activeClass : "text-slate-400 hover:text-white hover:bg-white/10";
  return (
    <button
      onClick={onToggle}
      className={`p-2.5 rounded-full transition-all duration-300 ${cls}`}
      title={title}
      aria-pressed={active}
    >
      {children}
    </button>
  );
}

export default function App() {
  const [settings, setSettings] = useState<Settings>(() => loadSettings());
  const [state, setState] = useState<LiveState>("disconnected");
  const [terminalLogs, setTerminalLogs] = useState<TerminalLog[]>([]);
  const [showTerminal, setShowTerminal] = useState(false);
  const terminalRef = useRef<HTMLDivElement>(null);
  const [activeEmotion, setActiveEmotion] = useState<WilcoEmotion>("idle");
  const [themeColor] = useState<string>("charcoal");
  const [userCaption, setUserCaption] = useState<string>("");
  const [characterState, setCharacterState] = useState<CharacterVisualState>("idle");
  const [modelCaption, setModelCaption] = useState<string>("");
  const [activeProjectorUrl, setActiveProjectorUrl] = useState<string | null>(null);
  const [showGuide, setShowGuide] = useState<boolean>(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [browserTrigger, setBrowserTrigger] = useState<BrowserTrigger | null>(null);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [showMemoryDashboard, setShowMemoryDashboard] = useState<boolean>(false);
  const [showTranscriptPanel, setShowTranscriptPanel] = useState<boolean>(false);
  const [transcriptEntries, setTranscriptEntries] = useState<TranscriptEntry[]>([]);
  const { toasts, dismiss } = useToast();
  const [showSettings, setShowSettings] = useState<boolean>(false);
  const showSettingsRef = useRef<boolean>(false);
  const [isBackendConnected, setIsBackendConnected] = useState<boolean>(false);
  const [pendingRequests, setPendingRequests] = useState<PendingRequest[]>([]);
  const [showChatFallback, setShowChatFallback] = useState<boolean>(false);
  const [isListeningInBrowser, setIsListeningInBrowser] = useState<boolean>(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const speechRecognitionRef = useRef<{ stop?: () => void } | null>(null);
  const wakeDetectorRef = useRef<WilcoWakeWordDetector | null>(null);
  const connectHandlerRef = useRef<() => void>(() => {});

  useEffect(() => {
    showSettingsRef.current = showSettings;
  }, [showSettings]);

  useEffect(() => {
    wakeDetectorRef.current ??= new WilcoWakeWordDetector();
    const det = wakeDetectorRef.current;
    return () => {
      det.stop();
    };
  }, []);

  useEffect(() => {
    const det = wakeDetectorRef.current;
    if (!det) {
      return;
    }
    const shouldListen = settings.wakeWordEnabled && state === "disconnected";
    if (shouldListen) {
      det.start({
        phrase: settings.wakePhrase,
        sensitivity: settings.sensitivity,
        onTriggered: () => {
          det.stop();
          connectHandlerRef.current();
        },
      });
    } else {
      det.stop();
    }
  }, [settings.wakeWordEnabled, settings.wakePhrase, settings.sensitivity, state]);

  const handleSettingsChange = useCallback((patch: Partial<Settings>) => {
    const next = saveSettings(patch);
    setSettings(next);
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/memories")
      .then((res) => res.json())
      .then((data: unknown) => {
        if (!cancelled && Array.isArray(data)) {
          setMemories(data as Memory[]);
        }
      })
      .catch((err: unknown) => logError("Initial persistent recollections load failure:", err));
    return () => {
      cancelled = true;
    };
  }, []);

  const handleAddManualMemory = useCallback(async (category: MemoryCategory, text: string) => {
    try {
      const resp = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, text }),
      });
      const saved = (await resp.json()) as Partial<Memory> | null;
      if (saved?.id) {
        setMemories((prev) => [...prev, saved as Memory]);
      }
    } catch (err) {
      logError("Manual database recollect upload error:", err);
    }
  }, []);

  const handleDeleteMemory = useCallback(async (id: string) => {
    try {
      const resp = await fetch(`/api/memories/${id}`, { method: "DELETE" });
      const resObj = (await resp.json()) as { success?: boolean };
      if (resObj?.success) {
        setMemories((prev) => prev.filter((m) => m.id !== id));
      }
    } catch (err) {
      logError("Manual memory delete execution failed:", err);
    }
  }, []);

  const submitCommand = useCallback(async (text: string) => {
    const clean = text.trim();
    if (!clean) {
      return;
    }
    setUserCaption(clean);
    setModelCaption("");
    setCharacterState("thinking");
    try {
      const resp = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean }),
      });
      const data = (await resp.json()) as { ok?: boolean; error?: string };
      if (!data.ok && data.error) {
        setErrorText(data.error);
      }
    } catch (err) {
      logError("Command submit error:", err);
      setErrorText("Failed to send command to Wilco backend");
    }
  }, []);

  const handleVoiceChange = useCallback(
    async (voiceName: string) => {
      handleSettingsChange({ voice: voiceName });
      try {
        await fetch("/api/voice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ voice: voiceName }),
        });
      } catch (err) {
        logError("Voice change failed:", err);
      }
    },
    [handleSettingsChange],
  );

  const handleApproveSudo = useCallback(async (token: string) => {
    try {
      await fetch("/api/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve: true, token }),
      });
    } catch (err) {
      logError("Sudo approve failed:", err);
    }
    setPendingRequests([]);
  }, []);

  const handleRejectSudo = useCallback(async (token: string) => {
    try {
      await fetch("/api/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve: false, token }),
      });
    } catch (err) {
      logError("Sudo reject failed:", err);
    }
    setPendingRequests([]);
  }, []);

  const stopBrowserListening = useCallback(() => {
    stopRecognizer(speechRecognitionRef);
    setIsListeningInBrowser(false);
    setState("idle");
    setCharacterState("idle");
  }, []);

  const toggleBrowserListening = useCallback(() => {
    const SpeechRecognition =
      (window as unknown as Record<string, new () => BrowserRecognizer>).SpeechRecognition ??
      (window as unknown as Record<string, new () => BrowserRecognizer>).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setShowChatFallback(true);
      return;
    }
    if (isListeningInBrowser) {
      stopBrowserListening();
      return;
    }
    try {
      const recognizer = new SpeechRecognition();
      recognizer.continuous = false;
      recognizer.interimResults = true;
      recognizer.lang = "en-US";
      recognizer.onstart = () => {
        setIsListeningInBrowser(true);
        setState("listening");
        setCharacterState("idle");
        setUserCaption("Listening...");
      };
      recognizer.onresult = (event: SpeechResultEvent) => {
        const transcript = Array.from(event.results)
          .map((result) => result[0]?.transcript ?? "")
          .join("");
        setUserCaption(transcript);
        if (event.results[0]?.isFinal) {
          void submitCommand(transcript);
        }
      };
      recognizer.onerror = (event: { error?: unknown }) => {
        warn("Speech recognition error:", event.error);
        setIsListeningInBrowser(false);
        setState("idle");
      };
      recognizer.onend = () => {
        setIsListeningInBrowser(false);
        setCharacterState((prev) => {
          if (prev !== "thinking" && prev !== "talking") {
            setState("idle");
          }
          return prev;
        });
      };
      speechRecognitionRef.current = recognizer;
      recognizer.start();
    } catch (err) {
      logError("Speech recognition start error:", err);
      setIsListeningInBrowser(false);
      setState("idle");
    }
  }, [isListeningInBrowser, stopBrowserListening, submitCommand]);

  const handleToggleConnection = useCallback(() => {
    if (isListeningInBrowser || state === "listening") {
      stopBrowserListening();
    } else {
      toggleBrowserListening();
    }
  }, [isListeningInBrowser, state, stopBrowserListening, toggleBrowserListening]);

  useEffect(() => {
    connectHandlerRef.current = handleToggleConnection;
  }, [handleToggleConnection]);

  const appendTranscript = useCallback((entry: TranscriptEntry) => {
    setTranscriptEntries((prev) => [...prev, entry]);
  }, []);

  const appendTerminalLog = useCallback((tool: string, args: unknown, output: string) => {
    const entry: TerminalLog = { id: createId("tool"), tool, args, output: String(output), time: Date.now() };
    setTerminalLogs((prev) => [...prev, entry].slice(-MAX_TERMINAL_LOGS));
  }, []);

  useEffect(() => {
    let sse: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const handleSnapshot = (e: MessageEvent) => {
      const snap = parseJson(e.data);
      if (!snap) {
        return;
      }
      setIsBackendConnected(true);
      const snapState = (snap as { state?: LiveState }).state;
      if (snapState) {
        setState(snapState);
        if (snapState === "speaking") {
          setCharacterState("talking");
        } else if (snapState === "thinking") {
          setCharacterState("thinking");
        } else {
          setCharacterState("idle");
        }
      }
      const voice = (snap as { voice?: string }).voice;
      if (voice) {
        handleSettingsChange({ voice });
      }
    };

    const handleStateEvent = (e: MessageEvent) => {
      const data = parseJson(e.data);
      if (!data) {
        return;
      }
      const val = (data as { value?: string }).value;
      if (val === "speaking") {
        setState("speaking");
        setCharacterState("talking");
      } else if (val === "thinking") {
        setState("speaking");
        setCharacterState("thinking");
      } else if (val === "listening") {
        setState("listening");
        setCharacterState("idle");
      } else {
        setState("idle");
        setCharacterState("idle");
      }
    };

    const handleTranscript = (e: MessageEvent) => {
      const data = parseJson(e.data);
      if (!data) {
        return;
      }
      const record = data as { role?: string; text?: string };
      const text = record.text ?? "";
      if (record.role === "user") {
        setUserCaption(text);
        setModelCaption("");
        setCharacterState("thinking");
        appendTranscript({
          id: createId("tx"),
          timestamp: new Date().toLocaleTimeString(),
          role: "user",
          content: text,
        });
      } else {
        setUserCaption("");
        setModelCaption(text);
        const emo = detectEmotionFromText(text);
        setActiveEmotion(emo);
        appendTranscript({
          id: createId("tx"),
          timestamp: new Date().toLocaleTimeString(),
          role: "model",
          content: text,
          emotion: emo,
        });
      }
    };

    const handleSpeakBus = (e: MessageEvent) => {
      const ev = parseJson(e.data);
      if (!ev) {
        return;
      }
      const record = ev as { phase?: string; length?: number; text?: unknown };
      const phase = record.phase as SpeakPhase | undefined;
      if (phase === "start" || phase === "chunk" || phase === "end") {
        const length = record.length ?? textLengthOf(record.text);
        onSpeakEvent({ phase, length });
        if (phase === "end") {
          setCharacterState("idle");
          setState("idle");
        }
      }
    };

    const handleSpeed = (e: MessageEvent) => {
      const data = parseJson(e.data);
      if (!data) {
        return;
      }
      const record = data as { speed?: unknown; value?: unknown };
      const raw = record.speed ?? record.value ?? 0;
      const value = Number(raw);
      onSpeedEvent(Number.isFinite(value) ? value : 0);
    };

    const handleTool = (e: MessageEvent) => {
      const data = parseJson(e.data);
      if (!data) {
        return;
      }
      const record = data as { name?: string; args?: unknown; result?: unknown; error?: unknown; status?: unknown };
      const toolName = record.name ?? "tool";
      const toolArgs = record.args ?? {};
      const toolOutput = record.result ?? record.error ?? record.status ?? "";
      appendTerminalLog(toolName, toolArgs, stringifyForDisplay(toolOutput));
    };

    const handleConfirm = (e: MessageEvent) => {
      const data = parseJson(e.data);
      if (!data) {
        return;
      }
      const record = data as { token?: string; action?: string; payload?: unknown };
      const req: PendingRequest = {
        id: record.token ?? String(Date.now()),
        command: record.action ?? "Action Requires Approval",
        package: toDisplayPackage(record.payload),
        requestedBy: "Wilco AI",
        timestamp: new Date(),
        expiresAt: new Date(Date.now() + 60000),
        status: "pending",
      };
      setPendingRequests((prev) => [...prev.filter((p) => p.id !== req.id), req]);
    };

    const handleVoice = (e: MessageEvent) => {
      const data = parseJson(e.data);
      const name = (data as { name?: string } | null)?.name;
      if (name) {
        handleSettingsChange({ voice: name });
      }
    };

    const connectSSE = () => {
      sse = new EventSource("/api/events");
      eventSourceRef.current = sse;
      sse.onopen = () => {
        log("[Wilco SSE] Connected to /api/events");
        setIsBackendConnected(true);
        setErrorText(null);
      };
      sse.addEventListener("snapshot", handleSnapshot);
      sse.addEventListener("state", handleStateEvent);
      sse.addEventListener("transcript", handleTranscript);
      sse.addEventListener("speak", handleSpeakBus);
      sse.addEventListener("speed", handleSpeed);
      sse.addEventListener("tool", handleTool);
      sse.addEventListener("confirm", handleConfirm);
      sse.addEventListener("voice", handleVoice);
      sse.addEventListener("error", () => {
        setIsBackendConnected(false);
        sse?.close();
        reconnectTimer = setTimeout(connectSSE, 3000);
      });
    };

    connectSSE();
    return () => {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      sse?.close();
    };
  }, [appendTerminalLog, appendTranscript, handleSettingsChange]);

  const subtitle = useMemo(() => getSubtitle(state, userCaption, modelCaption), [state, userCaption, modelCaption]);
  const speakerLabel = useMemo(() => getSpeakerLabel(state, settings.voice), [state, settings.voice]);
  const connectionLabel = useMemo(() => getConnectionLabel(isBackendConnected, state), [isBackendConnected, state]);

  const resetProjection = useCallback(() => {
    setActiveProjectorUrl(null);
    setErrorText(null);
  }, []);

  const closeProjector = useCallback(() => {
    setActiveProjectorUrl(null);
    setBrowserTrigger(null);
  }, []);

  const handleChatSubmit = useCallback(
    (msg: string) => {
      void submitCommand(msg);
      setShowChatFallback(false);
    },
    [submitCommand],
  );

  const truncatedLogs = useMemo(
    () =>
      terminalLogs.map((entry) => ({
        ...entry,
        display: entry.output.length > 300 ? `${entry.output.slice(0, 300)}...` : entry.output,
      })),
    [terminalLogs],
  );

  return (
    <div
      id="wilco-holographic-desktop"
      className={`relative w-full h-screen overflow-hidden bg-[#020817] text-white bg-linear-to-br ${AMBIENT_CLASS} theme-transition flex flex-col justify-between p-6 sm:p-10 select-none`}
    >
      <div className="absolute inset-0 pointer-events-none opacity-[0.03] bg-[url('https://www.transparenttextures.com/patterns/stardust.png')] z-0 mix-blend-screen" />
      <div className="absolute inset-0 z-0 pointer-events-none select-none">
        <WilcoCoreVisualizer
          state={state}
          themeColor={themeColor}
          activeEmotion={activeEmotion}
          characterState={characterState}
          backgroundVideo={settings.backgroundVideo}
          avatarStyle={settings.avatarStyle}
          voiceId={settings.voice}
        />
      </div>

      <div className="absolute top-6 left-6 z-40 flex items-center gap-2.5 px-4 py-2 rounded-full border border-white/10 bg-black/40 backdrop-blur-3xl shadow-[0_8px_32px_rgba(0,0,0,0.6)]">
        <div
          className={`w-2 h-2 rounded-full ${isBackendConnected ? "bg-cyan-400 shadow-[0_0_10px_cyan] animate-pulse" : "bg-rose-500"}`}
        />
        <span className="text-xs font-mono font-bold tracking-[0.2em] uppercase text-white">
          WILCO <span className="text-cyan-400">AI</span>
        </span>
        <span className="text-[9px] font-mono px-2 py-0.5 rounded bg-white/5 text-slate-400 uppercase tracking-widest border border-white/5 font-semibold">
          {isBackendConnected ? "ONLINE" : "OFFLINE"}
        </span>
      </div>

      <main className="relative z-10 flex-1 w-full max-w-4xl mx-auto flex flex-col items-center justify-between py-6">
        <div className="h-10 sm:h-20" />
        <AnimatePresence>
          {showGuide && <GuidePanel onClose={() => setShowGuide(false)} />}
        </AnimatePresence>
        <AnimatePresence>
          {errorText && (
            <motion.div
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 15 }}
              className="mt-6 flex items-start gap-3 p-4 rounded-2xl border border-rose-300 bg-rose-50/80 backdrop-blur-xl max-w-md w-full text-left shadow-lg"
            >
              <CircleAlert className="text-rose-600 shrink-0 mt-0.5" size={18} />
              <div>
                <h4 className="text-xs font-bold uppercase tracking-widest text-rose-700 font-mono">Core Error Protocol</h4>
                <p className="text-xs text-rose-600 mt-1 leading-relaxed font-bold">{errorText}</p>
                <button
                  onClick={() => setErrorText(null)}
                  className="mt-2 text-[10px] font-bold text-rose-500 underline font-mono uppercase hover:text-rose-700"
                >
                  Dismiss Code
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      <div className="absolute top-6 right-6 z-40">
        <div className="flex items-center p-1.5 gap-1 rounded-full border border-white/10 bg-black/40 backdrop-blur-3xl shadow-[0_8px_32px_rgba(0,0,0,0.6)]">
          <ToggleButton
            active={showGuide}
            onToggle={() => setShowGuide((v) => !v)}
            title="Topics"
            activeClass="bg-white/15 text-white"
          >
            <Compass size={18} />
          </ToggleButton>
          <div className="w-px h-4 bg-white/10 mx-1" />
          <ToggleButton
            active={showMemoryDashboard}
            onToggle={() => setShowMemoryDashboard((v) => !v)}
            title="Recalls"
            activeClass="bg-white/15 text-white"
          >
            <Brain size={18} />
          </ToggleButton>
          <div className="w-px h-4 bg-white/10 mx-1" />
          <ToggleButton
            active={showTerminal}
            onToggle={() => setShowTerminal((v) => !v)}
            title="Terminal Logs"
            activeClass="text-emerald-400 bg-emerald-500/20 shadow-[0_0_15px_rgba(52,211,153,0.4)]"
          >
            <Square size={14} />
          </ToggleButton>
          <div className="w-px h-4 bg-white/10 mx-1" />
          <ToggleButton
            active={showTranscriptPanel}
            onToggle={() => setShowTranscriptPanel((v) => !v)}
            title="Live Transcripts"
            activeClass="text-cyan-400 bg-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.4)]"
          >
            <Monitor size={18} />
          </ToggleButton>
          <div className="w-px h-4 bg-white/10 mx-1" />
          <ToggleButton
            active={showSettings}
            onToggle={() => setShowSettings((v) => !v)}
            title="Settings"
            activeClass="text-indigo-400 bg-indigo-500/20 shadow-[0_0_15px_rgba(99,102,241,0.4)]"
          >
            <SettingsIcon size={18} className={showSettings ? "animate-spin [animation-duration:6s]" : ""} />
          </ToggleButton>
        </div>
      </div>

      <div className="absolute bottom-8 sm:bottom-12 left-6 sm:left-12 z-40 flex flex-col items-start gap-3.5 max-w-sm sm:max-w-md lg:max-w-lg pointer-events-auto select-none">
        <div
          id="cinematic-subtitles"
          className="w-full rounded-2xl border border-white/10 bg-black/65 backdrop-blur-2xl p-4 sm:p-5 shadow-[0_12px_40px_rgba(0,0,0,0.8)] flex flex-col gap-2.5 transition-all duration-300 hover:border-white/20"
        >
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${getStateDotClass(state)}`} />
              <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-slate-300">
                {speakerLabel}
              </span>
            </div>
            <span className="text-[9px] font-mono text-cyan-400/80 uppercase tracking-widest px-2 py-0.5 rounded bg-cyan-950/40 border border-cyan-500/20">
              {settings.voice}
            </span>
          </div>
          <div className="min-h-12 flex items-center">
            <AnimatePresence mode="wait">
              <motion.div
                key={subtitle.kind + subtitle.text.substring(0, 10)}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.2 }}
                className="w-full text-left"
              >
                <SubtitleView subtitle={subtitle} />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>

        <div className="flex items-center gap-3.5 p-2 pl-2.5 pr-4 rounded-full border border-white/10 bg-black/60 backdrop-blur-2xl shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
          <button
            onClick={handleToggleConnection}
            className={`w-13 h-13 rounded-full flex items-center justify-center transition-all duration-500 cursor-pointer backdrop-blur-xl shrink-0 ${getPowerButtonClass(state)}`}
            title={state === "disconnected" ? "Awake Wilco" : "Sleep core"}
          >
            <PowerIcon state={state} />
          </button>
          <WaveBars state={state} />
          <div className="flex items-center gap-1.5 ml-1">
            <span
              className={`w-2 h-2 rounded-full ${
                isBackendConnected
                  ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)] animate-pulse"
                  : "bg-rose-400"
              }`}
            />
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-300 font-bold">
              {connectionLabel}
            </span>
          </div>
          <div className="w-px h-4 bg-white/10 mx-0.5" />
          <button
            onClick={() => setShowChatFallback((v) => !v)}
            className={`p-2 rounded-full transition-all duration-300 cursor-pointer ${
              showChatFallback
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.4)]"
                : "text-slate-400 hover:text-white hover:bg-white/10"
            }`}
            title="Type command to Wilco"
          >
            <MessageSquare size={16} />
          </button>
          {(activeProjectorUrl || errorText) && (
            <button
              onClick={resetProjection}
              className="p-1.5 rounded-full text-slate-400 hover:text-white transition ml-1"
              title="Reset Screen Broadcasts"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      <AnimatePresence>
        {activeProjectorUrl && (
          <BrowserAgent url={activeProjectorUrl} onClose={closeProjector} actionTrigger={browserTrigger} />
        )}
      </AnimatePresence>

      <MemoryDashboard
        isOpen={showMemoryDashboard}
        onClose={() => setShowMemoryDashboard(false)}
        memories={memories}
        onAddMemory={handleAddManualMemory}
        onDeleteMemory={handleDeleteMemory}
      />

      <TranscriptPanel
        entries={transcriptEntries}
        isOpen={showTranscriptPanel}
        onClose={() => setShowTranscriptPanel(false)}
        onEntriesChange={setTranscriptEntries}
        onSelectionChange={() => {}}
      />

      <AnimatePresence>
        {showSettings && (
          <SettingsPanel
            isOpen={showSettings}
            onClose={() => setShowSettings(false)}
            settings={settings}
            onChange={handleSettingsChange}
            onVoiceChange={handleVoiceChange}
          />
        )}
      </AnimatePresence>

      <ToastContainer toasts={toasts} onDismiss={dismiss} />
      <SudoPopup onApprove={handleApproveSudo} onReject={handleRejectSudo} pendingRequests={pendingRequests} />
      <TextChatFallback
        isActive={showChatFallback}
        onClose={() => setShowChatFallback(false)}
        onMessageSubmit={handleChatSubmit}
        systemStatus={{
          state: isBackendConnected ? "connected" : "disconnected",
          transcriptCount: transcriptEntries.length,
          timestamp: new Date().toLocaleTimeString(),
          status: "operational",
        }}
      />

      <AnimatePresence>
        {showTerminal && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 20 }}
            className="absolute bottom-24 left-1/2 -translate-x-1/2 z-50 w-[90vw] max-w-2xl h-64 rounded-2xl border border-white/10 bg-black/80 backdrop-blur-2xl shadow-[0_10px_40px_rgba(0,0,0,0.8)] overflow-hidden"
          >
            <div className="flex items-center justify-between px-4 py-2 border-b border-white/5">
              <span className="text-[10px] font-mono font-bold text-emerald-400 tracking-widest">TERMINAL OUTPUT</span>
              <button onClick={() => setShowTerminal(false)} className="text-slate-500 hover:text-white p-1" aria-label="Close terminal">
                <X size={12} />
              </button>
            </div>
            <div ref={terminalRef} className="h-[calc(100%-36px)] overflow-y-auto p-3 font-mono text-[11px] space-y-1.5">
              {truncatedLogs.length === 0 && (
                <div className="text-slate-600 italic text-center pt-8">Waiting for tool executions...</div>
              )}
              {truncatedLogs.map((entry) => (
                <div key={entry.id} className="border-l-2 border-emerald-500/30 pl-2 py-0.5">
                  <span className="text-emerald-400">$ </span>
                  <span className="text-slate-300">{entry.tool}</span>
                  <span className="text-slate-500 ml-1">{JSON.stringify(entry.args)}</span>
                  <div className="text-slate-400 whitespace-pre-wrap break-all mt-0.5 text-[10px] opacity-80">
                    {entry.display}
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

interface BrowserRecognizer {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onresult: ((event: SpeechResultEvent) => void) | null;
  onerror: ((event: { error?: unknown }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

interface SpeechResultEvent {
  results: ArrayLike<{ isFinal: boolean; 0?: { transcript?: string } } & ArrayLike<{ transcript?: string }>>;
}
