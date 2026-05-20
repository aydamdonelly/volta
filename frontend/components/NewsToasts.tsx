"use client";

import { useEffect, useRef, useState } from "react";
import { X, Zap, Info, AlertTriangle, AlertOctagon } from "lucide-react";
import { useCanvasStore } from "@/lib/store";
import { submitIntent } from "@/lib/api";
import { formatCET } from "@/lib/tz";
import type { DerivedNewsEvent } from "@/types";

// Severity → TTL. High persists until dismissed (Infinity).
const TTL_BY_SEVERITY: Record<DerivedNewsEvent["severity"], number> = {
  low: 5_000,
  med: 8_000,
  high: Number.POSITIVE_INFINITY,
};
const MAX_TOASTS = 4;
const TICK_MS = 100;          // countdown ring refresh
const FADE_OUT_MS = 200;

const SEV_ICON = { low: Info, med: AlertTriangle, high: AlertOctagon } as const;

// Mock events carry `kind` and `body` smuggled onto the event payload.
type EnrichedEvent = DerivedNewsEvent & { kind?: string; body?: string };

interface VisibleToast {
  ev: EnrichedEvent;
  ttl: number;
  arrivedAt: number;
  remainingMs: number;       // recomputed each tick
  leaving?: boolean;
}

export function NewsToasts() {
  const ticker = useCanvasStore((s) => s.ticker);
  const setPending = useCanvasStore((s) => s.setPendingIntent);
  const clearCanvas = useCanvasStore((s) => s.clearCanvas);
  const themes = useCanvasStore((s) => s.themes);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const dismissTickerItem = useCanvasStore((s) => s.dismissTickerItem);

  const [visible, setVisible] = useState<VisibleToast[]>([]);
  const hoveredIdsRef = useRef<Set<string>>(new Set());
  const lastTickRef = useRef<number>(Date.now());

  // Push newest event into the toast stack.
  useEffect(() => {
    if (ticker.length === 0) return;
    const top = ticker[0] as EnrichedEvent;
    setVisible((prev) => {
      if (prev.some((t) => t.ev.news_id === top.news_id)) return prev;
      const ttl = TTL_BY_SEVERITY[top.severity] ?? TTL_BY_SEVERITY.med;
      const next: VisibleToast = {
        ev: top,
        ttl,
        arrivedAt: Date.now(),
        remainingMs: ttl,
      };
      return [next, ...prev].slice(0, MAX_TOASTS);
    });
  }, [ticker]);

  // Countdown loop — decrements remainingMs unless toast is hovered or persistent.
  useEffect(() => {
    if (visible.length === 0) return;
    lastTickRef.current = Date.now();
    const t = window.setInterval(() => {
      const now = Date.now();
      const delta = now - lastTickRef.current;
      lastTickRef.current = now;
      setVisible((prev) => {
        let mutated = false;
        const next = prev.map((tt) => {
          if (tt.leaving) return tt;
          if (!Number.isFinite(tt.ttl)) return tt;
          if (hoveredIdsRef.current.has(tt.ev.news_id)) return tt;
          const remainingMs = Math.max(0, tt.remainingMs - delta);
          if (remainingMs !== tt.remainingMs) mutated = true;
          return { ...tt, remainingMs };
        });
        // Mark expired toasts as leaving (triggers fade-out CSS).
        const withLeave = next.map((tt) =>
          !tt.leaving && Number.isFinite(tt.ttl) && tt.remainingMs <= 0
            ? { ...tt, leaving: true }
            : tt,
        );
        return mutated || withLeave.some((tt, i) => tt.leaving !== next[i].leaving)
          ? withLeave
          : prev;
      });
    }, TICK_MS);
    return () => window.clearInterval(t);
  }, [visible.length]);

  // After fade-out animation, remove leaving toasts from the DOM.
  useEffect(() => {
    const leavingIds = visible.filter((v) => v.leaving).map((v) => v.ev.news_id);
    if (leavingIds.length === 0) return;
    const timeout = window.setTimeout(() => {
      setVisible((prev) => prev.filter((v) => !leavingIds.includes(v.ev.news_id)));
    }, FADE_OUT_MS);
    return () => window.clearTimeout(timeout);
  }, [visible]);

  async function onInvestigate(ev: EnrichedEvent) {
    try {
      clearCanvas("new_intent");
      const canvas_state = {
        themes: Object.keys(themes),
        window_ids: Object.keys(windowIndex),
        virtual_now: virtualNow,
      };
      const r = await submitIntent({ news_id: ev.news_id, canvas_state });
      setPending(r.intent_id);
    } catch (err) {
      console.error(err);
    } finally {
      setVisible((prev) =>
        prev.map((tt) => (tt.ev.news_id === ev.news_id ? { ...tt, leaving: true } : tt)),
      );
    }
  }

  function onClose(news_id: string) {
    setVisible((prev) =>
      prev.map((tt) => (tt.ev.news_id === news_id ? { ...tt, leaving: true } : tt)),
    );
    dismissTickerItem(news_id);
  }

  function onMouseEnter(news_id: string) {
    hoveredIdsRef.current.add(news_id);
  }
  function onMouseLeave(news_id: string) {
    hoveredIdsRef.current.delete(news_id);
  }

  return (
    <div className="toast-stack" aria-label="Derived news notifications" aria-live="polite">
      {visible.map((tt) => {
        const sev = tt.ev.severity;
        const isBreaking = tt.ev.kind === "breaking" || sev === "high";
        const persists = !Number.isFinite(tt.ttl);
        const SevIcon = SEV_ICON[sev as keyof typeof SEV_ICON] ?? Info;
        const progress = Number.isFinite(tt.ttl)
          ? Math.max(0, tt.remainingMs / tt.ttl)
          : 1;
        const classes = [
          "toast",
          `toast--${sev}`,
          isBreaking ? "toast--breaking" : "",
          persists ? "toast--persist" : "",
          tt.leaving ? "toast--leaving" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return (
          <div
            key={tt.ev.news_id}
            className={classes}
            role="alert"
            onMouseEnter={() => onMouseEnter(tt.ev.news_id)}
            onMouseLeave={() => onMouseLeave(tt.ev.news_id)}
            style={{ ["--toast-progress" as any]: progress }}
          >
            <header className="toast__head">
              {isBreaking ? (
                <Zap size={14} strokeWidth={2.25} className="toast__zap" aria-hidden />
              ) : (
                <SevIcon size={14} strokeWidth={2} className="toast__icon" aria-hidden />
              )}
              <span className="toast__sev">
                {isBreaking ? "Breaking" : sev}
              </span>
              <span className="toast__time">{formatCET(tt.ev.ts, "HH:mm")}</span>
              <button
                type="button"
                className="toast__close"
                onClick={() => onClose(tt.ev.news_id)}
                aria-label="Dismiss"
              >
                <X size={14} strokeWidth={2} />
              </button>
            </header>
            <div className="toast__title">{tt.ev.headline}</div>
            {tt.ev.body ? <div className="toast__body">{tt.ev.body}</div> : null}
            {tt.ev.hedged_text ? (
              <div className="toast__hedge">{tt.ev.hedged_text}</div>
            ) : null}
            <button
              type="button"
              className="toast__cta"
              onClick={() => onInvestigate(tt.ev)}
            >
              Investigate
            </button>
            <div className="toast__countdown" aria-hidden />
          </div>
        );
      })}
    </div>
  );
}
