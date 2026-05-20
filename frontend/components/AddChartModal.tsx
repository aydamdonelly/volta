"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { X, Plus, AlertTriangle } from "lucide-react";
import { fetchCurveIndex, type CurveIndexEntry, type CurveIndexResponse } from "@/lib/api";
import { useCanvasStore } from "@/lib/store";

type PresetKey = "today" | "yesterday" | "last7" | "demo_week" | "full" | "custom";
type GroupKey = "spot" | "generation" | "consumption" | "forecast" | "imbalance" | "fuels" | "other";

const GROUP_LABELS: Record<GroupKey, string> = {
  spot: "Spot prices",
  generation: "Generation",
  consumption: "Consumption / Load",
  forecast: "Forecasts",
  imbalance: "Optimeering imbalance",
  fuels: "Fuels & carbon",
  other: "Other",
};

const GROUP_ORDER: GroupKey[] = ["spot", "generation", "consumption", "forecast", "imbalance", "fuels", "other"];

function classify(curve: CurveIndexEntry): GroupKey {
  const k = curve.curve_key;
  if (k.startsWith("optimeering_")) return "imbalance";
  if (k.endsWith("_f") || k.includes("_ec00_f")) return "forecast";
  if (k.startsWith("pri_")) return "spot";
  if (k.startsWith("pro_")) return "generation";
  if (k.startsWith("con_") || k.startsWith("rdl_")) return "consumption";
  if (k.startsWith("co2_") || k.startsWith("gas_")) return "fuels";
  return "other";
}

const PRESETS: { key: PresetKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last7", label: "Last 7 days" },
  { key: "demo_week", label: "Demo week (Mar 1–6)" },
  { key: "full", label: "Full cache" },
  { key: "custom", label: "Custom" },
];

function toIso(d: Date): string {
  return d.toISOString();
}

function startOfUtcDay(d: Date): Date {
  const x = new Date(d);
  x.setUTCHours(0, 0, 0, 0);
  return x;
}

function presetRange(
  preset: PresetKey,
  cacheWindow: [string, string],
  virtualNowIso: string,
): { t_from: string; t_to: string } {
  const now = new Date(virtualNowIso);
  const [cacheFromStr, cacheToStr] = cacheWindow;
  const cacheFrom = new Date(`${cacheFromStr}T00:00:00Z`);
  const cacheTo = new Date(`${cacheToStr}T23:59:59Z`);

  switch (preset) {
    case "today": {
      const from = startOfUtcDay(now);
      const to = new Date(from);
      to.setUTCDate(to.getUTCDate() + 1);
      return { t_from: toIso(from), t_to: toIso(to) };
    }
    case "yesterday": {
      const to = startOfUtcDay(now);
      const from = new Date(to);
      from.setUTCDate(from.getUTCDate() - 1);
      return { t_from: toIso(from), t_to: toIso(to) };
    }
    case "last7": {
      const to = now;
      const from = new Date(to);
      from.setUTCDate(from.getUTCDate() - 7);
      return { t_from: toIso(from), t_to: toIso(to) };
    }
    case "demo_week": {
      return {
        t_from: toIso(new Date("2026-03-01T00:00:00Z")),
        t_to: toIso(new Date("2026-03-06T23:59:59Z")),
      };
    }
    case "full":
    case "custom":
    default:
      return { t_from: toIso(cacheFrom), t_to: toIso(cacheTo) };
  }
}

