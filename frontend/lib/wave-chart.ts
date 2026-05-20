// 9-color Tone-70 Wave dataviz palette
export const WAVE_CHART_COLORS = [
  "#1e957f", // Teal70 — primary
  "#9d46f0", // Purple70
  "#f0218b", // Pink70
  "#3875f6", // Blue70
  "#725cff", // Lazuli70
  "#559517", // Lime70
  "#f5893e", // Orange70 (NOT the Volue logo orange — Tone-70 only)
  "#b3c83c", // Pear70
  "#a8733f", // Brown70
] as const;

export const WAVE_CHART_AXES = {
  stroke: "var(--chart-axis, #c4d0cd)",
  gridStroke: "var(--chart-grid, #e2ebe9)",
  tick: { fill: "var(--chart-tick, #5d7570)", fontSize: 12 },
};

export function xAxisInterval(dataLength: number, targetTicks: number = 6): number {
  if (dataLength <= targetTicks) return 0;
  return Math.max(0, Math.floor(dataLength / targetTicks) - 1);
}
