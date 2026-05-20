"use client";

import { HedgeBadge } from "@/components/icons";
import type { Window, NewsSpec } from "@/types";

type Props = { window: Window & { window_type: "news"; spec: NewsSpec } };

export function NewsWindow({ window: w }: Props) {
  const spec = w.spec;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <header style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
        {spec.headline && <h4 style={{ margin: 0, fontSize: 17, fontWeight: 600, color: "var(--ink-900, #141413)" }}>{spec.headline}</h4>}
        <HedgeBadge />
        {spec.severity && (
          <span className={`label ${spec.severity === "high" ? "label--danger-subtle" : spec.severity === "med" ? "label--warning-subtle" : "label--neutral"}`}>
            {spec.severity}
          </span>
        )}
      </header>
      {spec.body && <p style={{ margin: 0, color: "var(--ink-700, #2A2A28)", fontSize: 14, lineHeight: 1.5 }}>{spec.body}</p>}
      {!spec.headline && (
        <p style={{ margin: 0, color: "var(--ink-500, #5C5C58)", fontStyle: "italic", fontSize: 14 }}>
          Awaiting derived-news events at this virtual_now…
        </p>
      )}
    </div>
  );
}
