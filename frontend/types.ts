// Mirror of backend/models.py — single source of truth for frontend types.

export interface SourcedValue {
  label: string;
  value: number;
  unit: string;
  source_curve: string;
  ts: string; // ISO-8601 UTC
}

export interface Annotation {
  ts: string;
  label: string;
  color?: string | null;
}

export interface Claim {
  claim: string;
  value: number;
  unit: string;
  source_curve: string;
  ts: string;
}

export type ChartType = "line" | "bar" | "area";

export interface ChartSpec {
  chart_type: ChartType;
  x_key: "ts";
  y_key: "value";
  y_unit: string;
  t_from: string;
  t_to: string;
  annotations: Annotation[];
  extra?: { highlight_negative?: boolean; [k: string]: unknown };
}

export type Badge = "context_not_proof" | "counter_evidence" | null;

export interface TextSpec {
  body: string;
  badge: Badge;
  dismissable: boolean;
  sources: SourcedValue[];
}

export interface NewsSpec {
  headline: string;
  body: string;
  badge: "context_not_proof";
  news_id: string;
  severity: "low" | "med" | "high";
}

export interface CounterSpec {
  body: string;
  badge: "counter_evidence";
  dismissable: boolean;
  points: Claim[];
}

export interface SearchCitation {
  url: string;
  title: string;
  accessed_at: string;
  snippet?: string;
}

export interface SearchSpec {
  body: string;
  query: string;
  badge: "web_search";
  dismissable: boolean;
  hedged: boolean;
  citations: SearchCitation[];
  related_curve_keys: string[];
  related_window_id?: string;
}

export type WindowType = "chart" | "text" | "news" | "counter" | "search";

export interface BaseWindow {
  window_id: string;
  theme_id: string;
  title: string;
  summary_line: string;
  state: "small" | "big";
  curve_keys: string[];
  grounding: SourcedValue | null;
  raw_toggle: boolean;
}

export type Window =
  | (BaseWindow & { window_type: "chart"; spec: ChartSpec })
  | (BaseWindow & { window_type: "text"; spec: TextSpec })
  | (BaseWindow & { window_type: "news"; spec: NewsSpec })
  | (BaseWindow & { window_type: "counter"; spec: CounterSpec })
  | (BaseWindow & { window_type: "search"; spec: SearchSpec });

export interface Theme {
  theme_id: string;
  label: string;
  thesis_key: string | null;
  window_order: string[];
  layout: GridLayoutItem[];
}

export interface GridLayoutItem {
  i: string; // window_id
  x: number;
  y: number;
  w: number;
  h: number;
  minW?: number;
  minH?: number;
}

export interface FundamentalBreakdown {
  area: string;
  focus: string;
  headline: string;
  drivers: SourcedValue[];
  method_note: string;
  residual_check_ok: boolean;
  t_from: string;
  t_to: string;
}

export interface DerivedNewsEvent {
  news_id: string;
  area: string;
  severity: "low" | "med" | "high";
  headline: string;
  delta_value: number;
  unit: string;
  source_curve: string;
  ts: string;
  hedged: boolean;
  hedged_text: string;
}

export interface CanvasSnapshot {
  windows: Array<Window & { layout?: GridLayoutItem }>;
  themes: string[];
  virtual_now: string;
}

// WS Op discriminated union
export type WsOp =
  | { op: "clear_canvas"; seq: number; ts: string; payload: { reason: "new_intent" | "restore" } }
  | { op: "spawn_theme"; seq: number; ts: string; payload: { theme_id: string; label: string; thesis_key: string | null; window_order: string[]; intent_id: string } }
  | { op: "spawn_window"; seq: number; ts: string; payload: Window & { intent_id: string } }
  | { op: "update_window"; seq: number; ts: string; payload: { window_id: string; patch: Partial<Window["spec"]>; intent_id: string } }
  | { op: "intent_recommendation"; seq: number; ts: string; payload: { text: string; action: { type: string; thesis_key: string }; intent_id: string } }
  | { op: "done"; seq: number; ts: string; payload: { intent_id: string; elapsed_ms: number } }
  | { op: "error"; seq: number; ts: string; payload: { code: string; message: string; intent_id: string | null; fatal: boolean } }
  | { op: "clock_tick"; seq: number; ts: string; payload: { virtual_now: string; tick_count: number; fired_news_ids: string[] } }
  | { op: "news_event"; seq: number; ts: string; payload: { event: DerivedNewsEvent } }
  | { op: "restore_canvas"; seq: number; ts: string; payload: { canvas_snapshot: CanvasSnapshot } }
  | { op: "tool_call"; seq: number; ts: string; payload: { stage: string; message: string; intent_id: string } }
  | { op: "remove_window"; seq: number; ts: string; payload: { window_id: string; intent_id: string; reason?: string } }
  | { op: "swap_window"; seq: number; ts: string; payload: { old_window_id: string; new_window: Window & { intent_id?: string }; intent_id: string } }
  | { op: "swap_window_order"; seq: number; ts: string; payload: { theme_id: string; new_order: string[]; intent_id: string } };
