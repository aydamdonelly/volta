"use client";

import { useRef, useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { enrichSearch } from "@/lib/api";
import { useCanvasStore } from "@/lib/store";
import type { Window } from "@/types";

interface Props {
  window: Window;
}

export function SearchButton({ window: w }: Props) {
  const [loading, setLoading] = useState(false);
  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const cooldownRef = useRef(0);

  async function trigger(e: React.MouseEvent | React.KeyboardEvent) {
    e.stopPropagation();
    if (loading) return;
    const now = Date.now();
    if (now - cooldownRef.current < 1500) return;
    cooldownRef.current = now;
    setLoading(true);
    try {
      await enrichSearch({
        window_id: w.window_id,
        theme_id: w.theme_id,
        context: {
          window_type: w.window_type,
          title: w.title,
          summary_line: w.summary_line,
          curve_keys: w.curve_keys,
          virtual_now: virtualNow,
        },
      });
    } catch (err) {
      console.warn("search/enrich failed", err);
    } finally {
      // Backend will spawn a new search window via WS — clear local spinner after a brief delay.
      setTimeout(() => setLoading(false), 1200);
    }
  }

  return (
    <span
      role="button"
      tabIndex={0}
      onClick={trigger}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          trigger(e);
        }
      }}
      aria-label="Search the web for context"
      title="Search the web for context"
      style={{
        padding: 4,
        lineHeight: 0,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        color: "var(--color-foreground-neutral-subtle, #5d7570)",
        cursor: loading ? "wait" : "pointer",
      }}
      className="window-card__search-btn btn btn--ghost btn--sm"
    >
      {loading ? (
        <Loader2 size={13} strokeWidth={2} className="search-button__spinner" />
      ) : (
        <Search size={13} strokeWidth={2} />
      )}
    </span>
  );
}