function isoToLocalInput(iso: string): string {
  // Convert UTC ISO into a value usable by <input type="datetime-local">
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function localInputToIso(local: string): string {
  // local has no tz — interpret as local time, convert to ISO UTC.
  if (!local) return "";
  const d = new Date(local);
  return d.toISOString();
}

type Props = { open: boolean; onClose: () => void };

export default function AddChartModal({ open, onClose }: Props) {
  const [index, setIndex] = useState<CurveIndexResponse | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preset, setPreset] = useState<PresetKey>("demo_week");
  const [chartType, setChartType] = useState<"line" | "area">("line");
  const [customFrom, setCustomFrom] = useState<string>("");
  const [customTo, setCustomTo] = useState<string>("");
  const [title, setTitle] = useState<string>("");
  const [titleDirty, setTitleDirty] = useState(false);

  const virtualNow = useCanvasStore((s) => s.virtualNow);
  const spawnLocalWindow = useCanvasStore((s) => s.spawnLocalWindow);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const firstFocusRef = useRef<HTMLButtonElement | null>(null);

  // Reset state each time modal opens
  useEffect(() => {
    if (!open) return;
    setSelected(new Set());
    setPreset("demo_week");
    setChartType("line");
    setCustomFrom("");
    setCustomTo("");
    setTitle("");
    setTitleDirty(false);
    setLoadErr(null);
  }, [open]);

  // Fetch curve index on open
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setIndex(null);
    fetchCurveIndex()
      .then((r) => {
        if (!cancelled) {
          setIndex(r);
          // initialise custom range to cache window
          setCustomFrom(isoToLocalInput(`${r.cache_window[0]}T00:00:00Z`));
          setCustomTo(isoToLocalInput(`${r.cache_window[1]}T23:59:59Z`));
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadErr(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // ESC + focus trap
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        const list = Array.from(focusables).filter((el) => !el.hasAttribute("disabled"));
        if (list.length === 0) return;
        const first = list[0];
        const last = list[list.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    // Focus close button when opened
    requestAnimationFrame(() => firstFocusRef.current?.focus());
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const grouped = useMemo(() => {
    const out: Record<GroupKey, CurveIndexEntry[]> = {
      spot: [],
      generation: [],
      consumption: [],
      forecast: [],
      imbalance: [],
      fuels: [],
      other: [],
    };
    if (!index) return out;
    for (const c of index.curves) {
      out[classify(c)].push(c);
    }
    // sort each group alphabetically
    for (const k of Object.keys(out) as GroupKey[]) {
      out[k].sort((a, b) => a.curve_key.localeCompare(b.curve_key));
    }
    return out;
  }, [index]);

  const selectedEntries = useMemo(() => {
    if (!index) return [];
    return index.curves.filter((c) => selected.has(c.curve_key));
  }, [index, selected]);

  const range = useMemo(() => {
    if (!index) return null;
    if (preset === "custom") {
      const fromIso = customFrom ? localInputToIso(customFrom) : "";
      const toIso = customTo ? localInputToIso(customTo) : "";
      return { t_from: fromIso, t_to: toIso };
    }
    return presetRange(preset, index.cache_window, virtualNow);
  }, [index, preset, customFrom, customTo, virtualNow]);

  // Auto-title (only if user hasn't edited it)
  useEffect(() => {
    if (titleDirty) return;
    const label = PRESETS.find((p) => p.key === preset)?.label ?? "";
    const n = selectedEntries.length;
    const next = n === 0 ? "" : `${n} curve${n === 1 ? "" : "s"} · ${label}`;
    setTitle(next);
  }, [selectedEntries, preset, titleDirty]);

  // Warnings
  const warnings: string[] = [];
  if (selectedEntries.length > 0) {
    const units = new Set(selectedEntries.map((c) => c.unit ?? ""));
    if (units.size > 1) warnings.push("Selected curves have different units — y-axis will use the first unit.");
    const hasOpti = selectedEntries.some((c) => c.curve_key.startsWith("optimeering_"));
    const hasNon = selectedEntries.some((c) => !c.curve_key.startsWith("optimeering_"));
    if (hasOpti && hasNon) {
      warnings.push("Mixing Optimeering predictions with other curves is not recommended.");
    }
  }

  const yUnit = selectedEntries[0]?.unit ?? "";
  const canSpawn =
    selectedEntries.length > 0 &&
    !!range &&
    !!range.t_from &&
    !!range.t_to &&
    title.trim().length > 0;

  function toggleCurve(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function handleSpawn() {
    if (!canSpawn || !range) return;
    spawnLocalWindow({
      window_type: "chart",
      curve_keys: selectedEntries.map((c) => c.curve_key),
      chart_type: chartType,
      y_unit: yUnit,
      t_from: range.t_from,
      t_to: range.t_to,
      title: title.trim(),
    });
    onClose();
  }

  if (!open) return null;

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal add-chart-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="addchart-title"
        ref={dialogRef}
      >
        <div className="modal__header">
          <h3 id="addchart-title" className="modal__title">Add chart</h3>
          <button
            ref={firstFocusRef}
            className="modal__close"
            onClick={onClose}
            aria-label="Close"
            type="button"
          >
            <X size={18} strokeWidth={2} />
          </button>
        </div>

        {loadErr && (
          <p style={{ color: "var(--color-foreground-danger)" }}>{loadErr}</p>
        )}
        {!index && !loadErr && <p>Loading curves…</p>}

        {index && (
          <div className="add-chart-modal__body">
            <div className="add-chart-modal__picker" aria-label="Curve picker">
              {GROUP_ORDER.map((g) => {
                const items = grouped[g];
                if (!items.length) return null;
                return (
                  <section key={g} className="add-chart-modal__group">
                    <h4 className="add-chart-modal__group-title">{GROUP_LABELS[g]}</h4>
                    <ul className="add-chart-modal__list">
                      {items.map((c) => {
                        const checked = selected.has(c.curve_key);
                        return (
                          <li key={c.curve_key}>
                            <label className="add-chart-modal__row">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleCurve(c.curve_key)}
                              />
                              <span className="add-chart-modal__row-key">{c.curve_key}</span>
                              <span className="add-chart-modal__row-meta">
                                {c.area}
                                {c.unit ? ` · ${c.unit}` : ""}
                              </span>
                            </label>
                          </li>
                        );
                      })}
                    </ul>
                  </section>
                );
              })}
            </div>

            <div className="add-chart-modal__settings" aria-label="Chart settings">
              <fieldset className="add-chart-modal__field">
                <legend>Time range</legend>
                <div className="add-chart-modal__presets">
                  {PRESETS.map((p) => (
                    <label key={p.key} className="add-chart-modal__radio">
                      <input
                        type="radio"
                        name="preset"
                        value={p.key}
                        checked={preset === p.key}
                        onChange={() => setPreset(p.key)}
                      />
                      <span>{p.label}</span>
                    </label>
                  ))}
                </div>
                {preset === "custom" && (
                  <div className="add-chart-modal__custom">
                    <label>
                      <span>From</span>
                      <input
                        type="datetime-local"
                        value={customFrom}
                        onChange={(e) => setCustomFrom(e.target.value)}
                      />
                    </label>
                    <label>
                      <span>To</span>
                      <input
                        type="datetime-local"
                        value={customTo}
                        onChange={(e) => setCustomTo(e.target.value)}
                      />
                    </label>
                  </div>
                )}
              </fieldset>

              <fieldset className="add-chart-modal__field">
                <legend>Chart type</legend>
                <div className="add-chart-modal__radios">
                  <label className="add-chart-modal__radio">
                    <input
                      type="radio"
                      name="chartType"
                      value="line"
                      checked={chartType === "line"}
                      onChange={() => setChartType("line")}
                    />
                    <span>Line</span>
                  </label>
                  <label className="add-chart-modal__radio">
                    <input
                      type="radio"
                      name="chartType"
                      value="area"
                      checked={chartType === "area"}
                      onChange={() => setChartType("area")}
                    />
                    <span>Area</span>
                  </label>
                </div>
              </fieldset>

              <label className="add-chart-modal__field">
                <span className="add-chart-modal__legend">Title</span>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => {
                    setTitle(e.target.value);
                    setTitleDirty(true);
                  }}
                  placeholder="Auto-generated from selection"
                />
              </label>

              {warnings.length > 0 && (
                <div className="add-chart-modal__warnings" role="status">
                  {warnings.map((w, i) => (
                    <p key={i}>
                      <AlertTriangle size={14} strokeWidth={2} />
                      <span>{w}</span>
                    </p>
                  ))}
                </div>
              )}

              <div className="add-chart-modal__summary">
                {selectedEntries.length === 0
                  ? "Pick at least one curve."
                  : `${selectedEntries.length} curve${selectedEntries.length === 1 ? "" : "s"} selected.`}
              </div>

              <div className="add-chart-modal__actions">
                <button type="button" className="btn btn--ghost" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={handleSpawn}
                  disabled={!canSpawn}
                >
                  <Plus size={14} strokeWidth={2.5} style={{ marginRight: 6 }} />
                  Spawn chart
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
