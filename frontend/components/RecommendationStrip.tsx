"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { useCanvasStore } from "@/lib/store";

/**
 * Renders the intent_recommendation that the orchestrator emits.
 * Currently DEAD-LETTERED in the store; this strip surfaces it.
 * Appears under the ReasoningBar once `done` fires. Auto-fades 20s later
 * unless the user keeps interacting.
 */
export function RecommendationStrip() {
  const rec = useCanvasStore((s) => s.intentRecommendation);
  const pending = useCanvasStore((s) => s.pendingIntentId);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (rec && !pending) {
      setVisible(true);
      const t = setTimeout(() => setVisible(false), 20_000);
      return () => clearTimeout(t);
    }
    if (pending) setVisible(false);
  }, [rec, pending]);

  if (!rec || !visible) return null;

  return (
    <div className="recommendation-strip" role="region" aria-label="Volta recommendation">
      <span className="kicker">recommendation</span>
      <span className="recommendation-strip__text">{rec.text}</span>
      <span className="recommendation-strip__tag">layout: {rec.thesis_key}</span>
      <button
        type="button"
        className="recommendation-strip__close"
        onClick={() => setVisible(false)}
        aria-label="Dismiss recommendation"
      >
        <X size={12} strokeWidth={2.4} />
      </button>
      <style jsx>{`
        .recommendation-strip {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 12px 24px;
          background: var(--paper-100, #F4F3EE);
          border-bottom: 1px solid var(--paper-300, #E8E6DD);
          font-size: 14px;
          color: var(--ink-900, #141413);
          animation: rec-slide-in 320ms cubic-bezier(.23,1,.32,1);
        }
        .recommendation-strip__text {
          flex: 1;
          line-height: 1.45;
        }
        .recommendation-strip__tag {
          font-family: var(--font-plex-mono, ui-monospace, monospace);
          font-size: 11px;
          color: var(--ink-500, #5C5C58);
          background: var(--paper-50, #FAF9F5);
          padding: 3px 9px;
          border-radius: 9999px;
          border: 1px solid var(--paper-300, #E8E6DD);
          text-transform: lowercase;
          letter-spacing: 0.02em;
        }
        .recommendation-strip__close {
          background: transparent;
          border: 0;
          cursor: pointer;
          color: var(--ink-500, #5C5C58);
          padding: 4px;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
        }
        .recommendation-strip__close:hover {
          background: var(--paper-200, #F0EEE6);
          color: var(--ink-900, #141413);
        }
        @keyframes rec-slide-in {
          from { opacity: 0; transform: translateY(-6px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
