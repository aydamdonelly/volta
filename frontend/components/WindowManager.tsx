"use client";

import { useEffect, useRef } from "react";
import { X, LineChart, FileText, Newspaper, ShieldAlert, ChevronDown, Globe } from "lucide-react";
import { useCanvasStore } from "@/lib/store";
import { ChartWindow } from "./ChartWindow";
import { TextWindow } from "./TextWindow";
import { NewsWindow } from "./NewsWindow";
import { CounterWindow } from "./CounterWindow";
import { SearchWindow } from "./SearchWindow";
import { SearchButton } from "./SearchButton";

const TYPE_ICON = {
  chart: LineChart,
  text: FileText,
  news: Newspaper,
  counter: ShieldAlert,
  search: Globe,
} as const;

export function WindowManager({ windowId }: { windowId: string }) {
  const w = useCanvasStore((s) => s.windowIndex[windowId]);
  const dismissWindow = useCanvasStore((s) => s.dismissWindow);
  const expandWindow = useCanvasStore((s) => s.expandWindow);

  // Default open-state per window type. All open so canvas reads populated by default.
  const DEFAULT_OPEN: Record<string, boolean> = {
    chart: true,
    text: true,
    counter: true,
    news: true,
    search: true,
  };
  const autoExpandedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!w) return;
    if (autoExpandedRef.current.has(w.window_id)) return;
    autoExpandedRef.current.add(w.window_id);
    const shouldBeBig = DEFAULT_OPEN[w.window_type] ?? false;
    if (shouldBeBig && w.state !== "big") expandWindow(w.window_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [w?.window_id]);

  if (!w) return null;

  const TypeIcon = TYPE_ICON[w.window_type] ?? FileText;
  const isBig = w.state === "big";

  const cls =
    "window-card" +
    (w.window_type === "text" ? " window-card--text" : "") +
    (w.window_type === "news" ? " window-card--news" : "") +
    (w.window_type === "counter" ? " window-card--counter" : "") +
    (isBig ? " window-card--big" : " window-card--small");

  return (
    <article className={cls}>
      <div
        role="button"
        tabIndex={0}
        className="window-card__header window-card__toggle"
        onClick={(e) => {
          // Don't toggle if click was on the dismiss / search button
          const t = e.target as HTMLElement;
          if (t.closest(".window-card__dismiss")) return;
          if (t.closest('[aria-label="Search the web for context"]')) return;
          expandWindow(w.window_id);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            const t = e.target as HTMLElement;
            if (t.closest(".window-card__dismiss")) return;
            if (t.closest('[aria-label="Search the web for context"]')) return;
            e.preventDefault();
            expandWindow(w.window_id);
          }
        }}
        aria-expanded={isBig}
        aria-controls={`win-body-${w.window_id}`}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0, flex: 1 }}>
          <TypeIcon
            size={13}
            strokeWidth={2}
            style={{ color: "var(--ink-500, #5C5C58)", flexShrink: 0 }}
          />
          <div style={{ minWidth: 0, textAlign: "left" }}>
            <h3 className="window-card__title">{w.title}</h3>
            {w.summary_line && <p className="window-card__summary">{w.summary_line}</p>}
          </div>
        </div>
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {w.window_type !== "search" && <SearchButton window={w} />}
          <span
            className="window-card__chevron-btn"
            style={{ display: "inline-flex", alignItems: "center", padding: 2 }}
          >
            <ChevronDown
              size={14}
              strokeWidth={2}
              className="window-card__chevron"
              style={{
                color: "var(--ink-500, #5C5C58)",
                transform: isBig ? "rotate(0deg)" : "rotate(-90deg)",
                transition: "transform 280ms cubic-bezier(.23,1,.32,1)",
              }}
            />
          </span>
          <span
            role="button"
            tabIndex={0}
            className="window-card__dismiss btn btn--ghost btn--sm"
            onClick={(e) => {
              e.stopPropagation();
              dismissWindow(windowId);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                dismissWindow(windowId);
              }
            }}
            aria-label="Dismiss window"
            title="Dismiss"
            style={{ padding: 4, lineHeight: 0 }}
          >
            <X size={13} strokeWidth={2} />
          </span>
        </div>
      </div>
      <div
        id={`win-body-${w.window_id}`}
        className={`window-card__body window-card__body--${isBig ? "open" : "closed"}`}
        aria-hidden={!isBig}
      >
        <div className="window-card__body-inner">
          {w.window_type === "chart" && <ChartWindow window={w as any} />}
          {w.window_type === "text" && <TextWindow window={w as any} />}
          {w.window_type === "news" && <NewsWindow window={w as any} />}
          {w.window_type === "counter" && <CounterWindow window={w as any} />}
          {w.window_type === "search" && <SearchWindow window={w as any} />}
        </div>
      </div>
    </article>
  );
}
