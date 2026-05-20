import { create } from "zustand";
import type {
  Window,
  Theme,
  GridLayoutItem,
  DerivedNewsEvent,
  CanvasSnapshot,
  WsOp,
} from "@/types";

export const H_BY_TYPE: Record<string, { w: number; h: number; minH: number }> = {
  chart:   { w: 12, h: 5, minH: 4 },
  text:    { w: 6,  h: 5, minH: 3 },
  counter: { w: 6,  h: 5, minH: 3 },
  news:    { w: 6,  h: 4, minH: 2 },
  search:  { w: 6,  h: 5, minH: 3 },
};

/** Pack a theme's windows into a gap-free grid. Returns a fresh layout array. */
export function packTheme(wins: Window[]): GridLayoutItem[] {
  const layout: GridLayoutItem[] = [];
  if (wins.length === 0) return layout;
  if (wins.length === 1) {
    const w = wins[0];
    layout.push({ i: w.window_id, x: 0, y: 0, w: 12, h: w.window_type === "chart" ? 6 : 5, minW: 3, minH: 3 });
    return layout;
  }
  // 2+ windows: chart (if any) goes full-width on top; the rest pair up in rows of 2 (w=6 each).
  const chartIdx = wins.findIndex(w => w.window_type === "chart");
  let cy = 0;
  if (chartIdx >= 0) {
    const c = wins[chartIdx];
    layout.push({ i: c.window_id, x: 0, y: cy, w: 12, h: 6, minW: 3, minH: 4 });
    cy += 6;
  }
  const others = wins.filter((_, i) => i !== chartIdx);
  others.forEach((w, i) => {
    const isLastOdd = i === others.length - 1 && others.length % 2 === 1;
    const col = i % 2;
    const row = Math.floor(i / 2);
    const rowH = w.window_type === "news" ? 4 : 5;
    layout.push({
      i: w.window_id,
      x: isLastOdd ? 0 : col * 6,
      y: cy + row * 5,
      w: isLastOdd ? 12 : 6,
      h: rowH,
      minW: 3,
      minH: 3,
    });
  });
  return layout;
}

export interface CanvasState {
  themes: Record<string, Theme>;
  windowIndex: Record<string, Window>;
  ticker: DerivedNewsEvent[];
  virtualNow: string;
  lastSeq: number;
  intentRecommendation: { text: string; thesis_key: string } | null;
  pendingIntentId: string | null;
  reasoning: { stage: string; message: string; updated_at: number } | null;
}

export interface CanvasStore extends CanvasState {
  applyOp: (frame: WsOp) => void;
  loadCanvasState: (snapshot: CanvasSnapshot) => void;
  clearCanvas: (reason: "new_intent" | "restore") => void;
  expandWindow: (window_id: string) => void;
  setThemeLayout: (theme_id: string, layout: GridLayoutItem[]) => void;
  dismissTickerItem: (news_id: string) => void;
  dismissWindow: (window_id: string) => void;
  setPendingIntent: (intent_id: string | null) => void;
  spawnLocalWindow: (spec: ManualChartSpec) => string;
  killSwitch: () => Promise<void>;
}

export interface ManualChartSpec {
  window_type: "chart";
  curve_keys: string[];
  chart_type: "line" | "area";
  y_unit: string;
  t_from: string;
  t_to: string;
  title: string;
}

const initialState: CanvasState = {
  themes: {},
  windowIndex: {},
  ticker: [],
  virtualNow: "2026-03-06T00:00:00+00:00",
  lastSeq: 0,
  intentRecommendation: null,
  pendingIntentId: null,
  reasoning: null,
};

