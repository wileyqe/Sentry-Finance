/**
 * InvestmentsHoldings — Holdings tab for the Investments page.
 *
 * Sortable positions table with expandable tax-lot detail rows.
 * Account filter from the parent narrows displayed positions.
 * Wired to /api/investments/holdings and /api/investments/lots.
 */

import { useState, useMemo, useEffect } from "react";
import { useSessionState } from "@/hooks/useSessionState";
import {
  Table, TableHeader, TableBody, TableHead, TableRow, TableCell,
} from "@/components/ui/table";
import { formatCurrency } from "@/lib/formatCurrency";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { apiFetch } from "@/lib/api";
import SyntheticBadge from "@/components/ui/SyntheticBadge";

/* ── Types ────────────────────────────────────────────────────────────────── */

type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

interface InvestmentsTabProps {
  timeframe: Timeframe;
  accountFilter: string;
}

interface TaxLot {
  date: string;
  quantity: number;
  cost_basis: number;
  current_value: number | null;
  gain_loss: number | null;
  holding_period_days: number;
  is_long_term: boolean;
}

interface TaxBucket {
  bucket_type: string;
  balance: number;
  pct: number;
  vested_pct: number;
}

interface Holding {
  ticker: string;
  shares: string;
  price: number | null;
  market_value: number | null;
  cost_basis: number | null;
  total_gain_loss: number | null;
  gain_loss_pct: number | null;
  allocation_pct?: number;
  sector: string | null;
  asset_class: string | null;
}

interface AccountData {
  account_id: string;
  name: string;
  institution_id: string;
  is_synthetic: number;
  tax_status: string | null;
  total_value: number;
  cash_balance: number;
  holdings: Holding[];
}

// Flattened row for the table
interface HoldingRow {
  ticker: string;
  account: string;
  accountId: string;
  isSynthetic: boolean;
  taxStatus: string | null;
  price: number;
  quantity: number;
  value: number;
  portfolioPct: number;
  costBasis: number | null;
  gainLoss: number | null;
  gainLossPct: number | null;
  sector: string | null;
}

type SortKey = "ticker" | "account" | "price" | "quantity" | "value" | "portfolioPct";
type SortDir = "asc" | "desc";

/* ── Helpers ──────────────────────────────────────────────────────────────── */

const SORT_DEFAULTS: Record<SortKey, SortDir> = {
  ticker: "asc",
  account: "asc",
  price: "desc",
  quantity: "desc",
  value: "desc",
  portfolioPct: "desc",
};

function compareFn(key: SortKey, dir: SortDir) {
  return (a: HoldingRow, b: HoldingRow) => {
    let av: string | number = a[key];
    let bv: string | number = b[key];
    if (typeof av === "string") {
      const cmp = av.localeCompare(bv as string);
      return dir === "asc" ? cmp : -cmp;
    }
    return dir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
  };
}

/* ── Tax Badge ──────────────────────────────────────────────────────────── */

