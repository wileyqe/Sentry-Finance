import { useMemo } from "react";

import { Sparkline } from "@/components/charts/Sparkline";
import {
  computeApyTrend,
  directionSentiment,
  formatTrendAnnotation,
  type ApyHistoryPoint,
} from "@/lib/apyTrend";
import { formatMonthYearFull } from "@/lib/dateUtils";
import { useOwnerApi } from "@/lib/useOwnerApi";
import {
  fieldLabel,
  formatDetailDate,
  formatDetailField,
  formatPercent,
  parseDetailDate,
} from "@/lib/formatDetailField";
import {
  sentimentStrokeClass,
  sentimentTextClass,
} from "@/lib/sentimentClass";

interface DetailField {
  value: string;
  as_of: string;
}

interface ApyLatest {
  apy_rate: number;
  as_of: string;
  source: string;
}

// Composer's typed `collateral` slot (P15-T10). Identity that used to
// live in the loan_details KV — vin / address / purchase_price etc. —
// now arrives here so the loan-side and asset-side panels are
// guaranteed to render the same values for a given pair.
interface VehicleCollateral {
  kind: "vehicle";
  vehicle_id: string;
  make: string;
  model: string;
  year: number;
  vin: string | null;
  purchase_date: string | null;
  purchase_price: number | null;
  gap_insurance: boolean | null;
  description: string;
}

interface RealEstateCollateral {
  kind: "real_estate";
  property_id: number;
  name: string;
  address: string | null;
  purchase_date: string | null;
  purchase_price: number | null;
  description: string;
}

type Collateral = VehicleCollateral | RealEstateCollateral;

interface DetailsResponse {
  account_id: string;
  details: Record<string, DetailField>;
  apy_latest: ApyLatest | null;
  apy_history: ApyHistoryPoint[];
  collateral: Collateral | null;
}

interface AccountDetailsPanelProps {
  accountId: string;
  accountType: string;
  open: boolean;
}

type RenderedRow = { key: string; label: string; value: string; asOf: string };

function buildRows(
  order: string[],
  details: Record<string, DetailField>,
): RenderedRow[] {
  const rows: RenderedRow[] = [];
  for (const key of order) {
    const raw = details[key];
    if (!raw) continue;
    const rendered = formatDetailField(key, raw.value);
    if (rendered == null) continue;
    rows.push({ key, label: fieldLabel(key), value: rendered, asOf: raw.as_of });
  }
  return rows;
}

const DEPOSIT_ORDER = [
  "available_balance",
  "present_balance",
  "dividends_ytd",
  "last_year_dividends",
  "ytd_interest",
  "last_statement_date",
  "direct_deposit_enrolled",
  "date_opened",
];

const CREDIT_CARD_ORDER = [
  "purchase_apr",
  "cash_advance_apr",
  "credit_limit",
  "available_credit",
  "statement_balance",
  "remaining_statement_balance",
  "minimum_payment",
  "payment_due_date",
  "next_closing_date",
  "last_payment",
  "14_day_payoff",
  "ytd_interest",
  "rewards_points",
  "cash_advance_limit",
  "cash_advance_available",
  "cash_advance_balance",
  "automatic_payments",
  "date_opened",
];

// Unified loan order — mortgage and auto loans share one schema with
// different populated fields. The hide-if-missing rule naturally drops
// escrow/term_months for autos and gap/vin for mortgages, so we don't
// distinguish by type at render time. (The DB records both as
// type=`loan`; `mortgage` type is kept for forward-compat but is not
// the canonical shape in the seeded DB.)
//
// P15-T10 update: collateral identity (vin, collateral_description,
// gap_flag, purchase_price, purchase_date, address) is composed by
// `dal/account_details_composer.py` and merged into `details` here.
// LOAN_ORDER keeps the slot for each so they render in their existing
// position; ordering matches the visual scan path users are used to.
const LOAN_ORDER = [
  "interest_rate",
  "payoff_today",
  "14_day_payoff",
  "minimum_payment",
  "original_loan_amount",
  "purchase_price",
  "remaining_term",
  "term_months",
  "payments_made",
  "escrow_balance",
  "ytd_interest",
  "collateral_type",
  "collateral_description",
  "vin",
  "address",
  "gap_flag",
  "purchase_date",
  "origination_date",
];

// Investment / retirement accounts intentionally render nothing
// structured here yet — per-fund yield, distributions, and contribution
// summaries land with the planned extractor work. The empty array
// signals `orderForType` to fall through to the explicit empty-state
// branch instead of the alphabetical loan-detail fallback.
const INVESTMENT_ORDER: string[] = [];

const INVESTMENT_TYPES = new Set(["investment", "retirement"]);

function orderForType(accountType: string): string[] {
  const t = (accountType || "").toLowerCase();
  if (t === "checking" || t === "savings") return DEPOSIT_ORDER;
  if (t === "credit_card" || t === "credit") return CREDIT_CARD_ORDER;
  if (
    t === "loan" ||
    t === "mortgage" ||
    t === "auto_loan" ||
    t === "auto" ||
    t === "bnpl"
  )
    return LOAN_ORDER;
  if (INVESTMENT_TYPES.has(t)) return INVESTMENT_ORDER;
  return [];
}

