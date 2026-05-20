const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface IntentResponse { intent_id: string; status: string; ws_channel: string; }
export interface TickResponse { virtual_now: string; fired_news_ids: string[]; }
export interface CurveRawResponse { curve_key: string; unit: string; area: string; virtual_now: string; rows: Array<{ ts: string; value: number }>; row_count: number; }
export interface CurveIndexEntry {
  curve_key: string;
  type: string;
  area: string;
  unit: string;
  frequency?: string;
  source_curve?: string;
}
export interface CurveIndexResponse {
  demo_day: string;
  cache_window: [string, string];
  curves: CurveIndexEntry[];
}
export async function fetchCurveIndex(): Promise<CurveIndexResponse> {
  const r = await fetch(`${API_BASE}/curves/index`);
  if (!r.ok) throw new Error(`/curves/index ${r.status}`);
  return r.json();
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${path}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const submitIntent = (body: {
  text?: string;
  news_id?: string;
  canvas_state?: object;
  mode?: "create" | "edit" | "explain";
}) => postJSON<IntentResponse>("/intent", body);

export const tick = (steps: number) => postJSON<TickResponse>("/tick", { steps });

export const saveTemplate = (name: string, canvas_snapshot: object) =>
  postJSON<{ ok: boolean; name: string }>("/template/save", { name, canvas_snapshot });

export const restoreTemplate = (name: string) =>
  postJSON<{ schema_version: number; template_name: string; canvas_snapshot: any }>("/template/restore", { name });

export const fetchCurveRaw = async (
  curve_key: string,
  t_from?: string,
  t_to?: string,
): Promise<CurveRawResponse> => {
  const qs = new URLSearchParams({ curve_key });
  if (t_from) qs.set("t_from", t_from);
  if (t_to) qs.set("t_to", t_to);
  const r = await fetch(`${API_BASE}/curve/raw?${qs.toString()}`);
  if (!r.ok) throw new Error(`${r.status} /curve/raw: ${await r.text()}`);
  return r.json();
};

export const resetNewsCooldowns = () => postJSON<{ reset: boolean }>("/admin/reset_news_cooldowns", {});

export const killSwitch = () =>
  postJSON<{ ok: boolean; cancelled_tasks: number; virtual_now: string }>("/admin/kill_switch", {});

export interface SearchEnrichRequest {
  window_id?: string;
  intent_id?: string;
  theme_id?: string;
  context: {
    window_type: string;
    title: string;
    summary_line: string;
    curve_keys: string[];
    virtual_now: string;
    user_text?: string;
    recent_values?: Array<{ ts: string; value: number; curve_key: string }>;
  };
}

export const enrichSearch = (body: SearchEnrichRequest) =>
  postJSON<{ search_id: string; status: string }>("/search/enrich", body);

export const wsUrl = (since: number, clientId?: string) => {
  const base = API_BASE.replace(/^http/, "ws");
  const params = new URLSearchParams({ since: String(since) });
  if (clientId) params.set("client_id", clientId);
  return `${base}/ws?${params.toString()}`;
};
