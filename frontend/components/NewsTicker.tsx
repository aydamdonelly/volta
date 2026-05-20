"use client";

import { useCanvasStore } from "@/lib/store";
import { formatCET } from "@/lib/tz";
import { submitIntent } from "@/lib/api";

export function NewsTicker() {
  const ticker = useCanvasStore((s) => s.ticker);
  const setPending = useCanvasStore((s) => s.setPendingIntent);
  const clearCanvas = useCanvasStore((s) => s.clearCanvas);
  const themes = useCanvasStore((s) => s.themes);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const virtualNow = useCanvasStore((s) => s.virtualNow);

  async function onClickEvent(news_id: string) {
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
      console.error(err);
    }
  }

  if (ticker.length === 0) {
    return (
      <div className="news-ticker" aria-label="Derived news ticker (empty)">
        <span style={{ color: "var(--text-muted)" }}>No derived news yet — step the clock to advance.</span>
      </div>
    );
  }

  return (
    <div className="news-ticker" aria-label="Derived news ticker" role="list">
      {ticker.map((ev) => (
        <button
          key={ev.news_id}
          className="news-ticker__item"
          onClick={() => onClickEvent(ev.news_id)}
          type="button"
          role="listitem"
          title={ev.hedged_text}
        >
          <span className={`news-ticker__dot news-ticker__dot--${ev.severity}`} aria-hidden="true" />
          <span>{ev.headline}</span>
          <small style={{ color: "var(--text-muted)" }}>context, not proof</small>
          <small style={{ color: "var(--text-muted)" }}>· {formatCET(ev.ts, "HH:mm")}</small>
        </button>
      ))}
    </div>
  );
}
