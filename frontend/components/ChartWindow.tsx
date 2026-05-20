"use client";

import { useEffect, useState, useMemo } from "react";
import {
  ComposedChart,
  Line,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
  ReferenceLine,
  Legend,
} from "recharts";
import { Table } from "lucide-react";
import { fetchCurveRaw } from "@/lib/api";
import { WAVE_CHART_COLORS, WAVE_CHART_AXES, xAxisInterval } from "@/lib/wave-chart";
import { downsample } from "@/lib/lttb";
import { formatCET } from "@/lib/tz";
import { RawDataModal } from "./RawDataModal";
import type { Window, ChartSpec } from "@/types";

type ChartWindowProps = { window: Window & { window_type: "chart"; spec: ChartSpec } };

type Row = { ts: string; [curveKey: string]: string | number };

export function ChartWindow({ window: w }: ChartWindowProps) {
  const spec = w.spec;
  const curveKeys = w.curve_keys;
  const [series, setSeries] = useState<Record<string, Array<{ ts: string; value: number }>>>({});
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [rawOpenKey, setRawOpenKey] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const out: Record<string, Array<{ ts: string; value: number }>> = {};
        await Promise.all(
          curveKeys.map(async (key) => {
            try {
              const r = await fetchCurveRaw(key, spec.t_from, spec.t_to);
              out[key] = r.rows.length > 800 ? downsample(r.rows, 400) : r.rows;
            } catch (err) {
              console.warn(`fetchCurveRaw(${key}) failed`, err);
              out[key] = [];
            }
          }),
        );
        if (!cancelled) {
          setSeries(out);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [curveKeys.join(","), spec.t_from, spec.t_to]);

  const merged: Row[] = useMemo(() => {
    const tsSet = new Set<string>();
    for (const k of curveKeys) (series[k] || []).forEach((r) => tsSet.add(r.ts));
    const allTs = Array.from(tsSet).sort();
    return allTs.map((ts) => {
      const row: Row = { ts };
      for (const k of curveKeys) {
        const rec = (series[k] || []).find((r) => r.ts === ts);
        if (rec) row[k] = rec.value;
      }
      return row;
    });
  }, [series, curveKeys]);

  const yDomain = useMemo<[number | string, number | string]>(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const k of curveKeys) for (const r of series[k] || []) { if (r.value < min) min = r.value; if (r.value > max) max = r.value; }
    if (min === Infinity || max === -Infinity) return ["auto", "auto"];
    const pad = (max - min) * 0.05;
    return [Number((min - pad).toFixed(2)), Number((max + pad).toFixed(2))];
  }, [series, curveKeys]);

  const showNegArea = spec.extra?.highlight_negative && typeof yDomain[0] === "number" && (yDomain[0] as number) < 0;

  // Multi-day detection: t_from..t_to span > 36h → switch x-axis to "MMM d".
  const rangeDays = useMemo(() => {
    try {
      const from = new Date(spec.t_from).getTime();
      const to = new Date(spec.t_to).getTime();
      return Math.max(1, Math.round((to - from) / (24 * 3600 * 1000)));
    } catch {
      return 1;
    }
  }, [spec.t_from, spec.t_to]);
  const multiDay = rangeDays > 1;

  const ChartTag: any = spec.chart_type === "area" ? Area : spec.chart_type === "bar" ? Bar : Line;

  if (error) {
    return <div style={{ color: "var(--color-foreground-danger)", padding: 16 }}>Chart error: {error}</div>;
  }

  return (
    <div style={{ width: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{ width: "100%", height: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={merged} margin={{ top: 8, right: 16, bottom: 24, left: 28 }}>
            <CartesianGrid stroke={WAVE_CHART_AXES.gridStroke as string} strokeDasharray="3 3" />
            <XAxis
              dataKey="ts"
              stroke={WAVE_CHART_AXES.stroke as string}
              tick={WAVE_CHART_AXES.tick as any}
              tickFormatter={(iso) => formatCET(iso, multiDay ? "MMM d" : "HH:mm")}
              interval={xAxisInterval(merged.length, 6)}
              minTickGap={20}
              label={{
                value: multiDay ? `${rangeDays}-day window · CET` : "time · CET",
                position: "insideBottomRight",
                offset: -8,
                style: { fontSize: 11, fill: "var(--ink-500, #5C5C58)", fontWeight: 500 },
              }}
            />
            <YAxis
              stroke={WAVE_CHART_AXES.stroke as string}
              tick={WAVE_CHART_AXES.tick as any}
              domain={yDomain}
              tickFormatter={(v) => (typeof v === "number" ? v.toFixed(1) : String(v))}
              width={64}
              label={{
                value: spec.y_unit || "value",
                angle: -90,
                position: "insideLeft",
                offset: 4,
                style: { fontSize: 11, fill: "var(--ink-500, #5C5C58)", fontWeight: 500, textAnchor: "middle" },
              }}
            />
            <Tooltip
              labelFormatter={(iso) => formatCET(String(iso), multiDay ? "MMM d HH:mm" : "EEE HH:mm")}
              formatter={(value: any) => (typeof value === "number" ? value.toFixed(2) : value)}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} iconType="line" />
            {showNegArea && (
              <ReferenceArea
                y1={yDomain[0] as number}
                y2={0}
                fill="var(--color-background-danger-subtle, #ffe8e0)"
                fillOpacity={0.5}
                ifOverflow="visible"
              />
            )}
            <ReferenceLine y={0} stroke="var(--chart-refline, #a2b2af)" strokeDasharray="2 2" />
            {spec.annotations?.map((ann, i) => (
              <ReferenceLine
                key={`ann-${i}`}
                x={ann.ts}
                stroke={ann.color || "var(--chart-refline, #a2b2af)"}
                label={{ value: ann.label, fontSize: 11, fill: "var(--text-muted)" }}
              />
            ))}
            {curveKeys.map((k, i) => (
              <ChartTag
                key={k}
                type="monotone"
                dataKey={k}
                stroke={WAVE_CHART_COLORS[i % WAVE_CHART_COLORS.length]}
                fill={spec.chart_type === "area" ? WAVE_CHART_COLORS[i % WAVE_CHART_COLORS.length] : undefined}
                fillOpacity={spec.chart_type === "area" ? 0.18 : undefined}
                dot={false}
                isAnimationActive={false}
                strokeWidth={2}
                connectNulls
                name={k}
              />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 2px 0", fontSize: 11, color: "var(--ink-500, #5C5C58)", fontFamily: "var(--font-plex-mono, ui-monospace, monospace)" }}>
        <span>
          {loading ? "loading…" : `${merged.length} pts · ${curveKeys.length} curve${curveKeys.length === 1 ? "" : "s"} · ${spec.y_unit}`}
        </span>
        {curveKeys.length > 0 && (
          <button
            type="button"
            className="btn btn--outline btn--sm"
            onClick={() => setRawOpenKey(curveKeys[0])}
            aria-label="View source data"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px" }}
          >
            <Table size={12} strokeWidth={2.4} />
            <span>Source data</span>
          </button>
        )}
      </div>
      {rawOpenKey && (
        <RawDataModal curveKey={rawOpenKey} tFrom={spec.t_from} tTo={spec.t_to} onClose={() => setRawOpenKey(null)} />
      )}
    </div>
  );
}
