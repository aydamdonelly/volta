"use client";

export function Sparkle({ teal = false, label }: { teal?: boolean; label?: string }) {
  return (
    <span
      className={`sparkle${teal ? " sparkle--teal" : ""}`}
      aria-hidden={!label}
      aria-label={label}
      role={label ? "status" : undefined}
    />
  );
}
