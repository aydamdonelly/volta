"use client";

import { useEffect, useState } from "react";
import { useCanvasStore } from "@/lib/store";
import { AppShell } from "@/components/AppShell";
import { Canvas } from "@/components/Canvas";
import { EmptyCanvas } from "@/components/EmptyCanvas";
import { NewsToasts } from "@/components/NewsToasts";
import { ReasoningBar } from "@/components/ReasoningBar";
import { RecommendationStrip } from "@/components/RecommendationStrip";
import { VoiceTextDot } from "@/components/VoiceTextDot";
import AddChartFab from "@/components/AddChartFab";

export default function Page() {
  const themeCount = useCanvasStore((s) => Object.keys(s.themes).length);
  const pendingIntentId = useCanvasStore((s) => s.pendingIntentId);
  const killSwitch = useCanvasStore((s) => s.killSwitch);
  const showEmpty = themeCount === 0 && !pendingIntentId;
  const [flashing, setFlashing] = useState(false);

  // Global kill switch: Cmd/Ctrl+K from anywhere wipes canvas + backend buffer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        e.stopPropagation();
        setFlashing(true);
        void killSwitch().finally(() => {
          window.setTimeout(() => setFlashing(false), 360);
        });
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [killSwitch]);

  return (
    <div style={{ display: "flex", flexDirection: "row", minHeight: "100vh" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <AppShell>
          <NewsToasts />
          <ReasoningBar />
          <RecommendationStrip />
          <main className="app-shell__main">{showEmpty ? <EmptyCanvas /> : <Canvas />}</main>
          <VoiceTextDot />
          <AddChartFab />
        </AppShell>
      </div>
      {flashing && (
        <div
          aria-hidden
          style={{
            position: "fixed",
            inset: 0,
            background: "var(--color-background-accent, #e3fffa)",
            opacity: 0.55,
            pointerEvents: "none",
            transition: "opacity 320ms ease",
            zIndex: 9999,
          }}
        />
      )}
    </div>
  );
}
