"use client";

import { useEffect, useMemo, useState } from "react";
import { useCanvasStore } from "@/lib/store";
import { Sparkle } from "@/components/icons";

const FADE_OUT_AFTER_DONE_MS = 1400;

const STAGE_ORDER = ["intake", "classify", "classify_done", "resolve", "narrate", "narrate_done"] as const;
type StageId = (typeof STAGE_ORDER)[number] | string;

const PIPELINE_CHIPS: Array<{ id: string; label: string; matches: string[] }> = [
  { id: "intake",   label: "intake",    matches: ["intake"] },
  { id: "classify", label: "classify",  matches: ["classify", "classify_done"] },
  { id: "resolve",  label: "resolve",   matches: ["resolve"] },
  { id: "narrate",  label: "narrate",   matches: ["narrate", "narrate_done"] },
];

const NARRATING_VERBS = [
  "Querying Sonnet…",
  "Aggregating drivers…",
  "Composing counter-argument…",
  "Cross-checking residual…",
  "Patching narration…",
];

function chipState(stage: StageId, currentStage: StageId, doneStages: Set<string>) {
  if (doneStages.has(stage as string)) return "done";
  if ((currentStage as string) === stage) return "active";
  return "pending";
}

export function ReasoningBar() {
  const reasoning = useCanvasStore((s) => s.reasoning);
  const pendingIntentId = useCanvasStore((s) => s.pendingIntentId);
  const [visible, setVisible] = useState(false);
  const [doneStages, setDoneStages] = useState<Set<string>>(new Set());
  const [verbIdx, setVerbIdx] = useState(0);

  // Track which stages we've seen for the CURRENT intent
  useEffect(() => {
    if (!reasoning) {
      setDoneStages(new Set());
      return;
    }
    setDoneStages((prev) => {
      const next = new Set(prev);
      // Mark previous stages as done
      const ix = STAGE_ORDER.indexOf(reasoning.stage as any);
      if (ix >= 0) {
        STAGE_ORDER.slice(0, ix).forEach((s) => next.add(s));
      }
      // Also mark `narrate_done` as itself done
      if (reasoning.stage === "narrate_done") next.add("narrate");
      return next;
    });
  }, [reasoning?.stage, reasoning?.updated_at]);

  useEffect(() => {
    if (reasoning) setVisible(true);
  }, [reasoning?.updated_at]);

  // Fade out shortly after done
  useEffect(() => {
    if (pendingIntentId === null && visible) {
      const t = setTimeout(() => setVisible(false), FADE_OUT_AFTER_DONE_MS);
      return () => clearTimeout(t);
    }
  }, [pendingIntentId, visible]);

  // Rotate verb during narrate phase
  useEffect(() => {
    if (reasoning?.stage !== "narrate") return;
    const t = setInterval(() => setVerbIdx((i) => (i + 1) % NARRATING_VERBS.length), 700);
    return () => clearInterval(t);
  }, [reasoning?.stage]);

  // Reset on clear (no reasoning, no pending)
  useEffect(() => {
    if (!reasoning && pendingIntentId === null) {
      setDoneStages(new Set());
      setVerbIdx(0);
    }
  }, [reasoning, pendingIntentId]);

  const displayMessage = useMemo(() => {
    if (!reasoning) return "";
    if (reasoning.stage === "narrate") return NARRATING_VERBS[verbIdx];
    return reasoning.message;
  }, [reasoning, verbIdx]);

  if (!reasoning && !visible) return null;

  return (
    <div className={`reasoning-bar ${visible ? "is-visible" : ""}`} role="status" aria-live="polite">
      <Sparkle teal />
      <span className="reasoning-bar__stage" style={{ flexShrink: 0 }}>
        {reasoning?.stage ?? ""}
      </span>
      <span className="reasoning-bar__message" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {displayMessage}
      </span>
      <span className="reasoning-bar__chips">
        {PIPELINE_CHIPS.map((c) => {
          const state = chipState(c.id, reasoning?.stage ?? "", doneStages);
          return (
            <span key={c.id} className={`pipeline-chip pipeline-chip--${state}`} title={c.label}>
              <span className="pipeline-chip__dot" />
              <span className="pipeline-chip__label">{c.label}</span>
            </span>
          );
        })}
      </span>
      <style jsx>{`
        .reasoning-bar__chips {
          display: inline-flex;
          gap: 6px;
          margin-left: 12px;
          align-items: center;
          flex-shrink: 0;
        }
        .pipeline-chip {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 2px 8px 2px 6px;
          font-family: var(--font-plex-mono, ui-monospace, monospace);
          font-size: 10.5px;
          line-height: 1;
          border-radius: 9999px;
          border: 1px solid transparent;
          transition: all 220ms cubic-bezier(.23,1,.32,1);
        }
        .pipeline-chip__dot {
          width: 6px; height: 6px;
          border-radius: 50%;
          background: var(--ink-300, #8C8C88);
        }
        .pipeline-chip__label {
          color: var(--ink-500, #5C5C58);
          text-transform: lowercase;
          letter-spacing: 0.02em;
        }
        .pipeline-chip--pending { opacity: 0.45; }
        .pipeline-chip--active {
          border-color: var(--accent, #487d74);
          background: var(--accent-soft, #DCEDE9);
        }
        .pipeline-chip--active .pipeline-chip__dot {
          background: var(--accent, #487d74);
          animation: chip-pulse 1.1s ease-in-out infinite;
        }
        .pipeline-chip--active .pipeline-chip__label {
          color: var(--accent-text, #1e4a42);
        }
        .pipeline-chip--done .pipeline-chip__dot {
          background: var(--accent, #487d74);
        }
        .pipeline-chip--done .pipeline-chip__label {
          color: var(--ink-700, #2A2A28);
        }
        @keyframes chip-pulse {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.4); opacity: 0.65; }
        }
      `}</style>
    </div>
  );
}
