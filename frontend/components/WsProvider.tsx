"use client";

import { useEffect, useRef } from "react";
import { useCanvasStore } from "@/lib/store";
import { wsUrl } from "@/lib/api";
import type { WsOp } from "@/types";

export function WsProvider({ children }: { children: React.ReactNode }) {
  const applyOp = useCanvasStore((s) => s.applyOp);
  const lastSeq = useCanvasStore((s) => s.lastSeq);
  const wsRef = useRef<WebSocket | null>(null);
  const clientIdRef = useRef<string>("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (clientIdRef.current === "") {
      clientIdRef.current = `volta-${crypto.randomUUID().slice(0, 8)}`;
    }

    // Idempotency: don't reconnect if already open / connecting
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    let attempts = 0;

    function connect(since: number) {
      if (cancelled) return;
      const url = wsUrl(since, clientIdRef.current);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (ev) => {
        try {
          const frame = JSON.parse(ev.data) as WsOp;
          applyOp(frame);
          if (typeof document !== "undefined" && (frame as any).op) {
            document.body.dataset.lastOp = (frame as any).op;
          }
        } catch (err) {
          console.error("ws parse error", err);
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        attempts += 1;
        const delay = Math.min(8000, 500 * 2 ** Math.min(attempts, 5));
        reconnectTimer = setTimeout(() => {
          const currentSeq = useCanvasStore.getState().lastSeq;
          connect(currentSeq);
        }, delay);
      };

      ws.onerror = (e) => {
        console.warn("ws error", e);
      };

      ws.onopen = () => {
        attempts = 0;
      };
    }

    connect(useCanvasStore.getState().lastSeq);

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      const ws = wsRef.current;
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        ws.close(1000, "unmount");
      }
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>{children}</>;
}
