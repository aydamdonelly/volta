"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, CornerDownLeft, RotateCcw, Sparkles, Wrench, MessageCircleQuestion } from "lucide-react";
import { submitIntent } from "@/lib/api";
import { useCanvasStore } from "@/lib/store";

type Mode = "idle" | "listening" | "processing" | "error";
type IntentMode = "create" | "edit" | "explain";

// Lazy access to Web Speech API
function getSR(): any {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

export function VoiceTextDot() {
  const [expanded, setExpanded] = useState(false);
  const [mode, setMode] = useState<Mode>("idle");
  const [transcript, setTranscript] = useState("");
  const [inputText, setInputText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recRef = useRef<any>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const setPending = useCanvasStore((s) => s.setPendingIntent);
  const clearCanvas = useCanvasStore((s) => s.clearCanvas);
  const themes = useCanvasStore((s) => s.themes);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const virtualNow = useCanvasStore((s) => s.virtualNow);

  useEffect(() => {
    setVoiceSupported(!!getSR());
  }, []);

  // Global hotkeys: Space = toggle voice; "/" = focus text & expand
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const active = document.activeElement;
      const isInput =
        active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || (active as HTMLElement).isContentEditable);
      if (e.key === "/") {
        if (!isInput) {
          e.preventDefault();
          setExpanded(true);
          requestAnimationFrame(() => inputRef.current?.focus());
        }
      } else if (e.code === "Space") {
        if (!isInput) {
          e.preventDefault();
          setExpanded(true);
          toggleVoice();
        }
      } else if (e.key === "Escape") {
        if (expanded && !inputText) {
          setExpanded(false);
          setTranscript("");
          stopVoice();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded, inputText]);

  function toggleVoice() {
    if (!voiceSupported) return;
    if (mode === "listening") {
      stopVoice();
      return;
    }
    startVoice();
  }

  async function startVoice() {
    const SR = getSR();
    if (!SR) {
      setError("Web Speech API not available — use the text input.");
      setMode("error");
      return;
    }
    // Pre-request mic permission via getUserMedia so the browser shows
    // a permission prompt instead of failing silently with "not-allowed".
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // We don't need the audio track ourselves — SpeechRecognition will manage it.
      stream.getTracks().forEach(t => t.stop());
    } catch (e: any) {
      const name = e?.name || "PermissionError";
      if (name === "NotAllowedError") {
        setError("Microphone blocked. Click the lock icon in the URL bar → allow microphone.");
      } else if (name === "NotFoundError") {
        setError("No microphone detected.");
      } else {
        setError(`Mic error: ${name}`);
      }
      setMode("error");
      return;
    }

    const r = new SR();
    r.lang = "en-US";
    r.continuous = false;
    r.interimResults = true;
    r.maxAlternatives = 1;

    let silenceTimer: ReturnType<typeof setTimeout> | null = null;

    r.onstart = () => {
      setMode("listening");
      setError(null);
      setTranscript("");
      silenceTimer = setTimeout(() => {
        try { r.stop(); } catch {}
      }, 8000);
    };
    r.onresult = (ev: any) => {
      let interim = "";
      let final_ = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const res = ev.results[i];
        if (res.isFinal) final_ += res[0].transcript;
        else interim += res[0].transcript;
      }
      const text = (final_ || interim).trim();
      setTranscript(text);
      if (final_) {
        if (silenceTimer) clearTimeout(silenceTimer);
        // Allow brief delay so UI shows final transcript before submit
        setTimeout(() => submit(text), 200);
      }
    };
    r.onerror = (ev: any) => {
      const code = String(ev.error || "voice error");
      const friendly: Record<string, string> = {
        "not-allowed": "Microphone blocked. Click the lock icon → allow microphone.",
        "service-not-allowed": "Speech service blocked by browser settings.",
        "no-speech": "Nothing heard. Try again or type your thesis.",
        "audio-capture": "Microphone not found.",
        "network": "Speech recognition offline (browser needs network).",
        "aborted": "Voice input cancelled.",
      };
      setError(friendly[code] || `Voice error: ${code}`);
      setMode("error");
      if (silenceTimer) clearTimeout(silenceTimer);
    };
    r.onend = () => {
      if (silenceTimer) clearTimeout(silenceTimer);
      setMode((m) => (m === "listening" ? "idle" : m));
    };
    recRef.current = r;
    try {
      r.start();
    } catch (err) {
      console.warn("voice start failed", err);
      setMode("error");
      setError(String(err));
    }
  }

  function stopVoice() {
    const r = recRef.current;
    if (r) {
      try { r.stop(); } catch {}
      recRef.current = null;
    }
    setMode("idle");
  }

  const isFilled = Object.keys(themes).length > 0;
  const [intentMode, setIntentMode] = useState<IntentMode>("create");

  // When canvas transitions empty → filled, default to "edit". When emptied,
  // snap back to "create".
  useEffect(() => {
    setIntentMode(isFilled ? "edit" : "create");
  }, [isFilled]);

  async function submit(text: string) {
    const t = text.trim();
    if (!t) return;
    setMode("processing");
    try {
      // Only "create" mode clears the canvas; "edit" + "explain" preserve it.
      if (intentMode === "create" && isFilled) clearCanvas("new_intent");
      const canvas_state = {
        themes: Object.values(themes).map((t) => ({
          theme_id: t.theme_id,
          windows: t.window_order
            .map((wid) => windowIndex[wid])
            .filter(Boolean)
            .map((w) => ({
              window_id: w.window_id,
              window_type: w.window_type,
              title: w.title,
              curve_keys: w.curve_keys,
            })),
        })),
        virtual_now: virtualNow,
      };
      const r = await submitIntent({ text: t, canvas_state, mode: intentMode });
      setPending(r.intent_id);
      setInputText("");
      setTranscript("");
      // mode transitions to idle on `done` op via WsProvider — we leave it as 'processing' until then
      // For UX safety, auto-reset after 7s
      setTimeout(() => setMode("idle"), 7000);
    } catch (err) {
      setError(String(err));
      setMode("error");
    }
  }

  const killSwitch = useCanvasStore((s) => s.killSwitch);
  function reset() {
    void killSwitch();
    setInputText("");
    setTranscript("");
    setError(null);
  }

  return (
    <div
      className={`voice-dot ${expanded ? "voice-dot--expanded" : "voice-dot--collapsed"}`}
      role="region"
      aria-label="Volta voice and text input"
    >
      <button
        type="button"
        className={`voice-dot__mic ${mode === "listening" ? "voice-dot__mic--listening" : ""}`}
        onClick={() => {
          setExpanded(true);
          toggleVoice();
        }}
        disabled={!voiceSupported}
        title={voiceSupported ? "Voice (Space)" : "Voice not supported — use text input"}
        aria-label="Voice input"
      >
        {voiceSupported ? <Mic size={16} strokeWidth={2} /> : <MicOff size={16} strokeWidth={2} />}
      </button>
      {expanded && (
        <>
          <ModeToggle isFilled={isFilled} value={intentMode} onChange={setIntentMode} />
          {mode === "listening" && transcript && (
            <span className="voice-dot__transcript" aria-live="polite">{transcript}</span>
          )}
          <input
            ref={inputRef}
            className="voice-dot__input"
            type="text"
            placeholder={placeholderForMode(intentMode, voiceSupported, isFilled)}
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit(inputText);
              }
            }}
            disabled={mode === "processing"}
            aria-label="Text input"
          />
          {isFilled && (
            <button
              type="button"
              onClick={reset}
              title="Clear canvas"
              aria-label="Reset canvas"
              style={{
                width: 28,
                height: 28,
                borderRadius: 14,
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                color: "var(--color-foreground-neutral-subtle, #5d7570)",
              }}
            >
              <RotateCcw size={14} strokeWidth={2} />
            </button>
          )}
          <button
            type="button"
            className="voice-dot__submit"
            onClick={() => submit(inputText)}
            disabled={!inputText.trim() || mode === "processing"}
            aria-label="Submit"
            title="Submit (Enter)"
            style={{
              width: 28,
              height: 28,
              borderRadius: 14,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <CornerDownLeft size={16} strokeWidth={2} />
          </button>
        </>
      )}
      {error && expanded && (
        <span style={{ color: "var(--color-foreground-danger)", fontSize: 12 }}>{error}</span>
      )}
    </div>
  );
}

