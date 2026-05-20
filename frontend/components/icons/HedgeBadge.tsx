"use client";
import { Info } from "lucide-react";

/** "context, not proof" hedge label — single source of truth. */
export function HedgeBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span className="label label--info-subtle" aria-label="hedge label">
      <Info
        size={11}
        strokeWidth={2}
        style={{ marginRight: 4, marginBottom: -1, display: "inline-block", verticalAlign: "middle" }}
      />
      {compact ? "context" : "context, not proof"}
    </span>
  );
}
