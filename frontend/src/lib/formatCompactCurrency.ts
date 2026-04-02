/**
 * Abbreviate large currency values for KPI cards so they
 * don't truncate in narrow containers.
 *
 * Examples:
 *   formatCompactCurrency(15192)    →  "$15.2K"
 *   formatCompactCurrency(207400)   →  "$207.4K"
 *   formatCompactCurrency(1_500_000) → "$1.5M"
 *   formatCompactCurrency(9500)     →  "$9,500"   (below threshold)
 *   formatCompactCurrency(-3936)    →  "-$3,936"  (below threshold)
 *   formatCompactCurrency(0)        →  "$0"
 *
 * Values under ±10 000 are formatted normally (with commas, no decimals).
 * Values ≥ 10 000 are abbreviated with K/M/B suffixes.
 */
export function formatCompactCurrency(
  amount: number | null | undefined,
): string {
  if (amount == null || isNaN(amount)) return "$0";

  const abs = Math.abs(amount);
  const sign = amount < 0 ? "-" : "";

  if (abs >= 1_000_000_000) {
    return `${sign}$${(abs / 1_000_000_000).toFixed(1)}B`;
  }
  if (abs >= 1_000_000) {
    return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 10_000) {
    return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  }

  // Below 10K — show full number with comma separators, no decimals
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
  return `${sign}$${formatted}`;
}
