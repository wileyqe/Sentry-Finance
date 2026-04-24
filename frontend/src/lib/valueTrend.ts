/**
 * Pure helpers for manual-asset valuation trends (P15-T08).
 *
 * Mirrors `apyTrend.ts` but takes an `{estimated_value, as_of}` series
 * instead of `{apy_rate, as_of}` — used for real-estate and vehicle
 * sparklines on the Account Details panel. Keeping the two helpers
 * separate lets each call site stay typed against its own field name
 * without generic shims.
 *
 * Flat threshold is ±$1 — below a dollar no reasonable property or car
 * value has "moved." For real assets where values are in the tens of
 * thousands, this is effectively equality.
 */

export interface ValueHistoryPoint {
  estimated_value: number;
  as_of: string;
}

export type ValueDirection = "up" | "down" | "flat";

export interface ValueTrend {
  direction: ValueDirection;
  delta: number;
  lastChangeAsOf: string | null;
  firstAsOf: string;
  latestValue: number;
}

const FLAT_THRESHOLD = 1.0;

export function computeValueTrend(history: ValueHistoryPoint[]): ValueTrend | null {
  const clean = history.filter(
    (p) =>
      Number.isFinite(p.estimated_value) &&
      typeof p.as_of === "string" &&
      p.as_of.length > 0,
  );
  if (clean.length < 2) return null;

  const first = clean[0];
  const last = clean[clean.length - 1];
  const delta = last.estimated_value - first.estimated_value;

  let direction: ValueDirection = "flat";
  if (delta > FLAT_THRESHOLD) direction = "up";
  else if (delta < -FLAT_THRESHOLD) direction = "down";

  let lastChangeAsOf: string | null = null;
  for (let i = clean.length - 2; i >= 0; i--) {
    if (Math.abs(clean[i].estimated_value - last.estimated_value) >= FLAT_THRESHOLD) {
      lastChangeAsOf = clean[i + 1].as_of;
      break;
    }
  }

  return {
    direction,
    delta,
    lastChangeAsOf,
    firstAsOf: first.as_of,
    latestValue: last.estimated_value,
  };
}

/**
 * Sentiment bucket for a value change on a manual asset.
 *
 * Real estate mirrors the T07 asset rule — rising home value is good.
 * Vehicles take a third path: depreciation is the baseline, so the
 * trend renders neutral regardless of direction. Passing
 * ``"vehicle"`` here returns ``"neutral"`` on any non-flat direction;
 * ``"real_estate"`` follows the gain/loss rule.
 */
export function valueTrendSentiment(
  direction: ValueDirection,
  assetKind: "real_estate" | "vehicle",
): "good" | "bad" | "neutral" {
  if (direction === "flat") return "neutral";
  if (assetKind === "vehicle") return "neutral";
  // real_estate is an asset — up is good, down is bad.
  return direction === "up" ? "good" : "bad";
}

/**
 * Plain-language annotation for the trend card.
 *
 * Dates render as "April 2025" via the caller-supplied formatter to
 * avoid duplicating locale logic. `formatMoney` formats the delta
 * magnitude as a currency string without a sign (the arrow glyph
 * carries direction).
 */
export function formatValueTrendAnnotation(
  trend: ValueTrend,
  formatMoney: (absValue: number) => string,
  formatMonthYear: (isoDate: string) => string,
): string {
  if (trend.direction === "up" || trend.direction === "down") {
    const verb = trend.direction === "up" ? "Up" : "Down";
    return `${verb} ${formatMoney(Math.abs(trend.delta))} since ${formatMonthYear(trend.firstAsOf)}`;
  }
  if (trend.lastChangeAsOf) {
    return `Unchanged since ${formatMonthYear(trend.lastChangeAsOf)}`;
  }
  return "Unchanged over the last 12 months";
}