// Synthesize `details`-shaped entries from the composer's typed
// `collateral` slot so the existing iterator + label/format pipeline
// render them in their LOAN_ORDER position. Synthesized rows carry an
// empty `as_of` so `oldestAsOf` ignores them — the staleness footer
// reflects when real `loan_details` were last scraped, not when the
// panel rendered.
function mergeCollateralIntoDetails(
  details: Record<string, DetailField>,
  collateral: Collateral | null,
): Record<string, DetailField> {
  if (!collateral) return details;
  const merged: Record<string, DetailField> = { ...details };
  const put = (key: string, value: string | number | boolean | null) => {
    if (value == null || value === "") return;
    if (merged[key]) return; // never override a real loan_details row
    merged[key] = { value: String(value), as_of: "" };
  };
  put("purchase_price", collateral.purchase_price);
  put("purchase_date", collateral.purchase_date);
  if (collateral.kind === "vehicle") {
    put("collateral_description", collateral.description);
    put("vin", collateral.vin);
    put("gap_flag", collateral.gap_insurance == null
      ? null
      : (collateral.gap_insurance ? "Yes" : "No"));
  } else {
    // Address IS the collateral description for real estate, so we
    // only synthesize the Address row to avoid two labels for one value.
    put("address", collateral.address);
  }
  return merged;
}

function oldestAsOf(rows: RenderedRow[]): string | null {
  let min: Date | null = null;
  for (const r of rows) {
    if (!r.asOf) continue;
    const d = parseDetailDate(r.asOf);
    if (d && (!min || d < min)) min = d;
  }
  return min ? formatDetailDate(min.toISOString()) : null;
}

export function AccountDetailsPanel({
  accountId,
  accountType,
  open,
}: AccountDetailsPanelProps) {
  const { data, loading, error } = useOwnerApi<DetailsResponse>(
    `/api/accounts/${encodeURIComponent(accountId)}/details`,
    { skip: !open },
  );

  const rawDetails = data?.details ?? {};
  const collateral = data?.collateral ?? null;
  const apyLatest = data?.apy_latest ?? null;
  const apyHistory = data?.apy_history ?? [];

  const details = useMemo(
    () => mergeCollateralIntoDetails(rawDetails, collateral),
    [rawDetails, collateral],
  );

  const isInvestmentLike = INVESTMENT_TYPES.has(
    (accountType || "").toLowerCase(),
  );

  const rows = useMemo(() => {
    const order = orderForType(accountType);
    if (order.length > 0) return buildRows(order, details);
    return buildRows(Object.keys(details).sort(), details);
  }, [accountType, details]);

  const trend = useMemo(() => computeApyTrend(apyHistory), [apyHistory]);
  const trendSentiment = trend
    ? directionSentiment(trend.direction, accountType)
    : "neutral";

  if (!open) return null;

  if (loading && !data) {
    return (
      <div className="px-6 py-3 text-xs text-muted-foreground border-t border-border/60">
        Loading details…
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-6 py-3 text-xs text-[var(--color-loss)] border-t border-border/60">
        Couldn't load details: {error.message}
      </div>
    );
  }

  const hasApy = apyLatest != null;
  const apyValue = hasApy ? formatPercent(apyLatest.apy_rate) : null;
  const hasAnyContent = hasApy || rows.length > 0;

  if (isInvestmentLike) {
    return (
      <div
        className="px-6 py-3 text-xs text-muted-foreground border-t border-border/60"
        data-slot="account-details-panel"
        data-account-id={accountId}
        data-empty-reason="investment-no-scraped-details"
      >
        No investment details captured yet. Per-fund yield, distributions,
        and contribution summaries are tracked in P15-T09.
      </div>
    );
  }

  if (!hasAnyContent) {
    return (
      <div className="px-6 py-3 text-xs text-muted-foreground border-t border-border/60">
        No scraped details yet for this account.
      </div>
    );
  }

  const oldestDetail = oldestAsOf(rows);

  return (
    <div
      className="border-t border-border/60 bg-muted/30 px-6 py-3"
      data-slot="account-details-panel"
      data-account-id={accountId}
    >
      {hasApy && (
        <div className="mb-3 rounded-md bg-background px-3 py-2">
          <div className="flex items-baseline justify-between">
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">APY</span>
              <span className="text-[10px] text-muted-foreground/80">
                as of {formatDetailDate(apyLatest.as_of)} · {apyLatest.source}
              </span>
            </div>
            <span className="text-lg font-semibold text-foreground tabular-nums">
              {apyValue}
            </span>
          </div>
          {trend && (
            <div className="mt-2 flex items-center justify-between gap-3">
              <Sparkline
                values={apyHistory.map((p) => p.apy_rate)}
                width={120}
                height={32}
                strokeClassName={sentimentStrokeClass(trendSentiment)}
                ariaLabel={`APY history, ${trend.direction === "up" ? "rising" : trend.direction === "down" ? "falling" : "flat"}`}
              />
              <div className="flex flex-col items-end text-right">
                {trend.direction !== "flat" && (
                  <span
                    className={`text-xs font-medium tabular-nums ${sentimentTextClass(trendSentiment)}`}
                  >
                    <span aria-hidden="true">{trend.direction === "up" ? "↑" : "↓"}</span>{" "}
                    {formatTrendAnnotation(trend, formatMonthYearFull)}
                  </span>
                )}
                {trend.direction === "flat" && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {formatTrendAnnotation(trend, formatMonthYearFull)}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      {rows.length > 0 && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div
              key={row.key}
              className="flex items-baseline justify-between gap-3 text-xs"
            >
              <span className="text-muted-foreground">{row.label}</span>
              <span
                className={`text-foreground tabular-nums ${
                  row.key === "vin" ? "font-mono text-[11px]" : "font-medium"
                }`}
              >
                {row.value}
              </span>
            </div>
          ))}
        </div>
      )}
      {oldestDetail && (
        <div className="mt-3 text-[10px] uppercase tracking-wide text-muted-foreground">
          Scraped {oldestDetail}
        </div>
      )}
    </div>
  );
}