function placeholderForMode(
  m: IntentMode,
  voiceSupported: boolean,
  isFilled: boolean,
): string {
  if (m === "edit") return "Edit — e.g. ‘swap the news for a wind chart’";
  if (m === "explain") return "Ask — e.g. ‘why is residual load spiking after 13:00?’";
  // create
  if (!isFilled) return voiceSupported ? "Or type your thesis…" : "Type your thesis…";
  return "New thesis — replaces the canvas";
}

interface ModeToggleProps {
  isFilled: boolean;
  value: IntentMode;
  onChange: (m: IntentMode) => void;
}

function ModeToggle({ isFilled, value, onChange }: ModeToggleProps) {
  const opts: Array<{ key: IntentMode; label: string; Icon: any; title: string }> = [
    { key: "create", label: "New", Icon: Sparkles, title: "Compose a fresh canvas (clears the current one)" },
    { key: "edit", label: "Edit", Icon: Wrench, title: "Modify the current canvas (swap / remove / add)" },
    { key: "explain", label: "Ask", Icon: MessageCircleQuestion, title: "Add a streamed answer card (no other changes)" },
  ];
  // When canvas is empty, only Create makes sense — show just it as a static label.
  const visible = isFilled ? opts : opts.filter((o) => o.key === "create");
  return (
    <div
      role="radiogroup"
      aria-label="Intent mode"
      style={{
        display: "inline-flex",
        gap: 2,
        padding: 2,
        borderRadius: 999,
        background: "var(--paper-100, #F7F5EF)",
        border: "1px solid var(--paper-300, #E8E6DD)",
      }}
    >
      {visible.map(({ key, label, Icon, title }) => {
        const active = value === key;
        return (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(key)}
            title={title}
            className="window-card__action"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "3px 10px",
              borderRadius: 999,
              border: "none",
              cursor: "pointer",
              fontSize: 11,
              fontWeight: active ? 600 : 500,
              letterSpacing: "0.02em",
              background: active ? "var(--color-background-accent, #e3fffa)" : "transparent",
              color: active ? "var(--color-foreground-accent, #1e4a42)" : "var(--ink-500, #5C5C58)",
              transition: "background 160ms ease, color 160ms ease",
            }}
          >
            <Icon size={12} strokeWidth={2} />
            {label}
          </button>
        );
      })}
    </div>
  );
}
