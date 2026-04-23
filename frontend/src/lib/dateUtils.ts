/**
 * Date-formatting constants and helpers shared across pages.
 *
 * Prefer these over inline `['Jan','Feb',...]` literals so all
 * components render month names consistently.
 */

export const MONTH_ABBR = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
] as const;

export const MONTH_FULL = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

/**
 * Format a YYYY-MM string as "June 2026" (full month + year).
 * Returns empty string on malformed input.
 */
export function formatMonthYearFull(yyyyMm: string): string {
  const [y, m] = yyyyMm.split('-');
  const idx = parseInt(m, 10) - 1;
  if (!y || Number.isNaN(idx) || idx < 0 || idx > 11) return '';
  return `${MONTH_FULL[idx]} ${y}`;
}