export function applyOpReducer(state: CanvasState, frame: WsOp): CanvasState {
  const next: CanvasState = { ...state, lastSeq: Math.max(state.lastSeq, frame.seq) };
  switch (frame.op) {
    case "clear_canvas": {
      return { ...next, themes: {}, windowIndex: {}, intentRecommendation: null, reasoning: null };
    }
    case "spawn_theme": {
      const p = frame.payload;
      return {
        ...next,
        themes: {
          ...next.themes,
          [p.theme_id]: {
            theme_id: p.theme_id,
            label: p.label,
            thesis_key: p.thesis_key,
            window_order: p.window_order,
            layout: [],
          },
        },
      };
    }
    case "spawn_window": {
      const win = frame.payload as Window & { intent_id: string };
      const { intent_id: _ignore, ...windowFields } = win as any;
      const newWindowIndex = { ...next.windowIndex, [win.window_id]: windowFields as Window };
      let theme = next.themes[win.theme_id];
      let themes = next.themes;
      if (!theme) {
        // Orphan window — auto-stub a minimal theme so the card renders.
        theme = {
          theme_id: win.theme_id,
          label: "Working canvas",
          thesis_key: null,
          window_order: [],
          layout: [],
        };
        themes = { ...themes, [win.theme_id]: theme };
      }
      const ids = [...theme.window_order];
      if (!ids.includes(win.window_id)) ids.push(win.window_id);
      const wins = ids.map(id => newWindowIndex[id]).filter(Boolean);
      const layout: GridLayoutItem[] = packTheme(wins);
      return {
        ...next,
        windowIndex: newWindowIndex,
        themes: {
          ...themes,
          [win.theme_id]: { ...theme, layout, window_order: ids },
        },
      };
    }
    case "update_window": {
      const { window_id, patch } = frame.payload;
      const existing = next.windowIndex[window_id];
      if (!existing) return next;
      const merged: Window = { ...existing, spec: { ...existing.spec, ...(patch as any) } } as Window;
      return { ...next, windowIndex: { ...next.windowIndex, [window_id]: merged } };
    }
    case "intent_recommendation": {
      return {
        ...next,
        intentRecommendation: {
          text: frame.payload.text,
          thesis_key: frame.payload.action.thesis_key,
        },
      };
    }
    case "done": {
      return { ...next, pendingIntentId: null };
    }
    case "clock_tick": {
      return { ...next, virtualNow: frame.payload.virtual_now };
    }
    case "news_event": {
      const ev = frame.payload.event;
      const tickerNext = [ev, ...next.ticker.filter((x) => x.news_id !== ev.news_id)].slice(0, 20);
      return { ...next, ticker: tickerNext };
    }
    case "restore_canvas": {
      const snap = frame.payload.canvas_snapshot;
      const themes: Record<string, Theme> = {};
      const windowIndex: Record<string, Window> = {};
      for (const w of snap.windows) {
        windowIndex[w.window_id] = w as Window;
        const tId = w.theme_id;
        themes[tId] = themes[tId] || { theme_id: tId, label: "Restored", thesis_key: null, window_order: [], layout: [] };
        themes[tId].window_order.push(w.window_id);
      }
      return { ...next, themes, windowIndex, virtualNow: snap.virtual_now };
    }
    case "tool_call": {
      return {
        ...next,
        reasoning: {
          stage: frame.payload.stage,
          message: frame.payload.message,
          updated_at: Date.now(),
        },
      };
    }
    case "remove_window": {
      const { window_id } = frame.payload as { window_id: string };
      const w = next.windowIndex[window_id];
      if (!w) return next;
      const { [window_id]: _drop, ...restIdx } = next.windowIndex;
      const theme = next.themes[w.theme_id];
      const themes = theme
        ? {
            ...next.themes,
            [w.theme_id]: {
              ...theme,
              layout: theme.layout.filter((item) => item.i !== window_id),
              window_order: theme.window_order.filter((id) => id !== window_id),
            },
          }
        : next.themes;
      return { ...next, windowIndex: restIdx, themes };
    }
    case "swap_window": {
      const { old_window_id, new_window } = frame.payload as {
        old_window_id: string;
        new_window: Window & { intent_id?: string };
      };
      const old = next.windowIndex[old_window_id];
      if (!old) return next;
      const { intent_id: _ig, ...newWFields } = new_window as any;
      const newW = newWFields as Window;
      const { [old_window_id]: _drop, ...restIdx } = next.windowIndex;
      const updatedIdx = { ...restIdx, [newW.window_id]: newW };
      const theme = next.themes[old.theme_id];
      if (!theme) {
        return { ...next, windowIndex: updatedIdx };
      }
      const orderIdx = theme.window_order.indexOf(old_window_id);
      const newOrder = [...theme.window_order];
      if (orderIdx >= 0) newOrder.splice(orderIdx, 1, newW.window_id);
      else newOrder.push(newW.window_id);
      // Shape-preserving: if grid dims match, reuse old x/y/w/h; else repack.
      const oldDims = H_BY_TYPE[old.window_type];
      const newDims = H_BY_TYPE[newW.window_type];
      let layout: GridLayoutItem[];
      if (
        oldDims &&
        newDims &&
        oldDims.w === newDims.w &&
        oldDims.h === newDims.h
      ) {
        const oldItem = theme.layout.find((it) => it.i === old_window_id);
        if (oldItem) {
          layout = theme.layout.map((it) =>
            it.i === old_window_id ? { ...it, i: newW.window_id } : it,
          );
        } else {
          const wins = newOrder.map((id) => updatedIdx[id]).filter(Boolean);
          layout = packTheme(wins);
        }
      } else {
        const wins = newOrder.map((id) => updatedIdx[id]).filter(Boolean);
        layout = packTheme(wins);
      }
      return {
        ...next,
        windowIndex: updatedIdx,
        themes: {
          ...next.themes,
          [old.theme_id]: { ...theme, layout, window_order: newOrder },
        },
      };
    }
    case "swap_window_order": {
      const { theme_id, new_order } = frame.payload as { theme_id: string; new_order: string[] };
      const theme = next.themes[theme_id];
      if (!theme) return next;
      const ordered = new_order.filter((id) => !!next.windowIndex[id]);
      const wins = ordered.map((id) => next.windowIndex[id]).filter(Boolean);
      return {
        ...next,
        themes: {
          ...next.themes,
          [theme_id]: { ...theme, window_order: ordered, layout: packTheme(wins) },
        },
      };
    }
    case "error":
    default:
      return next;
  }
}

