import type { CSSProperties } from "react";

/**
 * Token-bound style helpers for Recharts. Pass the return values directly to
 * <Tooltip contentStyle={...}>, <XAxis tick={...}>, and <CartesianGrid {...}>
 * so chart chrome tracks the Ember palette instead of hardcoded slate hex.
 *
 * Design constraint: these MUST return plain style objects (not className
 * strings) because Recharts ignores className on its SVG chrome. CSS variables
 * are valid inside inline styles, so `var(--card)` etc. resolve at render
 * time and respond to `.dark` class flips.
 */

export function rechartsTooltipStyle(): CSSProperties {
  return {
    backgroundColor: "var(--card)",
    border: "1px solid var(--border)",
    borderRadius: "0.5rem",
    color: "var(--foreground)",
    fontSize: "0.8125rem",
    boxShadow: "var(--shadow-md)",
    padding: "0.5rem 0.75rem",
  };
}

export function rechartsTooltipLabelStyle(): CSSProperties {
  return {
    color: "var(--muted-foreground)",
    fontWeight: 600,
    fontSize: "0.75rem",
    marginBottom: "0.25rem",
  };
}

export function rechartsTooltipItemStyle(): CSSProperties {
  return {
    color: "var(--foreground)",
  };
}

export function rechartsAxisTickStyle(): { fill: string; fontSize: number } {
  return {
    fill: "var(--muted-foreground)",
    fontSize: 11,
  };
}

export function rechartsGridStyle(): { stroke: string; strokeOpacity: number } {
  return {
    stroke: "var(--border)",
    strokeOpacity: 0.4,
  };
}

/**
 * Cycle through the 12-hue chart palette. Use when series count is dynamic
 * or unknown at compile time; prefer `var(--chart-c1)` literals where the
 * slot is semantic (e.g. c1 = primary brand series).
 *
 * Returns a CSS var() reference, safe to pass to recharts `fill` / `stroke`
 * props and SVG `stopColor` attributes.
 */
export function chartColor(i: number): string {
  const n = (((i % 12) + 12) % 12) + 1;
  return `var(--chart-c${n})`;
}

/**
 * Semantic color tokens wrapped as var() references. For recharts fills
 * where sentiment matters (gain/loss bars, warning thresholds).
 */
export const semanticColor = {
  gain: "var(--color-gain)",
  loss: "var(--color-loss)",
  warning: "var(--color-warning)",
  neutral: "var(--color-neutral)",
} as const;
