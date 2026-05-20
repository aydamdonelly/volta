"use client";

import Markdown from "markdown-to-jsx";
import { ExternalLink } from "lucide-react";
import type { Window, SearchSpec } from "@/types";

interface Props {
  window: Window & { window_type: "search"; spec: SearchSpec };
}

export function SearchWindow({ window: w }: Props) {
  const { body, citations, query, hedged } = w.spec;
  return (
    <div className="search-window" style={{ padding: "8px 4px" }}>
      {query && (
        <p
          style={{
            fontSize: 11,
            color: "var(--ink-500, #5C5C58)",
            marginBottom: 8,
            fontFamily: "var(--font-plex-mono, ui-monospace, monospace)",
          }}
        >
          query: <code>{query}</code>
        </p>
      )}
      <div className="search-window__body" style={{ fontSize: 14, lineHeight: 1.5 }}>
        <Markdown
          options={{
            overrides: {
              a: {
                props: { target: "_blank", rel: "noreferrer noopener" },
              },
            },
          }}
        >
          {body || "_(searching…)_"}
        </Markdown>
      </div>
      {citations && citations.length > 0 && (
        <div
          style={{
            marginTop: 10,
            display: "flex",
            flexWrap: "wrap",
            gap: 6,
          }}
        >
          {citations.map((c, i) => (
            <a
              key={`${c.url}-${i}`}
              href={c.url}
              target="_blank"
              rel="noreferrer noopener"
              title={c.snippet}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: 11,
                padding: "2px 8px",
                borderRadius: 999,
                background: "var(--color-background-accent-subtle, #eefffc)",
                border: "1px solid var(--color-border-neutral-subtle, #e2ebe9)",
                color: "var(--color-foreground-accent-subtle, #487d74)",
                textDecoration: "none",
                maxWidth: 240,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              <ExternalLink size={10} strokeWidth={2} />
              {c.title || c.url}
            </a>
          ))}
        </div>
      )}
      {hedged && (
        <p
          style={{
            fontSize: 10,
            color: "var(--ink-500, #5C5C58)",
            marginTop: 8,
            fontStyle: "italic",
          }}
        >
          context, not market data — verify via Volue before acting
        </p>
      )}
    </div>
  );
}
