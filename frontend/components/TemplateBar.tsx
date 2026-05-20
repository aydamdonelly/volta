"use client";

import { useEffect, useRef, useState } from "react";
import { useCanvasStore } from "@/lib/store";
import { saveTemplate, restoreTemplate } from "@/lib/api";
import type { Window } from "@/types";

function buildSnapshot(state: { themes: Record<string, any>; windowIndex: Record<string, Window>; virtualNow: string }) {
  const windows = Object.values(state.windowIndex);
  return { windows, themes: Object.keys(state.themes), virtual_now: state.virtualNow };
}

type Mode = "idle" | "save" | "restore";

export function TemplateBar() {
  const [mode, setMode] = useState<Mode>("idle");
  const [name, setName] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const themes = useCanvasStore((s) => s.themes);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const loadCanvasState = useCanvasStore((s) => s.loadCanvasState);

  useEffect(() => {
    if (mode !== "idle") setTimeout(() => inputRef.current?.focus(), 30);
  }, [mode]);

  function showStatus(msg: string) {
    setStatus(msg);
    setTimeout(() => setStatus(null), 3000);
  }

  async function onSave() {
    if (!name.trim()) return;
    try {
      await saveTemplate(name.trim(), buildSnapshot({ themes, windowIndex, virtualNow }));
      showStatus(`Saved “${name.trim()}”`);
      setName("");
      setMode("idle");
    } catch (err) {
      showStatus(`Save failed: ${err}`);
    }
  }

  async function onRestore() {
    if (!name.trim()) return;
    try {
      const r = await restoreTemplate(name.trim());
      loadCanvasState(r.canvas_snapshot);
      showStatus(`Restored “${name.trim()}”`);
      setName("");
      setMode("idle");
    } catch (err) {
      showStatus(`Restore failed: ${err}`);
    }
  }

  return (
    <div className="template-bar" aria-label="Templates" style={{ position: "relative", display: "flex", gap: 8, alignItems: "center" }}>
      <button className="btn btn--outline btn--sm" onClick={() => setMode(mode === "save" ? "idle" : "save")}>
        Save
      </button>
      <button className="btn btn--outline btn--sm" onClick={() => setMode(mode === "restore" ? "idle" : "restore")}>
        Restore
      </button>
      {status && <small style={{ color: "var(--ink-500, #5C5C58)" }}>{status}</small>}
      {mode !== "idle" && (
        <div className="template-popover" role="dialog" aria-label={`${mode} template`}>
          <label className="kicker" style={{ marginBottom: 6, display: "block" }}>
            {mode === "save" ? "Save current canvas as" : "Restore template name"}
          </label>
          <div style={{ display: "flex", gap: 6 }}>
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              placeholder="demo_a"
              onKeyDown={(e) => {
                if (e.key === "Enter") (mode === "save" ? onSave() : onRestore());
                if (e.key === "Escape") { setMode("idle"); setName(""); }
              }}
              style={{
                flex: 1, padding: "6px 10px", border: "1px solid var(--paper-300, #E8E6DD)",
                borderRadius: 8, fontSize: 14, fontFamily: "var(--font-plex-mono, ui-monospace, monospace)",
                background: "var(--paper-50, #FAF9F5)",
              }}
            />
            <button className="btn btn--sm" onClick={mode === "save" ? onSave : onRestore} disabled={!name.trim()}>
              {mode === "save" ? "Save" : "Load"}
            </button>
          </div>
          <small style={{ display: "block", marginTop: 6, color: "var(--ink-500, #5C5C58)", fontSize: 11 }}>
            a–z, 0–9, _, -
          </small>
        </div>
      )}
      <style jsx>{`
        .template-popover {
          position: absolute;
          top: 100%;
          right: 0;
          margin-top: 8px;
          background: var(--paper-50, #FAF9F5);
          border: 1px solid var(--paper-300, #E8E6DD);
          border-radius: 8px;
          padding: 12px;
          min-width: 280px;
          box-shadow: 0 12px 32px rgba(20,20,19,.10);
          z-index: 100;
          animation: pop-in 180ms cubic-bezier(.23,1,.32,1);
        }
        @keyframes pop-in {
          from { opacity: 0; transform: translateY(-4px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  );
}
