"use client";

import { useState } from "react";
import { Bell, BellOff, Pin, FileText, ChevronRight } from "lucide-react";
import { useCanvasStore } from "@/lib/store";
import { submitIntent } from "@/lib/api";
import { formatCET } from "@/lib/tz";
import { HedgeBadge } from "@/components/icons";

export function SuggestionsSidebar() {
  const ticker = useCanvasStore((s) => s.ticker);
  const themes = useCanvasStore((s) => s.themes);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const setPending = useCanvasStore((s) => s.setPendingIntent);
  const clearCanvas = useCanvasStore((s) => s.clearCanvas);
  const dismissTickerItem = useCanvasStore((s) => s.dismissTickerItem);
  const [muted, setMuted] = useState(false);

  const watching = muted ? [] : ticker.slice(0, 8);

  async function onChipClick(news_id: string) {
    try {
      clearCanvas("new_intent");
      const canvas_state = {
        themes: Object.keys(themes),
        window_ids: Object.keys(windowIndex),
        virtual_now: virtualNow,
      };
      const r = await submitIntent({ news_id, canvas_state });
      setPending(r.intent_id);
    } catch (err) {
      console.error("UC2 intent failed", err);
    }
  }

  return (
    <aside className="sidebar" aria-label="Watching & themes sidebar">
      {/* ===== Header ===== */}
      <header className="sidebar__head">
        <span className="sidebar__title">Volta</span>
        <button
          type="button"
          className="sidebar__bell"
          aria-label={muted ? "Unmute notifications" : "Mute notifications"}
          title={muted ? "Notifications muted" : "Notifications on"}
          onClick={() => setMuted((m) => !m)}
        >
          {muted ? <BellOff size={14} /> : <Bell size={14} />}
        </button>
      </header>

      {/* ===== WATCHING section ===== */}
      <section className="sidebar__section">
        <h3 className="sidebar__section-title">
          <span>Watching</span>
          <span className="sidebar__count">{watching.length}</span>
        </h3>
        {watching.length === 0 ? (
          <div className="sidebar__empty">
            Signals appear here as Volta finds relevant context.
          </div>
        ) : (
          <ul className="sidebar__list">
            {watching.map((ev) => (
              <li key={ev.news_id} className={`sidebar__chip sidebar__chip--${ev.severity}`}>
                <button
                  type="button"
                  onClick={() => onChipClick(ev.news_id)}
                  className="sidebar__chip-btn"
                  aria-label={`Open: ${ev.headline}`}
                >
                  <div className="sidebar__chip-head">
                    <span className={`sidebar__chip-dot sidebar__chip-dot--${ev.severity}`} aria-hidden />
                    <span className="sidebar__chip-sev">{ev.severity}</span>
                    <span className="sidebar__chip-time">{formatCET(ev.ts, "HH:mm")}</span>
                  </div>
                  <div className="sidebar__chip-headline">{ev.headline}</div>
                  <div className="sidebar__chip-foot">
                    <HedgeBadge compact />
                    <ChevronRight size={12} className="sidebar__chip-arrow" />
                  </div>
                </button>
                <button
                  type="button"
                  className="sidebar__chip-dismiss"
                  aria-label="Dismiss"
                  onClick={(e) => {
                    e.stopPropagation();
                    dismissTickerItem(ev.news_id);
                  }}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ===== PINNED THEMES (stub) ===== */}
      <section className="sidebar__section">
        <h3 className="sidebar__section-title">
          <Pin size={11} strokeWidth={2.4} style={{ display: "inline-block", marginRight: 4, verticalAlign: "middle" }} />
          <span>Pinned themes</span>
        </h3>
        <div className="sidebar__empty">No pinned themes yet. Pin one from the canvas header.</div>
      </section>

      {/* ===== TEMPLATES (stub for now) ===== */}
      <section className="sidebar__section">
        <h3 className="sidebar__section-title">
          <FileText size={11} strokeWidth={2.4} style={{ display: "inline-block", marginRight: 4, verticalAlign: "middle" }} />
          <span>Templates</span>
        </h3>
        <div className="sidebar__empty">Save a canvas as template (top-right) to see it here.</div>
      </section>
    </aside>
  );
}