export const useCanvasStore = create<CanvasStore>()((set, get) => ({
  ...initialState,
  applyOp: (frame) => set((s) => applyOpReducer(s, frame)),
  loadCanvasState: (snapshot) =>
    set((s) =>
      applyOpReducer(s, {
        op: "restore_canvas",
        seq: s.lastSeq + 1,
        ts: new Date().toISOString(),
        payload: { canvas_snapshot: snapshot },
      } as WsOp),
    ),
  clearCanvas: (reason) =>
    set((s) =>
      applyOpReducer(s, {
        op: "clear_canvas",
        seq: s.lastSeq + 1,
        ts: new Date().toISOString(),
        payload: { reason },
      } as WsOp),
    ),
  expandWindow: (window_id) =>
    set((s) => {
      const w = s.windowIndex[window_id];
      if (!w) return s;
      const newState: "small" | "big" = w.state === "big" ? "small" : "big";
      return { ...s, windowIndex: { ...s.windowIndex, [window_id]: { ...w, state: newState } as Window } };
    }),
  setThemeLayout: (theme_id, layout) =>
    set((s) => {
      const t = s.themes[theme_id];
      if (!t) return s;
      const prev = t.layout;
      if (
        prev.length === layout.length &&
        prev.every(
          (p, i) =>
            p.i === layout[i].i &&
            p.x === layout[i].x &&
            p.y === layout[i].y &&
            p.w === layout[i].w &&
            p.h === layout[i].h,
        )
      ) {
        return s;
      }
      return { ...s, themes: { ...s.themes, [theme_id]: { ...t, layout } } };
    }),
  dismissTickerItem: (news_id) =>
    set((s) => ({ ...s, ticker: s.ticker.filter((x) => x.news_id !== news_id) })),
  dismissWindow: (window_id) =>
    set((s) => {
      const w = s.windowIndex[window_id];
      if (!w) return s;
      const { [window_id]: _drop, ...rest } = s.windowIndex;
      const theme = s.themes[w.theme_id];
      const themes = theme
        ? {
            ...s.themes,
            [w.theme_id]: {
              ...theme,
              layout: theme.layout.filter((item) => item.i !== window_id),
              window_order: theme.window_order.filter((id) => id !== window_id),
            },
          }
        : s.themes;
      return { ...s, windowIndex: rest, themes };
    }),
  setPendingIntent: (intent_id) => set({ pendingIntentId: intent_id }),
  killSwitch: async () => {
    // Optimistic local reset so the UI snaps back instantly even if the
    // backend hiccups. Backend response then re-syncs via WS clear_canvas.
    set({
      themes: {},
      windowIndex: {},
      ticker: [],
      lastSeq: 0,
      intentRecommendation: null,
      pendingIntentId: null,
      reasoning: null,
    });
    try {
      const { killSwitch } = await import("@/lib/api");
      await killSwitch();
    } catch (err) {
      console.warn("killSwitch backend call failed", err);
    }
  },
  spawnLocalWindow: (spec) => {
    const state = get();
    const id = `win_manual_${Date.now().toString(36)}`;
    const dims = H_BY_TYPE[spec.window_type] ?? { w: 8, h: 6, minH: 4 };

    // Find or create "Manual charts" theme (themes is a Record<string, Theme>)
    const existingTheme = state.themes["theme_manual"];
    const manualTheme: Theme = existingTheme
      ? {
          ...existingTheme,
          layout: [...existingTheme.layout],
          window_order: [...existingTheme.window_order],
        }
      : {
          theme_id: "theme_manual",
          thesis_key: "manual",
          label: "Manual charts",
          layout: [],
          window_order: [],
        };

    const order = manualTheme.window_order.length;
    const layoutItem: GridLayoutItem = {
      i: id,
      x: (order % 2) * dims.w,
      y: Math.floor(order / 2) * dims.h,
      w: dims.w,
      h: dims.h,
      minW: 3,
      minH: dims.minH,
    };
    manualTheme.layout.push(layoutItem);
    manualTheme.window_order.push(id);

    const win: Window = {
      window_id: id,
      theme_id: "theme_manual",
      window_type: "chart",
      title: spec.title,
      summary_line: `${spec.curve_keys.length} curve${spec.curve_keys.length === 1 ? "" : "s"} · ${spec.chart_type}`,
      state: "big",
      curve_keys: spec.curve_keys,
      spec: {
        chart_type: spec.chart_type,
        x_key: "ts",
        y_key: "value",
        y_unit: spec.y_unit,
        t_from: spec.t_from,
        t_to: spec.t_to,
        annotations: [],
      },
      grounding: null,
      raw_toggle: true,
    };

    set({
      themes: { ...state.themes, theme_manual: manualTheme },
      windowIndex: { ...state.windowIndex, [id]: win },
    });
    return id;
  },
}));
