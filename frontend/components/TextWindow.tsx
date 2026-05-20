"use client";

import { useMemo } from "react";
import Markdown from "markdown-to-jsx";
import { Sparkles } from "lucide-react";
import { formatCET } from "@/lib/tz";
import { useCanvasStore } from "@/lib/store";
import type { Window, TextSpec } from "@/types";

type Props = { window: Window & { window_type: "text"; spec: TextSpec } };

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
      <span className="skel skel--w90" />
      <span className="skel skel--w70" />
      <span className="skel skel--w45" />
      <style jsx>{`
        .skeleton { display: flex; flex-direction: column; gap: 8px; padding: 6px 0; }
        .skel {
          display: block;
          height: 12px;
          background: linear-gradient(90deg,
            var(--paper-200, #F0EEE6) 0%,
            var(--paper-300, #E8E6DD) 50%,
            var(--paper-200, #F0EEE6) 100%);
          background-size: 200% 100%;
          animation: skel-shimmer 1.4s ease-in-out infinite;
          border-radius: 3px;
        }
        .skel--w90 { width: 90%; }
        .skel--w70 { width: 70%; }
        .skel--w45 { width: 45%; }
        @keyframes skel-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

/**
 * Post-process Sonnet body markdown to:
 *  - wrap inline citations `(`curve_name`, 2026-XX-XX HH:MM CET)` in <cite title="…">curve · HH:MM CET</cite>
 *  - wrap currency tokens `−€16.34/MWh` (and similar) in <span class="num num--neg">…</span>
 *  - wrap plain MWh/EUR numbers in <span class="num">…</span>
 *
 * The Markdown engine treats the wrapped HTML as raw inline.
 */
function decorateCitationsAndNums(md: string): string {
  let s = md;
  // (`curve_name`, 2026-03-06T23:45 CET) → <cite title="curve_name @ 2026-03-06T23:45 CET">curve · HH:MM CET</cite>
  s = s.replace(
    /\(`([^`]+)`,\s*([0-9T:\-+.]+)\s*(CET|UTC)\)/g,
    (_m, curve, ts, tz) => {
      const short = curve.split(/\s+/).slice(0, 2).join(" ");
      const hhmm = ts.length >= 16 ? ts.slice(11, 16) : ts;
      const title = `${curve} @ ${ts} ${tz}`;
      return ` <cite title="${title}">${short} · ${hhmm} ${tz}</cite>`;
    },
  );
  // -€16.34/MWh OR €125.09/MWh OR -€16.34 → number token (preserve leading whitespace)
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

export function TextWindow({ window: w }: Props) {
  const spec = w.spec;
  const pending = useCanvasStore((s) => s.pendingIntentId);
  const hasBody = (spec.body || "").trim().length > 0;
  const isStreaming = hasBody && pending !== null;
  const isSmall = w.state === "small";
  const decorated = useMemo(() => (hasBody ? decorateCitationsAndNums(spec.body) : ""), [spec.body, hasBody]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      {!hasBody ? (
        isSmall ? <ThinkingMode /> : <SkeletonLines />
      ) : (
        <div
          className={`narration body-fade-in ${isStreaming ? "is-streaming" : "is-done"}`}
        >
          <Markdown
            options={{
              overrides: {
                code: { component: "cite" },
                strong: { props: { style: { fontWeight: 600, color: "var(--ink-900, #141413)" } } },
                ul: { props: { style: { paddingLeft: 18, margin: "8px 0" } } },
                ol: { props: { style: { paddingLeft: 18, margin: "8px 0" } } },
              },
            }}
          >
            {decorated}
          </Markdown>
        </div>
      )}
      {spec.sources && spec.sources.length > 0 && hasBody && (
        <div className="body-fade-in" style={{ borderTop: "1px solid var(--paper-300, #E8E6DD)", paddingTop: 10, marginTop: 4 }}>
          <strong className="kicker" style={{ fontSize: 11, color: "var(--ink-500, #5C5C58)" }}>Sources</strong>
          <ul style={{ margin: "6px 0 0", paddingLeft: 0, listStyle: "none" }}>
            {spec.sources.map((s, i) => (
              <li key={i} style={{ marginBottom: 4, fontFamily: "var(--font-plex-mono, ui-monospace, monospace)", fontSize: 11.5, color: "var(--ink-700, #2A2A28)" }}>
                <span className="tabular-nums" style={{ color: "var(--ink-900, #141413)" }}>[{i + 1}]</span>
                {" "}
                <span className="tabular-nums" style={{ color: "var(--ink-900, #141413)" }}>{Number(s.value).toFixed(2)} {s.unit}</span>
                {" — "}
                <span>{s.source_curve}</span>
                {s.ts && <span style={{ color: "var(--ink-500, #5C5C58)" }}> · {formatCET(s.ts, "MMM d HH:mm")}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
