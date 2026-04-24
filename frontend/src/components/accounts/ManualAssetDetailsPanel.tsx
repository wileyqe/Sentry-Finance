import { useMemo } from "react";

import { Sparkline } from "@/components/charts/Sparkline";
import { formatCurrency } from "@/lib/formatCurrency";
import { formatMonthYearFull } from "@/lib/dateUtils";
import { useOwnerApi } from "@/lib/useOwnerApi";
import {
  fieldLabel,
  formatDetailDate,
  formatDetailField,
  parseDetailDate,
} from "@/lib/formatDetailField";
import {
  sentimentStrokeClass,
  sentimentTextClass,
} from "@/lib/sentimentClass";
import {
  computeValueTrend,
  formatValueTrendAnnotation,
  valueTrendSentiment,
  type ValueHistoryPoint,
} from "@/lib/valueTrend";

type AssetKind = "real_estate" | "vehicle";

interface DetailField {
  value: string;
  as_of: string;
}

interface LatestValuation {
  estimated_value: number;
  source: string | null;
  as_of: string;
}

interface RealEstateDetailsResponse {
  property_id: number;
  name: string;
  address: string | null;
  purchase_price: number | null;
  purchase_date: string | null;
  latest_valuation: LatestValuation | null;
  valuation_history: ValueHistoryPoint[];
  linked_loan_id: string | null;
  details: Record<string, DetailField>;
}

interface VehicleDetailsResponse {
  vehicle_id: string;
  make: string;
  model: string;
  year: number;
  purchase_date: string | null;
  purchase_price: number | null;
  vin: string | null;
  gap_insurance: boolean | null;
  linked_loan_id: string | null;
  latest_valuation: LatestValuation | null;
  valuation_history: ValueHistoryPoint[];
  suggested_value: number | null;
  depreciation_curve: string | null;
  details: Record<string, DetailField>;
}

type DetailsResponse = RealEstateDetailsResponse | VehicleDetailsResponse;

interface ManualAssetDetailsPanelProps {
  assetKind: AssetKind;
  assetId: string | number;
  open: boolean;
}

type RenderedRow = { key: string; label: string; value: string };

// Mortgage/auto-loan field order when rendered under a manual-asset panel.
// Matches the LOAN_ORDER used by `AccountDetailsPanel` but drops fields
// that duplicate info already shown on the asset's hero card. Collateral
// identity (vin / address / gap / purchase_*) lives on the asset row
// and renders via `buildAssetRows`; rendering it again here would
// double-display the same value.
const LINKED_LOAN_ORDER = [
  "interest_rate",
  "payoff_today",
  "14_day_payoff",
  "minimum_payment",
  "remaining_term",
  "term_months",
  "payments_made",
  "escrow_balance",
  "ytd_interest",
  "collateral_type",
  "origination_date",
];

function buildLoanRows(details: Record<string, DetailField>): RenderedRow[] {
  const rows: RenderedRow[] = [];
  for (const key of LINKED_LOAN_ORDER) {
    const raw = details[key];
    if (!raw) continue;
    const rendered = formatDetailField(key, raw.value);
    if (rendered == null) continue;
    rows.push({ key, label: fieldLabel(key), value: rendered });
  }
  return rows;
}

function buildAssetRows(data: DetailsResponse, kind: AssetKind): RenderedRow[] {
  const rows: RenderedRow[] = [];
  const push = (key: string, rawValue: string | number | null | undefined) => {
    if (rawValue == null || rawValue === "") return;
    const rendered = formatDetailField(key, String(rawValue));
    if (rendered == null) return;
    rows.push({ key, label: fieldLabel(key), value: rendered });
  };

  if (kind === "vehicle") {
    const v = data as VehicleDetailsResponse;
    push("year", v.year);
    push("vin", v.vin);
    push("purchase_date", v.purchase_date);
    push("purchase_price", v.purchase_price);
    if (v.gap_insurance != null) {
      push("gap_insurance", v.gap_insurance ? "Yes" : "No");
    }
    if (v.suggested_value != null) push("suggested_value", v.suggested_value);
  } else {
    const re = data as RealEstateDetailsResponse;
    push("address", re.address);
    push("purchase_date", re.purchase_date);
    push("purchase_price", re.purchase_price);
    if (re.latest_valuation?.source) {
      rows.push({
        key: "source",
        label: fieldLabel("source"),
        value: re.latest_valuation.source,
      });
    }
  }
  return rows;
}

