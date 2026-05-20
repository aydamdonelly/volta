"use client";

/** Claude-Code-style tool-call mono line.
 *  Renders as:  ▸ Tool(args)
 *  Or with result: also pass `result` prop for a ↳ result line beneath.
 */
export function ToolCallLine({
  tool,
  args,
  result,
}: {
  tool: string;
  args?: string;
  result?: string;
}) {
  return (
    <div className="tool-call-block">
      <div className="tool-call">
        <span className="tool-call__name">{tool}</span>
        {args !== undefined && (
          <>
            <span className="tool-call__paren">(</span>
            <span className="arg">{args}</span>
            <span className="tool-call__paren">)</span>
          </>
        )}
      </div>
      {result !== undefined && (
        <div className="tool-result">{result}</div>
      )}
      <style jsx>{`
        .tool-call-block { font-family: var(--font-plex-mono, ui-monospace, monospace); }
        .tool-call__name { color: var(--ink-900, #141413); font-weight: 500; }
        .tool-call__paren { color: var(--ink-500, #5C5C58); }
      `}</style>
    </div>
  );
}
