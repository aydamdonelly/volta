"use client";

import { useState } from "react";
import { Check, Clock, AlertOctagon, Sigma } from "lucide-react";

export interface CitationData {
  n: number;
  value?: string;            // e.g. "€125.09"
  source_curve: string;      // e.g. "pri de spot €/mwh cet h a"
  ts?: string;               // ISO-8601 UTC
  unit?: string;             // e.g. "€/MWh"
  status?: "ok" | "stale" | "missing" | "derived";
  formula?: string;          // for derived values
  residual_check_ok?: boolean | null;
  onOpen?: () => void;       // triggered by click — opens RawDataModal
}

const STATUS_ICON = {
  ok: Check,
  stale: Clock,
  missing: AlertOctagon,
  derived: Sigma,
};

function _statusLabel(s: CitationData["status"]) {
  switch (s) {
    case "ok":      return "verified";
    case "stale":   return "cached";
    case "missing": return "missing";
    case "derived": return "derived";
    default:        return "verified";
  }
}

export function CitationChip(props: CitationData) {
  const { n, value, source_curve, ts, status = "ok", formula, residual_check_ok, onOpen } = props;
  const [hovering, setHovering] = useState(false);
  const StatusIcon = STATUS_ICON[status];

  return (
    <span
      className="cite-chip-wrap"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <button
        type="button"
        className="cite-chip"
        data-status={status}
        onClick={onOpen}
        aria-label={`Source ${n}: ${source_curve}`}
      >
        <span className="cite-chip__num">[{n}]</span>
        {value && <span className="cite-chip__val tabular-nums">{value}</span>}
        <StatusIcon size={10} strokeWidth={2.4} className="cite-chip__glyph" aria-hidden />
      </button>
      {hovering && (
        <span className="cite-pop" role="tooltip" aria-live="polite">
          <span className="cite-pop__head">
            <span className="cite-pop__n">[{n}]</span>
            <span className={`cite-pop__badge cite-pop__badge--${status}`}>
              <StatusIcon size={10} strokeWidth={2.4} /> {_statusLabel(status)}
            </span>
          </span>
          {value && (
            <span className="cite-pop__value tabular-nums">
              {value}
              {props.unit && <span className="cite-pop__unit"> {props.unit}</span>}
            </span>
          )}
          <dl className="cite-pop__grid">
            <dt>Curve</dt>
            <dd className="mono">{source_curve}</dd>
            {ts && (
              <>
                <dt>Time (UTC)</dt>
                <dd>{ts.replace("T", " ").slice(0, 16)}</dd>
              </>
            )}
            <dt>Source</dt>
            <dd>Volue Insight cache</dd>
            {formula && (
              <>
                <dt>Formula</dt>
                <dd className="mono">{formula}</dd>
              </>
            )}
            {residual_check_ok != null && (
              <>
                <dt>Reconciled</dt>
                <dd className={residual_check_ok ? "ok" : "warn"}>
                  {residual_check_ok ? "✓ residual = con − spv − wnd" : "! mismatch"}
                </dd>
              </>
            )}
          </dl>
          <span className="cite-pop__hint">click chip to open source data</span>
        </span>
      )}
    </span>
  );
}
