"use client";

import { useMemo } from "react";
import Markdown from "markdown-to-jsx";
import { Sparkles } from "lucide-react";
import { formatCET } from "@/lib/tz";
import { useCanvasStore } from "@/lib/store";
import type { Window, CounterSpec } from "@/types";

type Props = { window: Window & { window_type: "counter"; spec: CounterSpec } };

function ThinkingMode() {
  return (
    <div
      className="window-card--thinking"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 4px",
        color: "var(--ink-500, #5C5C58)",
        fontSize: 12,
        fontStyle: "italic",
      }}
      aria-busy="true"
      aria-live="polite"
    >
      <Sparkles
        size={13}
        strokeWidth={2}
        style={{ flexShrink: 0, animation: "thinking-pulse 1.6s ease-in-out infinite" }}
      />
      <span>thinking…</span>
      <style jsx>{`
        @keyframes thinking-pulse {
          0%, 100% { opacity: 0.45; }
          50% { opacity: 1; }
        }
      `}</style>
    </div>
  );
}

function SkeletonLines() {
  return (
    <div className="skeleton" aria-busy="true">
      <span className="skel skel--w80" />
      <span className="skel skel--w50" />
      <style jsx>{`
        .skeleton { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
        .skel {
          height: 11px;
          background: linear-gradient(90deg,
            var(--paper-200, #F0EEE6) 0%,
            var(--paper-300, #E8E6DD) 50%,
            var(--paper-200, #F0EEE6) 100%);
          background-size: 200% 100%;
          animation: skel-shimmer 1.4s ease-in-out infinite;
          border-radius: 3px;
        }
        .skel--w80 { width: 80%; }
        .skel--w50 { width: 50%; }
        @keyframes skel-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

function decorateCitationsAndNums(md: string): string {
  let s = md;
  s = s.replace(
    /\(`([^`]+)`,\s*([0-9T:\-+.]+)\s*(CET|UTC)\)/g,
    (_m, curve, ts, tz) => {
      const short = curve.split(/\s+/).slice(0, 2).join(" ");
      const hhmm = ts.length >= 16 ? ts.slice(11, 16) : ts;
      const title = `${curve} @ ${ts} ${tz}`;
      return ` <cite title="${title}">${short} · ${hhmm} ${tz}</cite>`;
    },
  );
  s = s.replace(
    /(\s*)(-?[−–]?€\s?[\d][\d.,]*(?:\s?\/(?:MWh\/h|MWh|kWh|EUA))?)/g,
    (_m, lead, num) => {
      const isNeg = /[-−–]/.test(num);
      const cls = isNeg ? "num num--neg" : "num";
      return `${lead || " "}<span class="${cls}">${num.trim()}</span>`;
    },
  );
  return s;
}

export function CounterWindow({ window: w }: Props) {
  const spec = w.spec;
  const pending = useCanvasStore((s) => s.pendingIntentId);
  const hasBody = (spec.body || "").trim().length > 0;
  const isStreaming = hasBody && pending !== null;
  const hasPoints = (spec.points?.length ?? 0) > 0;
  const isSmall = w.state === "small";
  const decorated = useMemo(() => (hasBody ? decorateCitationsAndNums(spec.body) : ""), [spec.body, hasBody]);

  if (!hasBody && !hasPoints && isSmall) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <header style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
          <span className="label label--warning-subtle">counter-evidence</span>
        </header>
        <ThinkingMode />
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <header style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
        <span className="label label--warning-subtle">counter-evidence</span>
        {spec.points?.length ? (
          <span className="kicker" style={{ fontSize: 10 }}>
            {spec.points.length} signal{spec.points.length === 1 ? "" : "s"}
          </span>
        ) : null}
      </header>

      {/* Numbers FIRST */}
      {spec.points && spec.points.length > 0 && (
        <ul className="points-list" style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 8 }}>
          {spec.points.map((p, i) => (
            <li
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr auto",
                columnGap: 10,
                rowGap: 2,
                alignItems: "baseline",
                paddingBottom: 8,
                borderBottom: i < spec.points.length - 1 ? "1px dashed var(--paper-300, #E8E6DD)" : "none",
              }}
            >
              <span style={{ fontSize: 13, color: "var(--ink-900, #141413)", fontWeight: 500 }}>{p.claim}</span>
              {typeof p.value === "number" && Number.isFinite(p.value) ? (
                <span className="tabular-nums" style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-900, #141413)" }}>
                  {p.value.toFixed(2)}{" "}
                  <span style={{ color: "var(--ink-500, #5C5C58)", fontWeight: 400, fontSize: 11 }}>{p.unit}</span>
                </span>
              ) : (
                <span />
              )}
              <span
                style={{
                  gridColumn: "1 / -1",
                  fontSize: 11,
                  fontFamily: "var(--font-plex-mono, ui-monospace, monospace)",
                  color: "var(--ink-500, #5C5C58)",
                }}
              >
                {p.source_curve}
                {p.ts ? ` · ${formatCET(p.ts, "MMM d HH:mm")}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Counter-narrative BELOW */}
      {!hasBody ? (
        <SkeletonLines />
      ) : (
        <div
          className={`narration body-fade-in ${isStreaming ? "is-streaming" : "is-done"}`}
          style={{ borderTop: "1px solid var(--paper-300, #E8E6DD)", paddingTop: 12 }}
        >
          <Markdown
            options={{
              overrides: {
                code: { component: "cite" },
                strong: { props: { style: { fontWeight: 600, color: "var(--ink-900, #141413)" } } },
              },
            }}
          >
            {decorated}
          </Markdown>
        </div>
      )}
    </div>
  );
}
