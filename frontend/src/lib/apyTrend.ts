/**
 * Pure helpers for APY trend annotation on the Account Details panel.
 *
 * Input is the `apy_history` array the `/api/accounts/{id}/details`
 * endpoint ships under P15-T07 — ascending chronological rows of
 * `{apy_rate, as_of}`.
 *
 * A half-basis-point threshold (0.0005%) is the "flat" guard. APYs are
 * stored as percent-scaled floats (e.g. 4.00 for 4%), so 0.0005 really
 * is half a basis point, not half a percent.
 */

export interface ApyHistoryPoint {
  apy_rate: number;
  as_of: string;
}

export type ApyDirection = "up" | "down" | "flat";

export interface ApyTrend {
  direction: ApyDirection;
  delta: number;
  lastChangeAsOf: string | null;
  firstAsOf: string;
  latestRate: number;
}

const FLAT_THRESHOLD = 0.0005;

export function computeApyTrend(history: ApyHistoryPoint[]): ApyTrend | null {
  const clean = history.filter(
    (p) => Number.isFinite(p.apy_rate) && typeof p.as_of === "string" && p.as_of.length > 0,
  );
  if (clean.length < 2) return null;

  const first = clean[0];
  const last = clean[clean.length - 1];
  const delta = last.apy_rate - first.apy_rate;

  let direction: ApyDirection = "flat";
  if (delta > FLAT_THRESHOLD) direction = "up";
  else if (delta < -FLAT_THRESHOLD) direction = "down";

  // Scan backward from the latest entry; the last row whose rate diverges
  // from the latest by ≥ threshold is the "last change" date. Null means
  // the rate never moved in the window.
  let lastChangeAsOf: string | null = null;
  for (let i = clean.length - 2; i >= 0; i--) {
    if (Math.abs(clean[i].apy_rate - last.apy_rate) >= FLAT_THRESHOLD) {
      lastChangeAsOf = clean[i + 1].as_of;
      break;
    }
  }

  return {
    direction,
    delta,
    lastChangeAsOf,
    firstAsOf: first.as_of,
    latestRate: last.apy_rate,
  };
}

/**
 * Map a direction + account type to a "good" / "bad" / "neutral" bucket
 * so the caller can choose the right color class. Savings/checking treat
 * a rising rate as good; loans/credit cards treat it as bad.
 */
export function directionSentiment(
  direction: ApyDirection,
  accountType: string,
): "good" | "bad" | "neutral" {
  if (direction === "flat") return "neutral";
  const t = (accountType || "").toLowerCase();
  const isLiability =
    t === "credit_card" ||
    t === "credit" ||
    t === "loan" ||
    t === "mortgage" ||
    t === "auto_loan" ||
    t === "auto" ||
    t === "bnpl";
  if (isLiability) {
    return direction === "up" ? "bad" : "good";
  }
  // Assets (checking, savings, and anything else we haven't classified)
  return direction === "up" ? "good" : "bad";
}

/**
 * Human copy for the trend annotation. Plain language, no jargon.
 * Dates render as "April 2025" (month + year) via the provided
 * formatter so we don't duplicate locale logic here.
 */
export function formatTrendAnnotation(
  trend: ApyTrend,
  formatMonthYear: (isoDate: string) => string,
): string {
  if (trend.direction === "up" || trend.direction === "down") {
    const verb = trend.direction === "up" ? "Up" : "Down";
    const magnitude = Math.abs(trend.delta).toFixed(2);
    return `${verb} ${magnitude}% since ${formatMonthYear(trend.firstAsOf)}`;
  }
  // flat
  if (trend.lastChangeAsOf) {
    return `Unchanged since ${formatMonthYear(trend.lastChangeAsOf)}`;
  }
  return "Unchanged over the last 12 months";
}
