"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { fetchCurveRaw, type CurveRawResponse } from "@/lib/api";
import { formatCET } from "@/lib/tz";

type Props = {
  curveKey: string;
  tFrom?: string;
  tTo?: string;
  onClose: () => void;
};

export function RawDataModal({ curveKey, tFrom, tTo, onClose }: Props) {
  const [data, setData] = useState<CurveRawResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetchCurveRaw(curveKey, tFrom, tTo);
        if (!cancelled) {
          setData(r);
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
  }, [curveKey, tFrom, tTo]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-labelledby="rawmodal-title">
        <div className="modal__header">
          <h3 id="rawmodal-title" className="modal__title">Raw data — {curveKey}</h3>
          <button className="modal__close" onClick={onClose} aria-label="Close">
            <X size={18} strokeWidth={2} />
          </button>
        </div>
        {loading && <p>Loading…</p>}
        {error && <p style={{ color: "var(--color-foreground-danger)" }}>{error}</p>}
        {data && (
          <>
            <p style={{ marginTop: 0, fontSize: "var(--type-zeta)", color: "var(--text-muted)" }}>
              {data.area} · {data.unit} · {data.row_count} rows · virtual_now {formatCET(data.virtual_now, "MMM d HH:mm")}
            </p>
            <table className="data-table">
              <thead>
                <tr><th>Time (CET)</th><th>Value</th><th>Unit</th></tr>
              </thead>
              <tbody>
                {data.rows.slice(0, 200).map((r, i) => (
                  <tr key={i}>
                    <td className="tabular-nums">{formatCET(r.ts, "MMM d HH:mm")}</td>
                    <td className="num">{r.value.toFixed(3)}</td>
                    <td>{data.unit}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.rows.length > 200 && (
              <p style={{ marginTop: 8, fontSize: "var(--type-eta)", color: "var(--text-muted)" }}>
                Showing first 200 of {data.rows.length} rows.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
