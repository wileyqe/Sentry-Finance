/**
 * Format a number as a USD currency string.
 *
 * - Sign before dollar sign: -$1,234.56
 * - Always 2 decimal places: $43.50, not $43.5
 * - Comma thousand separators: $1,234.56, not $1234.56
 * - Handles zero, positive, negative, null, undefined
 */
export function formatCurrency(amount: number | null | undefined): string {
  if (amount == null || isNaN(amount)) return "$0.00";

  const abs = Math.abs(amount);
  const formatted = abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  if (amount < 0) return `-$${formatted}`;
  return `$${formatted}`;
}