export function ManualAssetDetailsPanel({
  assetKind,
  assetId,
  open,
}: ManualAssetDetailsPanelProps) {
  const path =
    assetKind === "real_estate"
      ? `/api/real_estate/${encodeURIComponent(String(assetId))}/details`
      : `/api/vehicles/${encodeURIComponent(String(assetId))}/details`;

  const { data, loading, error } = useOwnerApi<DetailsResponse>(path, { skip: !open });

  const history = data?.valuation_history ?? [];
  const latest = data?.latest_valuation ?? null;

  const trend = useMemo(() => computeValueTrend(history), [history]);

  const assetRows = useMemo(
    () => (data ? buildAssetRows(data, assetKind) : []),
    [data, assetKind],
  );
  const loanRows = useMemo(
    () => (data ? buildLoanRows(data.details) : []),
    [data],
  );

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

  if (!data) return null;

  const hasValuation = latest != null;
  const hasAnyContent = hasValuation || assetRows.length > 0 || loanRows.length > 0;

  if (!hasAnyContent) {
    return (
      <div className="px-6 py-3 text-xs text-muted-foreground border-t border-border/60">
        No details yet for this asset.
      </div>
    );
  }

  const sentiment = trend ? valueTrendSentiment(trend.direction, assetKind) : "neutral";
  const strokeClass = sentimentStrokeClass(sentiment);
  const textClass = sentimentTextClass(sentiment);

  return (
    <div
      className="border-t border-border/60 bg-muted/30 px-6 py-3"
      data-slot="manual-asset-details-panel"
      data-asset-kind={assetKind}
      data-asset-id={String(assetId)}
    >
      {hasValuation && (
        <div className="mb-3 rounded-md bg-background px-3 py-2">
          <div className="flex items-baseline justify-between">
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">
                {assetKind === "real_estate" ? "Estimated Value" : "Current Value"}
              </span>
              <span className="text-[10px] text-muted-foreground/80">
                as of {formatDetailDate(latest!.as_of)}
                {latest!.source ? ` · ${latest!.source}` : ""}
              </span>
            </div>
            <span className="text-lg font-semibold text-foreground tabular-nums">
              {formatCurrency(latest!.estimated_value)}
            </span>
          </div>
          {trend && (
            <div className="mt-2 flex items-center justify-between gap-3">
              <Sparkline
                values={history.map((p) => p.estimated_value)}
                width={120}
                height={32}
                strokeClassName={strokeClass}
                ariaLabel={`Valuation history, ${
                  trend.direction === "up"
                    ? "rising"
                    : trend.direction === "down"
                      ? "falling"
                      : "flat"
                }`}
              />
              <div className="flex flex-col items-end text-right">
                <span className={`text-xs font-medium tabular-nums ${textClass}`}>
                  {trend.direction !== "flat" && (
                    <span aria-hidden="true">
                      {trend.direction === "up" ? "↑" : "↓"}
                    </span>
                  )}{" "}
                  {formatValueTrendAnnotation(
                    trend,
                    (n) => formatCurrency(n),
                    formatMonthYearFull,
                  )}
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {(assetRows.length > 0 || loanRows.length > 0) && (
        <div className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
          {[...assetRows, ...loanRows].map((row) => (
            <div
              key={row.key}
              className="flex items-baseline justify-between gap-3 text-xs"
            >
              <span className="text-muted-foreground">{row.label}</span>
              <span className="text-foreground tabular-nums font-medium">
                {row.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {latest && parseDetailDate(latest.as_of) && (
        <div className="mt-3 text-[10px] uppercase tracking-wide text-muted-foreground">
          Valued {formatDetailDate(latest.as_of)}
        </div>
      )}
    </div>
  );
}
