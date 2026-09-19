import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  X,
  ExternalLink,
  AlertCircle,
  Layers,
  RefreshCw,
  ArrowLeft,
  ArrowRight,
  Home,
  Plus,
  Search,
  Play,
  Shield,
  BookOpen,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import { log, error as logError } from "../lib/logger";

interface Tab {
  id: string;
  url: string;
  title: string;
  history: string[];
  currentIndex: number;
  isLoading: boolean;
  openedExternally?: boolean;
}

interface BrowserAgentProps {
  url: string;
  onClose: () => void;
}

interface YtVideo {
  videoId: string;
  title: string;
  thumbnail: string;
  author?: string;
  views?: string;
  published?: string;
  duration?: string;
}

const YOUTUBE_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;
const RESTRICTED_REASON_FALLBACK = "";

let tabCounter = 0;

function createTabId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  tabCounter += 1;
  return `tab-${Date.now()}-${tabCounter}`;
}

function safeMessage(err: unknown): string {
  if (err instanceof Error) {
    return err.message;
  }
  if (typeof err === "string") {
    return err;
  }
  if (err === null || err === undefined) {
    return "Unknown error";
  }
  try {
    return JSON.stringify(err);
  } catch {
    return "Unknown error";
  }
}

function extractYoutubeId(urlStr: string): string | null {
  try {
    const parsed = new URL(urlStr);
    const host = parsed.hostname.toLowerCase();
    if (host.includes("youtube.com")) {
      const v = parsed.searchParams.get("v");
      if (v && YOUTUBE_ID_PATTERN.exec(v)) {
        return v;
      }
      const segments = parsed.pathname.split("/").filter(Boolean);
      const embedIdx = segments.indexOf("embed");
      if (embedIdx !== -1) {
        const candidate = segments.at(embedIdx + 1) ?? "";
        if (YOUTUBE_ID_PATTERN.exec(candidate)) {
          return candidate;
        }
      }
      const last = segments.at(-1) ?? "";
      if (YOUTUBE_ID_PATTERN.exec(last)) {
        return last;
      }
      return null;
    }
    if (host.includes("youtu.be")) {
      const candidate = parsed.pathname.split("/").find(Boolean) ?? "";
      if (YOUTUBE_ID_PATTERN.exec(candidate)) {
        return candidate;
      }
    }
  } catch {
    return null;
  }
  return null;
}

/** Normalize free text into a navigable URL, or a search URL when it is not an address. */
function normalizeToUrl(input: string): string {
  const trimmed = input.trim();
  if (trimmed === "about:blank") {
    return trimmed;
  }
  const withScheme = trimmed.includes("://") ? trimmed : `https://${trimmed}`;
  try {
    const parsed = new URL(withScheme);
    if (parsed.hostname.includes(".")) {
      return parsed.toString();
    }
  } catch {
    // Not parseable as a URL — fall through to search.
  }
  return `https://html.duckduckgo.com/html/?q=${encodeURIComponent(trimmed)}`;
}

function checkIsRestricted(urlStr: string): { restricted: boolean; reason: string } {
  if (!urlStr || urlStr === "about:blank") {
    return { restricted: false, reason: RESTRICTED_REASON_FALLBACK };
  }
  let parsed: URL;
  try {
    parsed = new URL(urlStr);
  } catch {
    return { restricted: false, reason: RESTRICTED_REASON_FALLBACK };
  }
  const hostname = parsed.hostname.toLowerCase();
  if (hostname.includes("youtube.com") && !parsed.pathname.includes("/embed") && !parsed.pathname.includes("/results")) {
    return {
      restricted: true,
      reason: "YouTube utilizes 'X-Frame-Options: SAMEORIGIN' security headers and frame-busting service modules that prevent frame nesting.",
    };
  }
  if (hostname.includes("youtu.be")) {
    return {
      restricted: true,
      reason: "YouTu.be redirect urls enforce strict top-level browser navigation redirects.",
    };
  }
  if (hostname.includes("google.com") && !parsed.pathname.includes("/search")) {
    return {
      restricted: true,
      reason: "Google security parameters prohibit embedding of credential ports and account consoles to mitigate clickjacking.",
    };
  }
  if (hostname.includes("chatgpt.com") || hostname.includes("openai.com")) {
    return {
      restricted: true,
      reason: "OpenAI requires secure browser authentication checks, cloudflare protections, and user-token cookie contexts.",
    };
  }
  if (hostname.includes("gmail.com") || hostname.includes("mail.google.com")) {
    return {
      restricted: true,
      reason: "Gmail demands authenticated, non-nested visual scopes to secure sensitive correspondence tokens.",
    };
  }
  if (hostname.includes("github.com")) {
    return {
      restricted: true,
      reason: "GitHub deploys 'X-Frame-Options: deny' on all repositories and workspace interfaces.",
    };
  }
  if (hostname.includes("twitter.com") || hostname.includes("x.com") || hostname.includes("instagram.com") || hostname.includes("facebook.com")) {
    return {
      restricted: true,
      reason: "Social networks require active secure sessions and forbid third-party iframe frame injection.",
    };
  }
  return { restricted: false, reason: RESTRICTED_REASON_FALLBACK };
}

