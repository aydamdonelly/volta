"use client";

import { useCanvasStore } from "@/lib/store";
import { ThemeSection } from "./ThemeSection";

export function Canvas() {
  const themes = useCanvasStore((s) => s.themes);
  const themeIds = Object.keys(themes);
  return (
    <div>
      {themeIds.map((tid) => (
        <ThemeSection key={tid} themeId={tid} />
      ))}
    </div>
  );
}