const TAX_BADGE_STYLES: Record<string, { label: string; cls: string }> = {
  taxable:     { label: "Taxable",      cls: "text-slate-500 bg-slate-100 dark:bg-slate-800/50 dark:text-slate-400" },
  traditional: { label: "Tax-Deferred", cls: "text-amber-600 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400" },
  roth:        { label: "Roth",         cls: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 dark:text-emerald-400" },
  mixed:       { label: "Mixed",        cls: "text-violet-600 bg-violet-50 dark:bg-violet-900/30 dark:text-violet-400" },
  hsa:         { label: "HSA",          cls: "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 dark:text-emerald-400" },
};

function TaxBadge({ status }: { status: string | null }) {
  if (!status) return null;
  const style = TAX_BADGE_STYLES[status];
  if (!style) return null;
  return (
    <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ml-1.5 ${style.cls}`}>
      {style.label}
    </span>
  );
}

/* ── Sort Icon ───────────────────────────────────────────────────────────── */

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return null;
  return (
    <span className="material-symbols-outlined text-[14px] ml-0.5 align-middle text-muted-foreground">
      {dir === "asc" ? "arrow_upward" : "arrow_downward"}
    </span>
  );
}

/* ── Component ────────────────────────────────────────────────────────────── */

export default function InvestmentsHoldings({ timeframe: _tf, accountFilter }: InvestmentsTabProps) {
  const { data: holdingsData, loading } = useOwnerApi<{ accounts: AccountData[] }>("/api/investments/holdings");
  const [expandedRow, setExpandedRow] = useSessionState<string | null>("holdings:expandedRow", null);
  const [sort, setSort] = useSessionState<{ key: SortKey; dir: SortDir }>("holdings:sort", { key: "value", dir: "desc" });

  const toggleSort = (key: SortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: SORT_DEFAULTS[key] }
    );
  };

  // Flatten accounts → holdings rows (include cash balances as a holding)
  const allRows: HoldingRow[] = useMemo(() => {
    if (!holdingsData?.accounts) return [];
    const rows: HoldingRow[] = [];
    for (const acct of holdingsData.accounts) {
      for (const h of acct.holdings) {
        rows.push({
          ticker: h.ticker,
          account: acct.name,
          accountId: acct.account_id,
          isSynthetic: acct.is_synthetic === 1,
          taxStatus: acct.tax_status,
          price: h.price || 0,
          quantity: parseFloat(h.shares) || 0,
          value: h.market_value || 0,
          portfolioPct: h.allocation_pct || 0,
          costBasis: h.cost_basis,
          gainLoss: h.total_gain_loss,
          gainLossPct: h.gain_loss_pct,
          sector: h.sector,
        });
      }
      // Include cash balance as a distinct "Cash" holding row
      if (acct.cash_balance > 0) {
        const cashPct = acct.total_value > 0
          ? (acct.cash_balance / acct.total_value) * 100
          : 0;
        rows.push({
          ticker: "Cash",
          account: acct.name,
          accountId: acct.account_id,
          isSynthetic: acct.is_synthetic === 1,
          taxStatus: acct.tax_status,
          price: 1.0,
          quantity: acct.cash_balance,
          value: acct.cash_balance,
          portfolioPct: Math.round(cashPct * 10) / 10,
          costBasis: null,
          gainLoss: null,
          gainLossPct: null,
          sector: "Cash",
        });
      }
    }
    return rows;
  }, [holdingsData]);

  const filtered = useMemo(() => {
    if (accountFilter === "all") return allRows;
    return allRows.filter((h) => h.accountId === accountFilter);
  }, [allRows, accountFilter]);

  const sorted = useMemo(
    () => [...filtered].sort(compareFn(sort.key, sort.dir)),
    [filtered, sort]
  );

  const columns: { key: SortKey; label: string; align: "left" | "right" }[] = [
    { key: "ticker",       label: "Ticker",         align: "left" },
    { key: "account",      label: "Account",        align: "left" },
    { key: "price",        label: "Current Price",  align: "right" },
    { key: "quantity",     label: "Qty",            align: "right" },
    { key: "value",        label: "Value",          align: "right" },
    { key: "portfolioPct", label: "% of Portfolio", align: "right" },
  ];

  if (loading) {
    return (
      <div className="card-l1 flex items-center justify-center py-20 text-muted-foreground">
        <span className="material-symbols-outlined animate-spin text-xl mr-2">progress_activity</span>
        Loading holdings...
      </div>
    );
  }

  return (
    <div className="card-l1 overflow-hidden">
      <Table>
        <TableHeader className="bg-slate-50/80 dark:bg-slate-800/30">
          <TableRow>
            <TableHead className="w-8" />
            {columns.map((col) => (
              <TableHead
                key={col.key}
                onClick={() => toggleSort(col.key)}
                className={`cursor-pointer select-none hover:text-foreground transition-colors ${
                  col.align === "right" ? "text-right" : ""
                }`}
              >
                {col.label}
                <SortIcon active={sort.key === col.key} dir={sort.dir} />
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((h) => {
            const rowKey = `${h.ticker}-${h.accountId}`;
            const isExpanded = expandedRow === rowKey;

            return (
              <PositionRow
                key={rowKey}
                holding={h}
                isExpanded={isExpanded}
                onToggle={() => setExpandedRow(isExpanded ? null : rowKey)}
              />
            );
          })}
        </TableBody>
      </Table>

      {sorted.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <span className="material-symbols-outlined text-4xl mb-2">search_off</span>
          <p className="text-sm">No positions found for this account filter.</p>
        </div>
      )}
    </div>
  );
}

/* ── Position Row ─────────────────────────────────────────────────────────── */

function PositionRow({
  holding: h,
  isExpanded,
  onToggle,
}: {
  holding: HoldingRow;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [lots, setLots] = useState<TaxLot[] | null>(null);
  const [lotsLoading, setLotsLoading] = useState(false);
  const [buckets, setBuckets] = useState<TaxBucket[] | null>(null);
  const [bucketsLoading, setBucketsLoading] = useState(false);

  // Track which account IDs we've already fetched buckets for
  const [bucketsFetched, setBucketsFetched] = useState<string | null>(null);

  useEffect(() => {
    if (isExpanded && lots === null && !lotsLoading) {
      setLotsLoading(true);
      apiFetch<{ lots: TaxLot[] }>(
        `/api/investments/lots?account_id=${encodeURIComponent(h.accountId)}&ticker=${encodeURIComponent(h.ticker)}`
      )
        .then((res) => setLots(res.lots))
        .catch(() => setLots([]))
        .finally(() => setLotsLoading(false));
    }
  }, [isExpanded, lots, lotsLoading, h.accountId, h.ticker]);

  // Fetch tax buckets for mixed accounts (once per account)
  useEffect(() => {
    if (isExpanded && h.taxStatus === "mixed" && bucketsFetched !== h.accountId) {
      setBucketsLoading(true);
      setBucketsFetched(h.accountId);
      apiFetch<{ buckets: TaxBucket[] }>(
        `/api/investments/tax-buckets?account_id=${encodeURIComponent(h.accountId)}`
      )
        .then((res) => setBuckets(res.buckets))
        .catch(() => setBuckets([]))
        .finally(() => setBucketsLoading(false));
    }
  }, [isExpanded, h.taxStatus, h.accountId, bucketsFetched]);

  // Label for tax-advantaged accounts in lot expansion
  const taxNote = h.taxStatus === "traditional" ? "Tax-deferred"
    : h.taxStatus === "roth" ? "Tax-free (Roth)"
    : h.taxStatus === "mixed" ? "Mixed tax treatment"
    : null;

  const isTaxable = h.taxStatus === "taxable";

  return (
    <>
      <TableRow
        onClick={onToggle}
        className="cursor-pointer"
      >
        <TableCell className="w-8 px-3">
          <span
            className="material-symbols-outlined text-[16px] text-muted-foreground transition-transform duration-200 inline-block"
            style={{ transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)" }}
          >
            chevron_right
          </span>
        </TableCell>
        <TableCell className="font-bold text-foreground">{h.ticker}</TableCell>
        <TableCell className="text-muted-foreground text-xs">
          {h.account}
          {h.isSynthetic && <> <SyntheticBadge compact /></>}
          <TaxBadge status={h.taxStatus} />
        </TableCell>
        <TableCell className="text-right text-numeric">{formatCurrency(h.price)}</TableCell>
        <TableCell className="text-right text-numeric">{h.quantity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 5 })}</TableCell>
        <TableCell className="text-right font-semibold text-numeric">{formatCurrency(h.value)}</TableCell>
        <TableCell className="text-right text-numeric">{h.portfolioPct.toFixed(1)}%</TableCell>
      </TableRow>

      {/* Expansion panel: tax buckets (mixed accounts) + tax lots */}
      {isExpanded && (
        <tr>
          <td colSpan={7} className="bg-slate-50/60 dark:bg-slate-800/20 px-8 py-3">
            {/* Tax bucket panel for mixed accounts */}
            {h.taxStatus === "mixed" && (
              <div className="mb-3 pb-3 border-b border-border/40">
                <p className="text-xs font-semibold text-muted-foreground mb-2">Tax Buckets</p>
                {bucketsLoading ? (
                  <div className="text-xs text-muted-foreground py-1 flex items-center gap-2">
                    <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                    Loading...
                  </div>
                ) : buckets && buckets.length > 0 ? (
                  <>
                    {/* Stacked bar */}
                    <div className="h-3 w-full rounded-full overflow-hidden flex mb-2">
                      {buckets.map((b) => (
                        <div
                          key={b.bucket_type}
                          className="h-full first:rounded-l-full last:rounded-r-full"
                          style={{
                            width: `${b.pct}%`,
                            backgroundColor: b.bucket_type === "traditional"
                              ? "var(--chart-c6, #f59e0b)"
                              : "var(--chart-c3, #10b981)",
                          }}
                        />
                      ))}
                    </div>
                    {/* Legend */}
                    <div className="flex gap-6 text-xs">
                      {buckets.map((b) => (
                        <div key={b.bucket_type} className="flex items-center gap-2">
                          <div
                            className="size-2.5 rounded-full"
                            style={{
                              backgroundColor: b.bucket_type === "traditional"
                                ? "var(--chart-c6, #f59e0b)"
                                : "var(--chart-c3, #10b981)",
                            }}
                          />
                          <span className="text-muted-foreground">
                            {b.bucket_type === "traditional" ? "Traditional (Tax-deferred)" : "Roth + Tax-exempt"}
                          </span>
                          <span className="font-semibold text-foreground text-numeric">{formatCurrency(b.balance)}</span>
                          <span className="text-muted-foreground text-numeric">{b.pct.toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                    {buckets.every((b) => b.vested_pct >= 1.0) && (
                      <p className="text-[10px] text-muted-foreground mt-1">All 100% vested</p>
                    )}
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">No tax bucket data available.</p>
                )}
              </div>
            )}

            {/* Tax lots */}
            {lotsLoading ? (
              <div className="text-xs text-muted-foreground py-2 flex items-center gap-2">
                <span className="material-symbols-outlined animate-spin text-sm">progress_activity</span>
                Loading tax lots...
              </div>
            ) : lots && lots.length > 0 ? (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-muted-foreground">
                    <th className="text-left py-1.5 font-medium pl-8">Purchase Date</th>
                    <th className="text-right py-1.5 font-medium">Qty</th>
                    <th className="text-right py-1.5 font-medium">Cost Basis</th>
                    <th className="text-right py-1.5 font-medium">Current Value</th>
                    <th className="text-right py-1.5 font-medium">Gain / Loss</th>
                    <th className="text-right py-1.5 font-medium pr-2">
                      {isTaxable ? "Term" : "Tax"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {lots.map((lot, i) => (
                    <tr key={`${lot.date}-${i}`} className="border-t border-border/40">
                      <td className="py-1.5 pl-8 text-muted-foreground">{lot.date}</td>
                      <td className="py-1.5 text-right text-numeric">
                        {lot.quantity.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 5 })}
                      </td>
                      <td className="py-1.5 text-right text-numeric">{formatCurrency(lot.cost_basis)}</td>
                      <td className="py-1.5 text-right text-numeric">
                        {lot.current_value != null ? formatCurrency(lot.current_value) : "\u2014"}
                      </td>
                      <td className={`py-1.5 text-right font-semibold text-numeric ${
                        lot.gain_loss != null && lot.gain_loss >= 0 ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"
                      }`}>
                        {lot.gain_loss != null
                          ? `${lot.gain_loss >= 0 ? "+" : ""}${formatCurrency(lot.gain_loss)}`
                          : "\u2014"}
                      </td>
                      <td className="py-1.5 text-right pr-2">
                        {isTaxable ? (
                          <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${
                            lot.is_long_term
                              ? "text-emerald-600 bg-emerald-50 dark:bg-emerald-900/30 dark:text-emerald-400"
                              : "text-amber-600 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-400"
                          }`}>
                            {lot.is_long_term ? "LT" : "ST"}
                          </span>
                        ) : taxNote ? (
                          <span className="text-[9px] text-muted-foreground">{taxNote}</span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-xs text-muted-foreground py-2">No tax lot data available.</p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
