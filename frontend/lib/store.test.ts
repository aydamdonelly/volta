import { describe, it, expect } from "vitest";
import { applyOpReducer } from "./store";
import type { WsOp } from "@/types";

const baseState = {
  themes: {},
  windowIndex: {},
  ticker: [],
  virtualNow: "2026-04-05T00:00:00+00:00",
  lastSeq: 0,
  intentRecommendation: null,
  pendingIntentId: null,
};

const f = (op: any, seq: number, payload: any): WsOp =>
  ({ op, seq, ts: new Date().toISOString(), payload } as WsOp);

describe("applyOpReducer", () => {
  it("clear_canvas resets themes + windows", () => {
    const s = { ...baseState, themes: { x: {} as any }, windowIndex: { w: {} as any } };
    const out = applyOpReducer(s as any, f("clear_canvas", 1, { reason: "new_intent" }));
    expect(out.themes).toEqual({});
    expect(out.windowIndex).toEqual({});
  });

  it("spawn_theme adds theme", () => {
    const out = applyOpReducer(baseState as any, f("spawn_theme", 1, { theme_id: "t1", label: "L", thesis_key: "de_price_crash", window_order: [], intent_id: "i1" }));
    expect(out.themes["t1"].label).toBe("L");
  });

  it("spawn_window adds to windowIndex + layout", () => {
    let s = applyOpReducer(baseState as any, f("spawn_theme", 1, { theme_id: "t1", label: "L", thesis_key: "x", window_order: ["w1"], intent_id: "i1" }));
    s = applyOpReducer(s, f("spawn_window", 2, { window_id: "w1", theme_id: "t1", window_type: "text", title: "T", summary_line: "s", state: "small", curve_keys: [], spec: { body: "", badge: null, dismissable: true, sources: [] }, grounding: null, raw_toggle: true, intent_id: "i1" }));
    expect(s.windowIndex["w1"].title).toBe("T");
    expect(s.themes["t1"].layout.length).toBe(1);
  });

  it("update_window merges spec patch", () => {
    let s: any = applyOpReducer(baseState as any, f("spawn_theme", 1, { theme_id: "t1", label: "L", thesis_key: "x", window_order: ["w1"], intent_id: "i1" }));
    s = applyOpReducer(s, f("spawn_window", 2, { window_id: "w1", theme_id: "t1", window_type: "text", title: "T", summary_line: "s", state: "small", curve_keys: [], spec: { body: "", badge: null, dismissable: true, sources: [] }, grounding: null, raw_toggle: true, intent_id: "i1" }));
    s = applyOpReducer(s, f("update_window", 3, { window_id: "w1", patch: { body: "filled" }, intent_id: "i1" }));
    expect((s.windowIndex["w1"].spec as any).body).toBe("filled");
  });

  it("intent_recommendation sets recommendation", () => {
    const out = applyOpReducer(baseState as any, f("intent_recommendation", 1, { text: "go", action: { type: "apply_layout", thesis_key: "de_price_crash" }, intent_id: "i" }));
    expect(out.intentRecommendation?.thesis_key).toBe("de_price_crash");
  });

  it("done clears pendingIntentId", () => {
    const s = { ...baseState, pendingIntentId: "i1" };
    const out = applyOpReducer(s as any, f("done", 1, { intent_id: "i1", elapsed_ms: 100 }));
    expect(out.pendingIntentId).toBeNull();
  });

  it("clock_tick updates virtualNow", () => {
    const out = applyOpReducer(baseState as any, f("clock_tick", 1, { virtual_now: "2026-04-05T14:00:00+00:00", tick_count: 56, fired_news_ids: [] }));
    expect(out.virtualNow).toBe("2026-04-05T14:00:00+00:00");
  });

  it("news_event prepends + dedupes", () => {
    const ev = { news_id: "n1", area: "DE", severity: "low", headline: "h", delta_value: 1, unit: "MWh", source_curve: "x", ts: "t", hedged: true, hedged_text: "context, not proof" } as any;
    const out = applyOpReducer(baseState as any, f("news_event", 1, { event: ev }));
    expect(out.ticker[0].news_id).toBe("n1");
  });

  it("error op is no-op", () => {
    const out = applyOpReducer(baseState as any, f("error", 1, { code: "X", message: "y", intent_id: null, fatal: false }));
    expect(out.themes).toEqual({});
  });

  it("restore_canvas seeds themes + windows from snapshot", () => {
    const snap = {
      windows: [{ window_id: "w1", theme_id: "t1", window_type: "text", title: "T", summary_line: "", state: "small", curve_keys: [], spec: { body: "x", badge: null, dismissable: true, sources: [] }, grounding: null, raw_toggle: true } as any],
      themes: ["t1"],
      virtual_now: "2026-04-05T10:00:00+00:00",
    };
    const out = applyOpReducer(baseState as any, f("restore_canvas", 1, { canvas_snapshot: snap }));
    expect(out.windowIndex["w1"]).toBeDefined();
    expect(out.themes["t1"]).toBeDefined();
  });
});