function getCleanTitleFromUrl(urlStr: string): string {
  if (!urlStr || urlStr === "about:blank") {
    return "Start Page";
  }
  let parsed: URL;
  try {
    parsed = new URL(urlStr);
  } catch {
    return "Viewing Portal";
  }
  if (parsed.hostname.includes("youtube.com")) {
    if (parsed.searchParams.get("v")) {
      return "YouTube Stream";
    }
    if (parsed.pathname.includes("/results")) {
      return `YouTube Search: ${parsed.searchParams.get("search_query") || ""}`;
    }
    return "YouTube Projector";
  }
  if (parsed.hostname.includes("google.com")) {
    if (parsed.pathname.includes("search")) {
      return `Google Results: ${parsed.searchParams.get("q") || ""}`;
    }
    return "Google Search Board";
  }
  if (parsed.hostname.includes("duckduckgo.com")) {
    return "DuckDuckGo Proxy Search";
  }
  return parsed.hostname.replace("www.", "");
}

function getRenderUrl(urlStr: string): string {
  if (!urlStr || urlStr === "about:blank") {
    return "about:blank";
  }
  const ytId = extractYoutubeId(urlStr);
  if (ytId) {
    return `https://www.youtube.com/embed/${ytId}?autoplay=1&enablejsapi=1`;
  }
  if (urlStr.includes("youtube.com/results")) {
    return "about:blank";
  }
  return `/api/web-proxy?url=${encodeURIComponent(urlStr)}`;
}

function getSearchQuery(urlStr: string): string {
  const qIndex = urlStr.indexOf("?");
  if (qIndex === -1) {
    return "";
  }
  try {
    return new URLSearchParams(urlStr.substring(qIndex)).get("search_query") ?? "";
  } catch {
    return "";
  }
}

const QUICK_LINKS = [
  { name: "YouTube", url: "https://youtube.com", icon: "play" },
  { name: "Wikipedia", url: "https://wikipedia.org", icon: "book" },
  { name: "Google", url: "https://google.com", icon: "search" },
  { name: "ChatGPT", url: "https://chatgpt.com", icon: "sparkles" },
  { name: "Gmail", url: "https://gmail.com", icon: "layers" },
  { name: "DuckDuckGo", url: "https://duckduckgo.com", icon: "shield" },
] as const;

function QuickLinkIcon({ icon }: Readonly<{ icon: string }>): React.JSX.Element {
  if (icon === "play") {
    return <Play size={12} />;
  }
  if (icon === "book") {
    return <BookOpen size={12} />;
  }
  if (icon === "search") {
    return <Search size={12} />;
  }
  if (icon === "sparkles") {
    return <Sparkles size={12} />;
  }
  if (icon === "layers") {
    return <Layers size={12} />;
  }
  return <Shield size={12} />;
}

