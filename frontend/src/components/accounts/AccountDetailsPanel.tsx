import { useMemo } from "react";

import { Sparkline } from "@/components/charts/Sparkline";
import {
  computeApyTrend,
  directionSentiment,
  formatTrendAnnotation,
  type ApyHistoryPoint,
} from "@/lib/apyTrend";
import { MONTH_FULL } from "@/lib/dateUtils";
import { useOwnerApi } from "@/lib/useOwnerApi";
import {
  fieldLabel,
  formatDetailDate,
  formatDetailField,
  formatPercent,
  parseDetailDate,
} from "@/lib/formatDetailField";

interface DetailField {
  value: string;
  as_of: string;
}

interface ApyLatest {
  apy_rate: number;
  as_of: string;
  source: string;
}

interface DetailsResponse {
  account_id: string;
  details: Record<string, DetailField>;
  apy_latest: ApyLatest | null;
  apy_history: ApyHistoryPoint[];
}

function formatMonthYear(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})/);
  if (!m) return iso;
  const idx = parseInt(m[2], 10) - 1;
  if (idx < 0 || idx > 11) return iso;
  return `${MONTH_FULL[idx]} ${m[1]}`;
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
// escrow/purchase_price/term_months for autos and vin/gap_flag for
// mortgages, so we don't need to distinguish by type at render time.
// (The DB records both as type=`loan`; `mortgage` type is kept for
// forward-compat but is not the canonical shape in the seeded DB.)
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
  "gap_flag",
  "date_opened",
  "origination_date",
];

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
  return [];
}

function oldestAsOf(rows: RenderedRow[]): string | null {
  const dates = rows
    .map((r) => parseDetailDate(r.asOf))
    .filter((d): d is Date => d !== null)
    .sort((a, b) => a.getTime() - b.getTime());
  return dates.length ? formatDetailDate(dates[0].toISOString()) : null;
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

  const details = data?.details ?? {};
  const apyLatest = data?.apy_latest ?? null;
  const apyHistory = data?.apy_history ?? [];

  const rows = useMemo(() => {
    const order = orderForType(accountType);
    if (order.length > 0) return buildRows(order, details);
    return buildRows(Object.keys(details).sort(), details);
  }, [accountType, details]);

  const trend = useMemo(() => computeApyTrend(apyHistory), [apyHistory]);

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
                strokeClassName={(() => {
                  const sentiment = directionSentiment(trend.direction, accountType);
                  if (sentiment === "good") return "stroke-[var(--color-gain)]";
                  if (sentiment === "bad") return "stroke-[var(--color-loss)]";
                  return "stroke-muted-foreground";
                })()}
                ariaLabel={`APY history, ${trend.direction === "up" ? "rising" : trend.direction === "down" ? "falling" : "flat"}`}
              />
              <div className="flex flex-col items-end text-right">
                {trend.direction !== "flat" && (
                  <span
                    className={`text-xs font-medium tabular-nums ${(() => {
                      const sentiment = directionSentiment(trend.direction, accountType);
                      if (sentiment === "good") return "text-[var(--color-gain)]";
                      if (sentiment === "bad") return "text-[var(--color-loss)]";
                      return "text-foreground";
                    })()}`}
                  >
                    <span aria-hidden="true">{trend.direction === "up" ? "↑" : "↓"}</span>{" "}
                    {formatTrendAnnotation(trend, formatMonthYear)}
                  </span>
                )}
                {trend.direction === "flat" && (
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {formatTrendAnnotation(trend, formatMonthYear)}
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
