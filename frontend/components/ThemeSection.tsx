"use client";

import { useEffect, useMemo, useState } from "react";
import { Responsive, WidthProvider, type Layout } from "react-grid-layout";
import { useCanvasStore, H_BY_TYPE } from "@/lib/store";
import { WindowManager } from "./WindowManager";

const ResponsiveGridLayout = WidthProvider(Responsive);

export function ThemeSection({ themeId }: { themeId: string }) {
  const theme = useCanvasStore((s) => s.themes[themeId]);
  const windowIndex = useCanvasStore((s) => s.windowIndex);
  const setThemeLayout = useCanvasStore((s) => s.setThemeLayout);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const windows = useMemo(() => {
    if (!theme) return [];
    return theme.window_order.map((id) => windowIndex[id]).filter((w) => w != null);
  }, [theme, windowIndex]);

  // Stabilize layout prop ref; only changes when array shape changes
  const layoutMemo = useMemo<Layout[]>(() => {
    if (!theme) return [];
    return theme.layout.map((it) => ({ ...it }));
  }, [theme?.layout]);

  if (!theme) return null;

  // SSR placeholder (RGL needs window width)
  if (!mounted) {
    return (
      <section className="theme-section">
        <header className="theme-section__header">
          <h2 className="theme-section__title">{theme.label}</h2>
          {theme.thesis_key && <span className="theme-section__kicker">{theme.thesis_key}</span>}
        </header>
        <div className="theme-section__grid" style={{ minHeight: 400 }} />
      </section>
    );
  }

  return (
    <section className="theme-section">
      <header className="theme-section__header">
        <h2 className="theme-section__title">{theme.label}</h2>
        {theme.thesis_key && <span className="theme-section__kicker">{theme.thesis_key}</span>}
      </header>
      <ResponsiveGridLayout
        className="theme-section__grid"
        layouts={{ lg: layoutMemo, md: layoutMemo, sm: layoutMemo }}
        breakpoints={{ lg: 1200, md: 996, sm: 768 }}
        cols={{ lg: 12, md: 10, sm: 6 }}
        rowHeight={80}
        margin={[16, 16]}
        containerPadding={[0, 0]}
        draggableHandle=".window-card__header"
        draggableCancel=".window-card__dismiss, .window-card__search-btn, .window-card__chevron-btn, .window-card__action"
        compactType="vertical"
        onDragStop={(layout) => setThemeLayout(themeId, layout as any)}
        onResizeStop={(layout) => setThemeLayout(themeId, layout as any)}
        useCSSTransforms={true}
        measureBeforeMount={false}
      >
        {windows.map((w, i) => {
          const found = layoutMemo.find((l) => l.i === w.window_id);
          const dims = H_BY_TYPE[w.window_type] ?? { w: 6, h: 4, minH: 3 };
          const dg = found ?? { i: w.window_id, x: (i % 2) * 6, y: Math.floor(i / 2) * 4, w: dims.w, h: dims.h, minW: 3, minH: dims.minH };
          return (
            <div key={w.window_id} className="window-spawn" data-grid={dg}>
              <WindowManager windowId={w.window_id} />
            </div>
          );
        })}
      </ResponsiveGridLayout>
    </section>
  );
}
