"use client";

import { useState } from "react";
import { Clock, ChevronRight } from "lucide-react";
import { useCanvasStore } from "@/lib/store";
import { tick } from "@/lib/api";
import { formatCETFull } from "@/lib/tz";

export function ClockBar() {
  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const [pending, setPending] = useState(false);

  async function step(steps: number) {
    if (pending) return;
    setPending(true);
    try {
      await tick(steps);
    } catch (err) {
      console.error(err);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="clock-bar" aria-label="Virtual clock">
      <Clock size={14} strokeWidth={2} style={{ color: "var(--ink-500)" }} />
      <span className="clock-bar__time" data-testid="clock-time">{formatCETFull(virtualNow)}</span>
      <button
        className="btn btn--ghost btn--sm"
        onClick={() => step(4)}
        disabled={pending}
        aria-label="Step +1 hour"
        title="Advance virtual clock by 1 hour"
      >
        <ChevronRight size={12} strokeWidth={2.4} style={{ marginRight: 2 }} /> 1h
      </button>
      <button
        className="btn btn--ghost btn--sm"
        onClick={() => step(24)}
        disabled={pending}
        aria-label="Step +6 hours"
        title="Advance virtual clock by 6 hours"
      >
        <ChevronRight size={12} strokeWidth={2.4} style={{ marginRight: 2 }} /> 6h
      </button>
    </div>
  );
}
