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

export function formatIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function parseIsoDateLocal(yyyyMmDd: string): Date {
  const [y, m, d] = yyyyMmDd.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function monthKeyFromDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export function monthWindowFromDate(d: Date): { start: string; end: string } {
  const year = d.getFullYear();
  const month = d.getMonth();
  return {
    start: formatIsoDate(new Date(year, month, 1)),
    end: formatIsoDate(new Date(year, month + 1, 0)),
  };
}

export function monthWindowFromIso(yyyyMmDd: string): { start: string; end: string } {
  return monthWindowFromDate(parseIsoDateLocal(yyyyMmDd));
}

export function todayIsoLocal(): string {
  return formatIsoDate(new Date());
}

/**
 * Format a YYYY-MM (or any longer ISO prefix) as "June 2026".
 * Returns empty string on malformed input.
 */
export function formatMonthYearFull(yyyyMm: string): string {
  const m = yyyyMm.match(/^(\d{4})-(\d{2})/);
  if (!m) return '';
  const idx = parseInt(m[2], 10) - 1;
  if (idx < 0 || idx > 11) return '';
  return `${MONTH_FULL[idx]} ${m[1]}`;
}

