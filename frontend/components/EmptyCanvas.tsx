"use client";

import Image from "next/image";

export function EmptyCanvas() {
  return (
    <div className="empty-canvas">
      <Image
        src="/volta-logo.png"
        alt="Volta"
        width={200}
        height={200}
        priority
        className="empty-canvas__logo"
      />
      <h2>An empty canvas.</h2>
      <p style={{ maxWidth: 560 }}>
        Press <kbd>/</kbd> to type your thesis or <kbd>Space</kbd> to speak. Volta composes a fresh
        canvas from the live Volue Insight + Optimeering catalog — every run a new painting.
      </p>
      <p style={{ fontSize: 12, color: "var(--ink-500, #5C5C58)", marginTop: 16 }}>
        <kbd>⌘</kbd>/<kbd>Ctrl</kbd>+<kbd>K</kbd> wipes everything (canvas, in-flight calls, caches) — full restart.
      </p>
      <p
        style={{
          fontSize: 12,
          color: "var(--ink-500, #5C5C58)",
          marginTop: 24,
          fontFamily: "var(--font-plex-mono, ui-monospace, monospace)",
        }}
      >
        powered by Volue Insight · Optimeering · Anthropic · Wave
      </p>
    </div>
  );
}