export const BrowserAgent: React.FC<Readonly<BrowserAgentProps>> = ({
  url: initialUrl,
  onClose,
}) => {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string>("");
  const [inputValue, setInputValue] = useState<string>("");
  const [diagnosticReason, setDiagnosticReason] = useState<string | null>(null);
  const [diagnosticStatus, setDiagnosticStatus] = useState<"secure" | "restricted" | "error" | "analyzing" | "blank">("blank");
  const [ytSearchResults, setYtSearchResults] = useState<YtVideo[]>([]);
  const [ytSearchLoading, setYtSearchLoading] = useState<boolean>(false);
  const [ytSearchError, setYtSearchError] = useState<string | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const loadStartRef = useRef<number>(0);

  const activeTab = tabs.find((t) => t.id === activeTabId);

  const navigateToUrl = useCallback((targetUrl: string) => {
    const finalUrl = normalizeToUrl(targetUrl);
    if (finalUrl === "about:blank") {
      setTabs((prev) =>
        prev.map((t) => {
          if (t.id !== activeTabId) {
            return t;
          }
          return {
            ...t,
            url: "about:blank",
            title: "Start Page",
            history: [...t.history.slice(0, t.currentIndex + 1), "about:blank"],
            currentIndex: t.currentIndex + 1,
            isLoading: false,
          };
        }),
      );
      setDiagnosticStatus("blank");
      setDiagnosticReason(null);
      return;
    }
    loadStartRef.current = Date.now();
    setDiagnosticStatus("analyzing");
    setDiagnosticReason(null);
    const restrictions = checkIsRestricted(finalUrl);
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== activeTabId) {
          return t;
        }
        const nextHistory = t.history.slice(0, t.currentIndex + 1);
        nextHistory.push(finalUrl);
        return {
          ...t,
          url: finalUrl,
          title: getCleanTitleFromUrl(finalUrl),
          history: nextHistory,
          currentIndex: nextHistory.length - 1,
          isLoading: !restrictions.restricted,
          openedExternally: restrictions.restricted,
        };
      }),
    );
    if (restrictions.restricted) {
      setDiagnosticStatus("restricted");
      setDiagnosticReason(restrictions.reason);
      try {
        window.open(finalUrl, "_blank", "noopener,noreferrer");
      } catch {
        setDiagnosticStatus("error");
        setDiagnosticReason("System pop-up blocker intercepted redirection search.");
      }
    }
  }, [activeTabId]);

  const handleNewTab = useCallback((initialUrlStr = "about:blank") => {
    const newTab: Tab = {
      id: createTabId(),
      url: initialUrlStr,
      title: getCleanTitleFromUrl(initialUrlStr),
      history: [initialUrlStr],
      currentIndex: 0,
      isLoading: false,
    };
    setTabs((prev) => [...prev, newTab]);
    setActiveTabId(newTab.id);
  }, []);

  const handleCloseTab = useCallback((idToClose: string) => {
    setTabs((prevTabs) => {
      if (prevTabs.length <= 1) {
        return prevTabs;
      }
      return prevTabs.filter((t) => t.id !== idToClose);
    });
    if (tabs.length <= 1) {
      onClose();
      return;
    }
    if (activeTabId === idToClose) {
      const idx = tabs.findIndex((t) => t.id === idToClose);
      const updated = tabs.filter((t) => t.id !== idToClose);
      const fallback = updated[Math.max(0, idx - 1)];
      if (fallback) {
        setActiveTabId(fallback.id);
      }
    }
  }, [activeTabId, onClose, tabs]);

  const handleBack = useCallback(() => {
    if (!activeTab || activeTab.currentIndex <= 0) {
      return;
    }
    const targetIdx = activeTab.currentIndex - 1;
    const targetUrl = activeTab.history[targetIdx];
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== activeTabId) {
          return t;
        }
        return { ...t, url: targetUrl, currentIndex: targetIdx, isLoading: true };
      }),
    );
  }, [activeTab, activeTabId]);

  const handleForward = useCallback(() => {
    if (!activeTab || activeTab.currentIndex >= activeTab.history.length - 1) {
      return;
    }
    const targetIdx = activeTab.currentIndex + 1;
    const targetUrl = activeTab.history[targetIdx];
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== activeTabId) {
          return t;
        }
        return { ...t, url: targetUrl, currentIndex: targetIdx, isLoading: true };
      }),
    );
  }, [activeTab, activeTabId]);

  const handleRefresh = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe || !activeTab) {
      return;
    }
    loadStartRef.current = Date.now();
    setDiagnosticStatus("analyzing");
    iframe.src = getRenderUrl(activeTab.url);
  }, [activeTab]);

  const handleAddressSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim()) {
      navigateToUrl(inputValue);
    }
  }, [inputValue, navigateToUrl]);

  const handleIframeLoadComplete = useCallback(() => {
    if (!activeTab) {
      return;
    }
    setDiagnosticStatus("secure");
    setTabs((prev) =>
      prev.map((t) => {
        if (t.id !== activeTabId) {
          return t;
        }
        return { ...t, isLoading: false, title: getCleanTitleFromUrl(t.url) };
      }),
    );
    try {
      const bodyTxt = iframeRef.current?.contentDocument?.body?.innerText ?? "";
      if (bodyTxt.includes("Wilco Web Proxy Error") || bodyTxt.includes("Failed loading remote website")) {
        setDiagnosticStatus("error");
        setDiagnosticReason(bodyTxt.slice(0, 500));
      }
    } catch {
      // Cross-origin frames cannot be inspected — that is expected.
    }
  }, [activeTab, activeTabId]);

  useEffect(() => {
    if (!initialUrl) {
      return;
    }
    const startUrl = initialUrl;
    const restrictions = checkIsRestricted(startUrl);
    const newTab: Tab = {
      id: createTabId(),
      url: startUrl,
      title: getCleanTitleFromUrl(startUrl),
      history: [startUrl],
      currentIndex: 0,
      isLoading: startUrl !== "about:blank" && !restrictions.restricted,
      openedExternally: restrictions.restricted,
    };
    setTabs([newTab]);
    setActiveTabId(newTab.id);
    setInputValue(startUrl === "about:blank" ? "" : startUrl);
    if (startUrl !== "about:blank") {
      loadStartRef.current = Date.now();
      if (restrictions.restricted) {
        setDiagnosticStatus("restricted");
        setDiagnosticReason(restrictions.reason);
        window.open(startUrl, "_blank", "noopener,noreferrer");
      } else {
        setDiagnosticStatus("analyzing");
      }
    } else {
      setDiagnosticStatus("blank");
    }
  }, [initialUrl]);

  useEffect(() => {
    if (!activeTab) {
      return;
    }
    setInputValue(activeTab.url === "about:blank" ? "" : activeTab.url);
    if (!activeTab.url.includes("youtube.com/results")) {
      setYtSearchResults([]);
      return;
    }
    let cancelled = false;
    setYtSearchLoading(true);
    setYtSearchError(null);
    let query = "";
    try {
      const urlObj = new URL(activeTab.url);
      query = urlObj.searchParams.get("search_query") ?? "";
    } catch {
      setYtSearchError("Invalid YouTube search URL structure.");
      setYtSearchLoading(false);
      return;
    }
    fetch(`/api/youtube-search?q=${encodeURIComponent(query)}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`HTTP status ${res.status}`);
        }
        return res.json();
      })
      .then((data: { results?: YtVideo[] }) => {
        if (cancelled) {
          return;
        }
        setYtSearchResults(data.results ?? []);
        setYtSearchLoading(false);
        setTabs((prev) => prev.map((t) => (t.id === activeTabId ? { ...t, isLoading: false } : t)));
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        logError("[YouTube Search Fetch Error]:", err);
        setYtSearchError(safeMessage(err) || "Failed loading real YouTube results.");
        setYtSearchLoading(false);
        setTabs((prev) => prev.map((t) => (t.id === activeTabId ? { ...t, isLoading: false } : t)));
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, activeTabId]);

  useEffect(() => {
    const handleNavigationMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; url?: string } | null;
      if (event.origin !== window.location.origin) {
        return;
      }
      if (data?.type === "NAVIGATE" && data.url) {
        log("[Wilco Browser] Same-origin child iframe navigated to:", data.url);
        navigateToUrl(data.url);
      }
    };
    window.addEventListener("message", handleNavigationMessage);
    return () => window.removeEventListener("message", handleNavigationMessage);
  }, [navigateToUrl]);

  const renderMainContent = (): React.JSX.Element => {
    if (activeTab?.url === "about:blank" || !activeTab) {
      return <HomeDashboard inputValue={inputValue} onInput={setInputValue} onSubmit={handleAddressSubmit} onNavigate={navigateToUrl} />;
    }
    if (diagnosticStatus === "restricted") {
      return <StatusCard kind="restricted" title={getCleanTitleFromUrl(activeTab.url)} reason={diagnosticReason} tabUrl={activeTab.url} />;
    }
    if (diagnosticStatus === "error") {
      return <StatusCard kind="error" title={getCleanTitleFromUrl(activeTab.url)} reason={diagnosticReason} tabUrl={activeTab.url} />;
    }
    if (activeTab.url.includes("youtube.com/results")) {
      return (
        <YoutubeResults
          url={activeTab.url}
          loading={ytSearchLoading}
          error={ytSearchError}
          results={ytSearchResults}
          onOpen={navigateToUrl}
          onRetry={handleRefresh}
        />
      );
    }
    return (
      <div className="flex-1 w-full h-full relative overflow-hidden">
        <iframe
          ref={iframeRef}
          title="Wilco browser viewport"
          src={getRenderUrl(activeTab.url)}
          onLoad={handleIframeLoadComplete}
          className="w-full h-full border-0 absolute inset-0 bg-black"
          allow="autoplay; encrypted-media; fullscreen"
        />
        {activeTab.isLoading && (
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-xs text-white/30 font-sans">Loading...</span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      id="wilco-playwright-automation-hud"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 bg-black/60 backdrop-blur-2xl animate-fade-in text-left select-none"
    >
      <div className="relative w-full max-w-5xl h-[88vh] flex flex-col rounded-2xl border border-white/6 bg-black/50 backdrop-blur-3xl shadow-[0_0_120px_rgba(13,148,136,0.12)] overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(13,148,136,0.08),transparent_60%)] pointer-events-none" />
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_bottom_left,rgba(6,182,212,0.05),transparent_50%)] pointer-events-none" />

        <div className="relative z-10 flex items-center justify-between px-3 pt-1">
          <div className="flex items-center gap-0 overflow-x-auto scrollbar-none" role="tablist" aria-label="Browser tabs">
            {tabs.map((tab) => {
              const isActive = tab.id === activeTabId;
              return (
                <div
                  key={tab.id}
                  role="tab"
                  aria-selected={isActive}
                  tabIndex={0}
                  onClick={() => setActiveTabId(tab.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setActiveTabId(tab.id);
                    }
                  }}
                  className={`group/tab relative flex items-center gap-2 px-3 py-2.5 cursor-pointer text-xs font-sans select-none transition-colors duration-150 ${
                    isActive ? "text-white" : "text-white/30 hover:text-white/60"
                  }`}
                >
                  {isActive && (
                    <div className="absolute bottom-0 left-2 right-2 h-0.5 bg-cyan-400 rounded-full" />
                  )}
                  {tab.isLoading && (
                    <span className="w-3 h-3 rounded-full border-[1.5px] border-white/20 border-t-cyan-400 animate-spin shrink-0" />
                  )}
                  <span className="truncate max-w-25">{tab.title}</span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCloseTab(tab.id);
                    }}
                    aria-label={`Close tab ${tab.title}`}
                    className="p-0.5 rounded opacity-0 group-hover/tab:opacity-100 text-white/30 hover:text-white/60 transition"
                  >
                    <X size={11} />
                  </button>
                </div>
              );
            })}
            <button
              onClick={() => handleNewTab()}
              aria-label="New tab"
              className="p-1.5 ml-0.5 text-white/30 hover:text-white/60 transition cursor-pointer shrink-0"
            >
              <Plus size={15} />
            </button>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-white/30 hover:text-white/60 transition cursor-pointer shrink-0"
            title="Close"
            aria-label="Close browser"
          >
            <X size={17} />
          </button>
        </div>

        <div className="relative z-10 flex-1 flex overflow-hidden mt-0.5">
          <div className="flex-1 flex flex-col overflow-hidden relative group">
            {renderMainContent()}

            <div className="absolute bottom-3 left-1/2 -translate-x-1/2 pointer-events-none">
              <div className="pointer-events-auto opacity-0 hover:opacity-100 focus-within:opacity-100 transition-opacity duration-200 flex items-center gap-1.5 px-3 py-2 rounded-full bg-black/50 backdrop-blur-2xl border border-white/8 shadow-xl">
                <button
                  onClick={handleBack}
                  disabled={!activeTab || activeTab.currentIndex <= 0}
                  className="p-1.5 rounded-full text-white/40 hover:text-white hover:bg-white/10 disabled:opacity-20 disabled:hover:bg-transparent transition cursor-pointer"
                  title="Back"
                  aria-label="Back"
                >
                  <ArrowLeft size={14} />
                </button>
                <button
                  onClick={handleForward}
                  disabled={!activeTab || activeTab.currentIndex >= activeTab.history.length - 1}
                  className="p-1.5 rounded-full text-white/40 hover:text-white hover:bg-white/10 disabled:opacity-20 disabled:hover:bg-transparent transition cursor-pointer"
                  title="Forward"
                  aria-label="Forward"
                >
                  <ArrowRight size={14} />
                </button>
                <button
                  onClick={handleRefresh}
                  disabled={!activeTab || activeTab.url === "about:blank"}
                  className="p-1.5 rounded-full text-white/40 hover:text-white hover:bg-white/10 disabled:opacity-20 transition cursor-pointer"
                  title="Refresh"
                  aria-label="Refresh"
                >
                  <RefreshCw size={13} className={activeTab?.isLoading ? "animate-spin" : ""} />
                </button>
                <button
                  onClick={() => navigateToUrl("about:blank")}
                  className="p-1.5 rounded-full text-white/40 hover:text-white hover:bg-white/10 transition cursor-pointer"
                  title="Home"
                  aria-label="Home"
                >
                  <Home size={14} />
                </button>
                <div className="w-px h-4 bg-white/6" />
                <form onSubmit={handleAddressSubmit} className="flex items-center">
                  <div className="flex items-center bg-black/30 rounded-full pl-3 pr-1">
                    <Search size={12} className="text-white/30 shrink-0" />
                    <input
                      type="text"
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      placeholder="Search or enter address..."
                      aria-label="Address bar"
                      className="w-36 bg-transparent px-2 py-1 text-xs text-white/70 placeholder-white/30 outline-none font-sans"
                    />
                  </div>
                  <button
                    type="submit"
                    className="ml-1 px-3 py-1 rounded-full bg-white/10 hover:bg-white/15 text-white/50 hover:text-white/80 text-[10px] font-sans transition cursor-pointer"
                  >
                    Go
                  </button>
                </form>
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>
  );
};

function HomeDashboard({ inputValue, onInput, onSubmit, onNavigate }: Readonly<{
  inputValue: string;
  onInput: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onNavigate: (url: string) => void;
}>): React.JSX.Element {
  return (
    <div className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
      <div className="absolute inset-0 bg-linear-to-br from-black via-teal-950/20 to-cyan-950/20 pointer-events-none" />
      <motion.div
        className="absolute inset-0 bg-[radial-gradient(800px_circle_at_50%_30%,rgba(13,148,136,0.06),transparent_60%)] pointer-events-none"
        animate={{ opacity: [0.4, 1, 0.4] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute inset-0 bg-[radial-gradient(600px_circle_at_80%_70%,rgba(6,182,212,0.05),transparent_60%)] pointer-events-none"
        animate={{ opacity: [1, 0.4, 1] }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 w-full max-w-lg px-6"
      >
        <form onSubmit={onSubmit} className="relative mb-10">
          <div className="flex items-center bg-black/40 backdrop-blur-xl border border-white/8 rounded-full pl-5 pr-2 py-2.5 focus-within:border-cyan-500/30 focus-within:shadow-[0_0_40px_rgba(13,148,136,0.06)] transition-all duration-300">
            <Search size={16} className="text-white/30 shrink-0" />
            <input
              type="text"
              value={inputValue}
              onChange={(e) => onInput(e.target.value)}
              placeholder="Search or enter address..."
              aria-label="Search or enter address"
              className="flex-1 bg-transparent px-3.5 py-1 text-sm text-white/80 placeholder-white/30 outline-none font-sans"
            />
            <button
              type="submit"
              className="px-5 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-white/50 hover:text-white/80 text-xs font-sans transition cursor-pointer"
            >
              Go
            </button>
          </div>
        </form>
        <div className="flex flex-wrap justify-center gap-2.5">
          {QUICK_LINKS.map((link) => (
            <motion.button
              key={link.name}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.97 }}
              onClick={() => onNavigate(link.url)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-white/4 hover:bg-white/8 border border-white/6 hover:border-cyan-500/20 text-xs text-white/50 hover:text-white/80 transition-all duration-200 cursor-pointer font-sans"
            >
              <QuickLinkIcon icon={link.icon} />
              {link.name}
            </motion.button>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

function StatusCard({ kind, title, reason, tabUrl }: Readonly<{
  kind: "restricted" | "error";
  title: string;
  reason: string | null;
  tabUrl: string;
}>): React.JSX.Element {
  const isRestricted = kind === "restricted";
  return (
    <div className="flex-1 flex items-center justify-center p-8">
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        className="max-w-sm w-full p-6 rounded-xl border border-white/6 bg-black/40 backdrop-blur-xl text-center space-y-4"
      >
        <div className={`mx-auto w-10 h-10 rounded-full border flex items-center justify-center ${isRestricted ? "bg-cyan-500/10 border-cyan-500/20" : "bg-rose-500/10 border-rose-500/20"}`}>
          {isRestricted ? <Shield size={18} className="text-cyan-400" /> : <AlertCircle size={18} className="text-rose-400" />}
        </div>
        <div className="space-y-1.5">
          <p className="text-sm font-sans text-white/80">{isRestricted ? "Site can't be embedded" : "Connection failed"}</p>
          <p className="text-xs text-white/40 font-sans leading-relaxed max-w-xs mx-auto">
            {reason ?? `${title} blocks embedding due to security policies. Open it in your browser instead.`}
          </p>
        </div>
        <button
          onClick={() => window.open(tabUrl, "_blank", "noopener,noreferrer")}
          className={`px-5 py-2 rounded-full border text-xs font-sans transition cursor-pointer inline-flex items-center gap-1.5 ${isRestricted ? "bg-cyan-500/10 hover:bg-cyan-500/20 border-cyan-500/20 text-cyan-400" : "bg-rose-500/10 hover:bg-rose-500/20 border-rose-500/20 text-rose-400"}`}
        >
          <ExternalLink size={13} /> Open in browser
        </button>
      </motion.div>
    </div>
  );
}

function YoutubeResults({ url, loading, error, results, onOpen, onRetry }: Readonly<{
  url: string;
  loading: boolean;
  error: string | null;
  results: YtVideo[];
  onOpen: (url: string) => void;
  onRetry: () => void;
}>): React.JSX.Element {
  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3">
        <div className="w-8 h-8 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-white/30 font-sans">Loading results...</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        <AlertCircle size={20} className="text-rose-400" />
        <p className="text-xs text-white/50 font-sans max-w-sm text-center">{error}</p>
        <button
          onClick={onRetry}
          className="px-4 py-1.5 rounded-full bg-white/10 hover:bg-white/15 text-xs text-white/60 transition cursor-pointer font-sans"
        >
          Retry
        </button>
      </div>
    );
  }
  return (
    <div className="flex-1 w-full h-full flex flex-col overflow-hidden relative">
      <div className="px-6 py-3 border-b border-white/6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <Play size={13} className="text-red-500" />
          <span className="text-xs text-white/60 font-sans">
            YouTube results for &ldquo;{getSearchQuery(url)}&rdquo;
          </span>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-5 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 scrollbar-none">
        {results.map((video) => (
          <motion.div
            key={video.videoId}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            onClick={() => onOpen(`https://youtube.com/watch?v=${video.videoId}`)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen(`https://youtube.com/watch?v=${video.videoId}`);
              }
            }}
            role="button"
            tabIndex={0}
            aria-label={`Play ${video.title}`}
            className="bg-white/3 border border-white/6 hover:border-red-500/20 rounded-xl overflow-hidden cursor-pointer hover:bg-white/6 transition-all duration-200 group/card flex flex-col"
          >
            <div className="relative aspect-video bg-black overflow-hidden">
              <img
                src={video.thumbnail}
                alt={video.title}
                referrerPolicy="no-referrer"
                className="w-full h-full object-cover group-hover/card:scale-105 transition duration-300"
              />
              {video.duration && (
                <span className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded bg-black/70 text-[10px] text-white/70 font-sans">
                  {video.duration}
                </span>
              )}
            </div>
            <div className="p-3 flex flex-col gap-1.5">
              <h4 className="text-xs font-sans text-white/80 group-hover/card:text-red-400 transition line-clamp-2 leading-relaxed">
                {video.title}
              </h4>
              <p className="text-[11px] text-white/40 font-sans truncate">
                {video.author ?? ""}
              </p>
              <div className="flex items-center gap-2 text-[10px] text-white/30 font-sans pt-1.5 border-t border-white/4">
                <span>{video.views ?? ""}</span>
                <span>·</span>
                <span>{video.published ?? ""}</span>
              </div>
            </div>
          </motion.div>
        ))}
        {results.length === 0 && (
          <div className="col-span-full py-16 text-center space-y-2">
            <Play size={18} className="mx-auto text-white/20" />
            <p className="text-sm text-white/30 font-sans">No results found</p>
            <p className="text-xs text-white/20 font-sans">Try a different search term</p>
          </div>
        )}
      </div>
    </div>
  );
}
