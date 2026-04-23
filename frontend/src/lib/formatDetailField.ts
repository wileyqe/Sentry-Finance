/**
 * Field-aware formatters for the Account Details panel (P15-T06).
 *
 * The `/api/accounts/{id}/details` endpoint returns every scraped
 * `loan_details` row as `{value: string, as_of: string}`. The raw
 * `value` string mirrors whatever the portal rendered — sometimes with
 * a currency sign, sometimes with a percent sign, sometimes a plain
 * number. This module maps known field names to a canonical rendered
 * string so the UI doesn't have to sprinkle type-casting logic.
 *
 * Unknown fields fall through as plain text.
 */
import { formatCurrency } from "./formatCurrency";
import { MONTH_ABBR } from "./dateUtils";

type FieldKind =
  | "currency"
  | "percent"
  | "date"
  | "count"
  | "boolean"
  | "months"
  | "text";

const FIELD_KINDS: Record<string, FieldKind> = {
  // Currency (dollar amounts)
  available_balance: "currency",
  available_credit: "currency",
  cash_advance_available: "currency",
  cash_advance_balance: "currency",
  cash_advance_limit: "currency",
  credit_limit: "currency",
  dividends_ytd: "currency",
  escrow_balance: "currency",
  last_payment: "currency",
  last_year_dividends: "currency",
  minimum_payment: "currency",
  original_loan_amount: "currency",
  payoff_today: "currency",
  present_balance: "currency",
  purchase_price: "currency",
  remaining_statement_balance: "currency",
  statement_balance: "currency",
  ytd_interest: "currency",
  "14_day_payoff": "currency",

  // Percent (interest / yield)
  cash_advance_apr: "percent",
  interest_rate: "percent",
  purchase_apr: "percent",

  // Dates
  date_opened: "date",
  last_statement_date: "date",
  next_closing_date: "date",
  origination_date: "date",
  payment_due_date: "date",

  // Count (integer with suffix)
  payments_made: "count",
  rewards_points: "count",

  // Boolean (Yes/No)
  automatic_payments: "boolean",
  direct_deposit_enrolled: "boolean",
  gap_flag: "boolean",

  // Months
  remaining_term: "months",
  term_months: "months",

  // Plain text
  collateral_description: "text",
  collateral_type: "text",
  vin: "text",
};

function parseCurrency(raw: string): number | null {
  const cleaned = raw.replace(/[$,\s]/g, "");
  const n = parseFloat(cleaned);
  return Number.isFinite(n) ? n : null;
}

function parsePercent(raw: string): number | null {
  const cleaned = raw.replace(/[%\s]/g, "");
  const n = parseFloat(cleaned);
  return Number.isFinite(n) ? n : null;
}

function parseCount(raw: string): number | null {
  const cleaned = raw.replace(/[,\s]/g, "");
  const n = parseInt(cleaned, 10);
  return Number.isFinite(n) ? n : null;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

/**
 * Parse a date-ish string emitted by either ``loan_details.as_of``
 * (ISO datetime: ``2026-04-20T10:00:00``) or a scraped portal date
 * (``MM/DD/YYYY`` or ``YYYY-MM-DD``). Returns null if unrecognised.
 */
export function parseDetailDate(raw: string): Date | null {
  if (!raw) return null;
  const isoMatch = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) {
    const d = new Date(`${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}T00:00:00`);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const usMatch = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (usMatch) {
    const d = new Date(Number(usMatch[3]), Number(usMatch[1]) - 1, Number(usMatch[2]));
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function formatDetailDate(raw: string): string {
  const d = parseDetailDate(raw);
  if (!d) return raw;
  return `${MONTH_ABBR[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

/**
 * Detect garbage values that bled through from Chase's subtitle lines
 * ("as of 12:00 AM ET on 04/17/2026"). T05 mitigated most of these at
 * scrape time, but a belt-and-suspenders UI filter keeps them from
 * rendering if anything slips through.
 */
function isGarbageValue(value: string): boolean {
  return /\bas of\b/i.test(value);
}

/**
 * Return a rendered value string for a known field, or null if the
 * raw value is empty, unparseable for its kind, or garbage-shaped.
 * Null tells the caller to hide the row entirely.
 */
export function formatDetailField(
  fieldName: string,
  rawValue: string | null | undefined,
): string | null {
  if (rawValue == null) return null;
  const raw = String(rawValue).trim();
  if (!raw) return null;
  if (isGarbageValue(raw)) return null;

  const kind = FIELD_KINDS[fieldName] ?? "text";

  switch (kind) {
    case "currency": {
      const n = parseCurrency(raw);
      return n == null ? null : formatCurrency(n);
    }
    case "percent": {
      const n = parsePercent(raw);
      return n == null ? null : formatPercent(n);
    }
    case "count": {
      const n = parseCount(raw);
      if (n == null) return null;
      const suffix = fieldName === "rewards_points" ? " pts" : "";
      return `${n.toLocaleString("en-US")}${suffix}`;
    }
    case "months": {
      const n = parseCount(raw);
      return n == null ? null : `${n.toLocaleString("en-US")} mo`;
    }
    case "boolean": {
      return /^(yes|y|true|enrolled|on)$/i.test(raw) ? "Yes" : "No";
    }
    case "date": {
      return formatDetailDate(raw);
    }
    case "text":
    default:
      return raw;
  }
}

/**
 * Human label for a field name — "purchase_apr" → "Purchase APR".
 * Falls back to title-casing the snake_case field name.
 */
const FIELD_LABELS: Record<string, string> = {
  available_balance: "Available Balance",
  available_credit: "Available Credit",
  automatic_payments: "Automatic Payments",
  cash_advance_apr: "Cash Advance APR",
  cash_advance_available: "Cash Advance Available",
  cash_advance_balance: "Cash Advance Balance",
  cash_advance_limit: "Cash Advance Limit",
  collateral_description: "Collateral",
  collateral_type: "Collateral Type",
  credit_limit: "Credit Limit",
  date_opened: "Date Opened",
  direct_deposit_enrolled: "Direct Deposit",
  dividends_ytd: "Dividends YTD",
  escrow_balance: "Escrow Balance",
  gap_flag: "GAP Insurance",
  interest_rate: "Interest Rate",
  last_payment: "Last Payment",
  last_statement_date: "Last Statement",
  last_year_dividends: "Last Year Dividends",
  minimum_payment: "Minimum Payment",
  next_closing_date: "Next Closing Date",
  origination_date: "Originated",
  original_loan_amount: "Original Loan Amount",
  payment_due_date: "Payment Due",
  payments_made: "Payments Made",
  payoff_today: "Payoff Today",
  present_balance: "Present Balance",
  purchase_apr: "Purchase APR",
  purchase_price: "Purchase Price",
  remaining_statement_balance: "Remaining Statement",
  remaining_term: "Remaining Term",
  rewards_points: "Rewards",
  statement_balance: "Statement Balance",
  term_months: "Term",
  vin: "VIN",
  ytd_interest: "YTD Interest",
  "14_day_payoff": "14-Day Payoff",
};

export function fieldLabel(fieldName: string): string {
  if (FIELD_LABELS[fieldName]) return FIELD_LABELS[fieldName];
  return fieldName
    .split("_")
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}
