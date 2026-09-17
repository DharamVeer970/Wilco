import React, { useEffect, useState } from "react";
import {
  Settings as SettingsIcon,
  X,
  Power,
  Mic,
  Cpu,
  Info,
  Sparkles,
} from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import type {
  Settings,
} from "../lib/settingsStore";
import { CHARACTERS, characterForVoice } from "../lib/characters";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onVoiceChange?: (voice: string) => void;
}

type SettingsTab = "general" | "voice" | "system" | "about";

function ToggleRow({
  label,
  description,
  checked,
  onChange
}: Readonly<{
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void
}>) {
  return (
    <div className="flex items-center justify-between p-4 bg-black/40 border-l-2 border-cyan-500/20 hover:border-cyan-400 transition-all duration-300 group relative">
      <div className="absolute inset-0 bg-linear-to-r from-cyan-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="relative z-10">
        <div className="text-sm font-mono text-cyan-50 tracking-wider uppercase">{label}</div>
        {description && (
          <div className="text-[10px] font-mono text-cyan-600/70 mt-1 uppercase tracking-widest">
            {description}
          </div>
        )}
      </div>
      <button
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-10 shrink-0 cursor-pointer border transition-colors duration-300 ease-in-out focus:outline-none z-10 ${
          checked ? 'bg-cyan-500/20 border-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.4)]' : 'bg-black/80 border-cyan-900/50'
        }`}
        style={{ clipPath: "polygon(20% 0, 100% 0, 80% 100%, 0% 100%)" }}
      >
        <span
          className={`pointer-events-none inline-block h-3 w-4 mt-0.5 transform bg-cyan-300 transition duration-300 ease-in-out ${
            checked ? 'translate-x-4 opacity-100' : 'translate-x-1 opacity-20'
          }`}
          style={{ clipPath: "polygon(20% 0, 100% 0, 80% 100%, 0% 100%)" }}
        />
      </button>
    </div>
  );
}

export function SettingsPanel({ isOpen, onClose, settings, onChange, onVoiceChange }: Readonly<SettingsPanelProps>) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  const [agentHealth, setAgentHealth] = useState<{
    online: boolean;
    toolCount?: number;
  }>({ online: false });
  const [voicePacks, setVoicePacks] = useState<{ name: string; description: string }[]>([]);

  useEffect(() => {
    if (!isOpen) return;
    const enumerate = async () => {
      try {
        if (!navigator.mediaDevices?.enumerateDevices) return;
        const devices = await navigator.mediaDevices.enumerateDevices();
        setMics(devices.filter((d) => d.kind === "audioinput"));
      } catch {}
    };
    enumerate();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const probe = async () => {
      try {
        // The agent's own health lives on this same origin — no second port to guess at.
        const res = await fetch("/api/state", { cache: "no-store" });
        if (!res.ok) {
          setAgentHealth({ online: false });
          return;
        }
        const data = await res.json();
        setAgentHealth({
          online: true,
          toolCount: Array.isArray(data.voices) ? data.voices.length : undefined,
        });
      } catch {
        setAgentHealth({ online: false });
      }
    };
    probe();
    const id = setInterval(probe, 5000);
    return () => clearInterval(id);
  }, [isOpen]);

  // The voice list is the backend's own pack table — the same list the spoken "switch voice"
  // command resolves against, so what is shown here can always be selected by voice too.
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/voices", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled && Array.isArray(data.voices)) {
          setVoicePacks(
            data.voices.map((v: { name: string; description?: string }) => ({
              name: String(v.name),
              description: String(v.description || ""),
            }))
          );
        }
      } catch {
        /* the panel simply keeps whatever it last had */
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const tabs: { id: SettingsTab; label: string; icon: any }[] = [
    { id: "general", label: "Sys_Config", icon: Power },
    { id: "voice", label: "Audio_I/O", icon: Mic },
    { id: "system", label: "Daemon_Link", icon: Cpu },
    { id: "about", label: "Core_Stats", icon: Info },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/80 z-40 backdrop-blur-md bg-[linear-gradient(rgba(0,255,255,0.03)_1px,transparent_1px)] bg-size-[100%_4px] pointer-events-auto"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.98, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[90vw] max-w-5xl h-[80vh] max-h-200 bg-black/90 backdrop-blur-3xl z-50 flex shadow-[0_0_100px_rgba(6,182,212,0.15)] overflow-hidden"
            style={{ clipPath: "polygon(0 0, calc(100% - 30px) 0, 100% 30px, 100% 100%, 30px 100%, 0 calc(100% - 30px))" }}
          >
            <div className="absolute inset-0 border-2 border-cyan-500/20 pointer-events-none" style={{ clipPath: "polygon(0 0, calc(100% - 30px) 0, 100% 30px, 100% 100%, 30px 100%, 0 calc(100% - 30px))" }} />
            
            {/* Sidebar */}
            <div className="w-64 border-r border-cyan-500/20 bg-cyan-950/10 flex flex-col relative">
              <div className="absolute top-0 left-0 w-8 h-1 bg-cyan-500/50" />
              <div className="absolute top-0 left-0 w-1 h-8 bg-cyan-500/50" />
              
              <div className="p-6 pb-8 border-b border-cyan-500/20 bg-black/40">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 relative overflow-hidden group">
                    <SettingsIcon size={22} className="relative z-10" />
                  </div>
                  <div>
                    <h3 className="font-display font-medium text-lg tracking-widest text-white uppercase flex items-center gap-2">
                      SETTINGS
                    </h3>
                    <p className="text-[9px] font-mono uppercase tracking-widest text-cyan-400 mt-0.5 flex items-center gap-1">
                      <Sparkles size={10} /> {settings.avatarStyle === "orb" ? "Aegis_Core" : "Wilco_Core"}
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {tabs.map((tab) => {
                  const Icon = tab.icon;
                  const isActive = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      className={`w-full flex items-center gap-3 px-4 py-3 text-sm font-mono uppercase tracking-wider transition-all duration-300 relative overflow-hidden group cursor-pointer ${
                        isActive
                          ? "text-cyan-300 bg-cyan-500/10 border-l-2 border-cyan-400 shadow-[inset_10px_0_20px_rgba(6,182,212,0.1)]"
                          : "text-cyan-600 hover:text-cyan-400 hover:bg-cyan-950/30 border-l-2 border-transparent"
                      }`}
                    >
                      <Icon size={16} className={isActive ? "text-cyan-400" : "text-cyan-800 group-hover:text-cyan-500"} />
                      <span className="relative z-10">{tab.label}</span>
                      {tab.id === "system" && !agentHealth.online && (
                        <span className="w-1.5 h-1.5 bg-rose-500 animate-pulse ml-auto shadow-[0_0_8px_rgba(244,63,94,0.8)]" />
                      )}
                    </button>
                  );
                })}
              </div>
              
              <div className="p-4 border-t border-cyan-500/20 text-[9px] font-mono text-cyan-700 uppercase tracking-widest flex justify-between">
                <span>AUTH: ADMIN</span>
                <span>SEC: L4</span>
              </div>
            </div>

            {/* Content Pane */}
            <div className="flex-1 flex flex-col bg-black/60 relative">
              <div className="absolute inset-0 bg-[linear-gradient(rgba(0,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(0,255,255,0.02)_1px,transparent_1px)] bg-size-[30px_30px] pointer-events-none opacity-50" />
              
              <div className="px-10 py-8 flex items-center justify-between border-b border-cyan-500/20 bg-black/40 relative z-10">
                <div className="flex items-center gap-4">
                  <div className="w-2 h-8 bg-cyan-500 shadow-[0_0_10px_rgba(6,182,212,0.6)]" />
                  <h2 className="text-2xl font-mono tracking-widest text-white uppercase">
                    {tabs.find(t => t.id === activeTab)?.label}
                  </h2>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 bg-cyan-950/40 text-cyan-400 hover:bg-rose-900/40 hover:text-rose-400 transition-all cursor-pointer border border-cyan-500/30 hover:border-rose-500/50"
                  style={{ clipPath: "polygon(0 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%)" }}
                >
                  <X size={20} />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-10 relative z-10 no-scrollbar">
                <div className="max-w-2xl mx-auto space-y-12">
                  
                  {activeTab === "general" && (
                    <div className="space-y-8 animate-in fade-in duration-500">
                      <div className="space-y-3">
                        <label htmlFor="settings-bg-video" className="text-xs font-mono tracking-widest text-cyan-500 uppercase flex items-center gap-2">
                          <span className="w-1 h-1 bg-cyan-400 rounded-full animate-pulse" /> Environmental FX
                        </label>
                        <select
                          id="settings-bg-video"
                          value={settings.backgroundVideo}
                          onChange={(e) => onChange({ backgroundVideo: e.target.value })}
                          className="w-full px-4 py-3 bg-black/50 border border-cyan-500/20 text-sm font-mono text-cyan-50 focus:outline-none focus:border-cyan-400/80 transition cursor-pointer"
                          style={{ clipPath: "polygon(0 0, calc(100% - 15px) 0, 100% 15px, 100% 100%, 0 100%)" }}
                        >
                          <option className="bg-slate-900 text-white" value="">Dynamic CSS Mesh (Default)</option>
                          <option className="bg-slate-900 text-white" value="solid">Solid Theme Color</option>
                          <option className="bg-slate-900 text-white" value="bg-6.mp4">Cinematic Scene (1)</option>
                          <option className="bg-slate-900 text-white" value="bg-7.mp4">Cinematic Scene (2)</option>
                        </select>
                      </div>

                      <div className="space-y-3">
                        <span className="text-xs font-mono tracking-widest text-cyan-500 uppercase flex items-center gap-2">
                          <span className="w-1 h-1 bg-cyan-400 rounded-full" /> System Hooks
                        </span>
                        <ToggleRow
                          label="Auto-Launch Sequence"
                          description="Boot agent automatically with OS"
                          checked={settings.autoStart}
                          onChange={(v) => {
                            onChange({ autoStart: v });
                            void fetch("/api/settings", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ autoStart: v }),
                            }).catch(() => {});
                          }}
                        />
                      </div>

                      <div className="space-y-3">
                        <span className="text-xs font-mono tracking-widest text-cyan-500 uppercase flex items-center gap-2">
                          <span className="w-1 h-1 bg-cyan-400 rounded-full" /> UI Rendering
                        </span>
                        <ToggleRow
                          label="Kinetic Animations"
                          description="Enable fluid UI and particle effects"
                          checked={settings.animations}
                          onChange={(v) => onChange({ animations: v })}
                        />
                      </div>
                    </div>
                  )}

                  {activeTab === "voice" && (
                    <div className="space-y-10 animate-in fade-in duration-500">
                      
                      <div className="space-y-3">
                        <span className="block text-xs font-mono tracking-widest text-cyan-500 uppercase">Hologram Archetype</span>
                        <div className="grid grid-cols-3 gap-3">
                          {[
                            { id: "image", label: "Character Avatar", desc: "AI Characters" },
                            { id: "character", label: "Video Entity", desc: "HD Video Cores" },
                            { id: "orb", label: "Aegis Orb", desc: "Live API Mesh" }
                          ].map((a) => (
                            <button
                              key={a.id}
                              onClick={() => {
                                onChange({ avatarStyle: a.id as any });
                              }}
                              className={`p-4 border text-left transition-all duration-300 cursor-pointer ${
                                settings.avatarStyle === a.id
                                  ? "border-cyan-400 bg-cyan-500/10 shadow-[inset_0_0_20px_rgba(6,182,212,0.2)]"
                                  : "border-cyan-900/40 bg-black/40 hover:border-cyan-500/40"
                              }`}
                              style={{ clipPath: "polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px)" }}
                            >
                              <div className={`text-sm font-mono uppercase tracking-wider ${settings.avatarStyle === a.id ? "text-cyan-300" : "text-cyan-700"}`}>
                                {a.label}
                              </div>
                              <div className="text-[9px] font-mono text-cyan-600/60 mt-1 uppercase">MODE: {a.desc}</div>
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="space-y-3">
                        <span className="block text-xs font-mono tracking-widest text-cyan-500 uppercase">Neural Voice Pattern</span>
                        {settings.avatarStyle !== "orb" || voicePacks.length === 0 ? (
                          <div className="grid grid-cols-2 gap-3">
                            {Object.entries(CHARACTERS).map(([key, char]) => {
                              const isSelected =
                                characterForVoice(settings.voice).name === char.name ||
                                settings.voice.toLowerCase() === key.toLowerCase() ||
                                char.voices.some((v) => v.toLowerCase() === settings.voice.toLowerCase());
                              return (
                                <button
                                  key={key}
                                  onClick={() => {
                                    onChange({ voice: key });
                                    onVoiceChange?.(key);
                                  }}
                                  className={`p-3 border-l-2 text-left transition-all duration-300 cursor-pointer flex items-center gap-3 ${
                                    isSelected
                                      ? "border-cyan-400 bg-cyan-500/10 text-cyan-300"
                                      : "border-cyan-900/40 bg-black/40 text-slate-400 hover:text-cyan-200 hover:border-cyan-500/40"
                                  }`}
                                >
                                  <img
                                    src={char.image}
                                    alt={char.name}
                                    className={`w-10 h-10 rounded-full object-cover border-2 transition-all shrink-0 ${
                                      isSelected
                                        ? "border-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.4)]"
                                        : "border-cyan-900/40 opacity-70"
                                    }`}
                                  />
                                  <div className="min-w-0">
                                    <div className="text-sm font-mono uppercase tracking-wider">
                                      {key === "ava" ? "AVA (DEFAULT)" : key.toUpperCase()}
                                    </div>
                                    <div className="text-[9px] font-mono opacity-70 mt-1 uppercase">
                                      {char.name} — {char.desc}
                                    </div>
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="grid grid-cols-2 gap-3">
                            {voicePacks.map((pack) => {
                              const isSelected = settings.voice.toLowerCase() === pack.name.toLowerCase();
                              return (
                                <button
                                  key={pack.name}
                                  onClick={() => {
                                    onChange({ voice: pack.name });
                                    onVoiceChange?.(pack.name);
                                  }}
                                  className={`p-3 border-l-2 text-left transition-all duration-300 cursor-pointer flex items-center gap-3 ${
                                    isSelected
                                      ? "border-cyan-400 bg-cyan-500/10 text-cyan-300"
                                      : "border-cyan-900/40 bg-black/40 text-slate-400 hover:text-cyan-200 hover:border-cyan-500/40"
                                  }`}
                                >
                                  <div className="min-w-0">
                                    <div className="text-sm font-mono uppercase tracking-wider">{pack.name}</div>
                                    <div className="text-[9px] font-mono opacity-70 mt-1 uppercase">{pack.description}</div>
                                  </div>
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      <div className="space-y-3 border-t border-cyan-900/30 pt-6">
                        <span className="block text-xs font-mono tracking-widest text-cyan-500 uppercase">Audio Telemetry</span>
                        <ToggleRow
                          label="Wake Word Listener"
                          description="Active environmental audio scanning"
                          checked={settings.wakeWordEnabled}
                          onChange={(v) => onChange({ wakeWordEnabled: v })}
                        />
                        {settings.wakeWordEnabled && (
                          <div className="pl-4 border-l border-cyan-900 mt-2 space-y-4">
                            <div>
                              <label htmlFor="settings-wake-phrase" className="block text-[10px] font-mono tracking-widest text-cyan-600 uppercase mb-2">Activation Phrase</label>
                              <input
                                id="settings-wake-phrase"
                                type="text"
                                value={settings.wakePhrase}
                                onChange={(e) => onChange({ wakePhrase: e.target.value })}
                                className="w-full bg-black/60 border-b border-cyan-500/30 text-cyan-300 font-mono text-sm py-2 px-3 focus:outline-none focus:border-cyan-400"
                              />
                            </div>
                            <div>
                              <label htmlFor="settings-mic-device" className="block text-[10px] font-mono tracking-widest text-cyan-600 uppercase mb-2">Input Hardware</label>
                              <select
                                id="settings-mic-device"
                                value={settings.micDeviceId}
                                onChange={(e) => onChange({ micDeviceId: e.target.value })}
                                className="w-full bg-black/60 border-b border-cyan-500/30 text-cyan-300 font-mono text-sm py-2 px-3 focus:outline-none focus:border-cyan-400 appearance-none"
                              >
                                <option value="">System Default Audio Stream</option>
                                {mics.map((m, i) => (
                                  <option key={m.deviceId || i} value={m.deviceId}>{m.label || `Sensor ${i + 1}`}</option>
                                ))}
                              </select>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {activeTab === "system" && (
                    <div className="space-y-8 animate-in fade-in duration-500">
                      
                      <div className="space-y-3">
                        <span className="block text-xs font-mono tracking-widest text-cyan-500 uppercase">Daemon Status</span>
                        <div
                          className={`p-6 border relative overflow-hidden ${
                            agentHealth.online ? "border-emerald-500/30 bg-emerald-950/20" : "border-rose-500/30 bg-rose-950/20"
                          }`}
                          style={{ clipPath: "polygon(0 0, 100% 0, 100% calc(100% - 20px), calc(100% - 20px) 100%, 0 100%)" }}
                        >
                          <div className="absolute top-0 right-0 p-4 opacity-20">
                            <Cpu size={100} />
                          </div>
                          <div className="relative z-10">
                            <div className="flex items-center gap-3 mb-2">
                              <div className="relative">
                                <div className={`w-3 h-3 rounded-full ${agentHealth.online ? "bg-emerald-400" : "bg-rose-400"}`} />
                                {agentHealth.online && <div className="absolute inset-0 w-3 h-3 rounded-full bg-emerald-400 animate-ping" />}
                              </div>
                              <div className={`text-lg font-mono uppercase tracking-widest ${agentHealth.online ? "text-emerald-400" : "text-rose-400"}`}>
                                {agentHealth.online ? "LINK ESTABLISHED" : "LINK SEVERED"}
                              </div>
                            </div>
                            <div className="text-sm font-mono text-cyan-600/80 uppercase">
                              {agentHealth.online
                                ? `PORT: 8799 | VOICE PACKS: ${agentHealth.toolCount ?? 0}`
                                : "INITIATE PYTHON DAEMON ON PORT 8799"}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-3">
                        <span className="block text-xs font-mono tracking-widest text-cyan-500 uppercase">Active Capabilities</span>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                          {[
                            "App_Auto", "CDP_Bridge", "Vol_Control", "Luminance",
                            "Power_Ops", "FS_ReadWrite", "Vision_Proc", "Clip_Access"
                          ].map((cap, i) => (
                            <div key={i} className="p-2 border border-cyan-900/50 bg-cyan-950/10 text-center text-[9px] font-mono text-cyan-500 uppercase tracking-widest flex items-center justify-center gap-2">
                              <span className="w-1 h-1 bg-cyan-500 rounded-full" /> {cap}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === "about" && (
                    <div className="space-y-8 animate-in fade-in duration-500">
                      
                      <div className="flex flex-col items-center justify-center p-10 text-center relative">
                        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(6,182,212,0.1)_0,transparent_70%)] pointer-events-none" />
                        <div className="w-24 h-24 border border-cyan-500/50 flex items-center justify-center mb-6 relative group" style={{ clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)" }}>
                          <div className="absolute inset-0 bg-cyan-500/10 group-hover:bg-cyan-500/30 transition-colors" />
                          <Sparkles size={40} className="text-cyan-400 relative z-10" />
                        </div>
                        <h1 className="text-4xl font-mono text-white mb-2 tracking-[0.2em] uppercase">
                          {settings.avatarStyle === "orb" ? "Aegis_V2" : "Wilco_V2"}
                        </h1>
                        <p className="text-xs font-mono text-cyan-600 uppercase tracking-widest max-w-md">
                          Tactical Multi-Modal Desktop Interface
                        </p>
                      </div>

                      <div className="p-1 border border-cyan-500/30 bg-cyan-950/10 relative">
                        <div className="absolute top-0 left-0 w-2 h-2 border-t border-l border-cyan-400" />
                        <div className="absolute bottom-0 right-0 w-2 h-2 border-b border-r border-cyan-400" />
                        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-y-4 gap-x-8">
                          <div className="flex justify-between items-center border-b border-cyan-900/50 pb-2">
                            <span className="text-[10px] font-mono text-cyan-700 uppercase tracking-widest">Build</span>
                            <span className="text-xs font-mono text-cyan-300">2.0.0-PRO</span>
                          </div>
                          <div className="flex justify-between items-center border-b border-cyan-900/50 pb-2">
                            <span className="text-[10px] font-mono text-cyan-700 uppercase tracking-widest">LLM Core</span>
                            <span className="text-xs font-mono text-cyan-300">Gemini Live API</span>
                          </div>
                          <div className="flex justify-between items-center border-b border-cyan-900/50 pb-2 md:border-0 md:pb-0">
                            <span className="text-[10px] font-mono text-cyan-700 uppercase tracking-widest">Daemon</span>
                            <span className="text-xs font-mono text-cyan-300">FastAPI / Python</span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="text-[10px] font-mono text-cyan-700 uppercase tracking-widest">Client</span>
                            <span className="text-xs font-mono text-cyan-300">React + Vite</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
