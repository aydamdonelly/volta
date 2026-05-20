"use client";

import Image from "next/image";
import { ClockBar } from "./ClockBar";
import { TemplateBar } from "./TemplateBar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <header className="app-shell__header">
        <div className="app-shell__brand">
          <Image src="/volta-logo.png" alt="Volta" width={32} height={32} priority />
          <h1>Volta</h1>
          <small>Energy Trader&rsquo;s Copilot</small>
        </div>
        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <ClockBar />
          <TemplateBar />
        </div>
      </header>
      {children}
    </div>
  );
}
