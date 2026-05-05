import { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../lib/api";
import { useView } from "../context/ViewContext";
import LifestyleCreepPanel from "../components/LifestyleCreepPanel";
import { formatCurrency } from "@/lib/formatCurrency";
import { formatCompactCurrency } from "@/lib/formatCompactCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { Skeleton } from "@/components/Skeleton";
import { useRuntimeContext } from "@/context/RuntimeContext";
import { parseIsoDateLocal } from "@/lib/dateUtils";
import { withOwnerQuery } from "@/lib/ownerRequest";

/* ── Helpers ──────────────────────────────────────────────────────── */

const fmtPct = (n: number | null | undefined) =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

const monthName = (m: string) => {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1).toLocaleString("en-US", { month: "long", year: "numeric" });
};

/* ── Month selector helper ────────────────────────────────────────── */

function buildMonthOptions(referenceDate: string, count = 24) {
  const opts: string[] = [];
  const d = parseIsoDateLocal(referenceDate);
  d.setDate(1);
  d.setMonth(d.getMonth() - 1); // start from prior month
  for (let i = 0; i < count; i++) {
    const y = d.getFullYear();
    const mo = d.getMonth() + 1;
    opts.push(`${y}-${String(mo).padStart(2, "0")}`);
    d.setMonth(d.getMonth() - 1);
  }
  return opts;
}

/* ── Types ────────────────────────────────────────────────────────── */

interface PreTaxBlock {
  gross_income: number;
  federal_tax: number;
  state_tax: number;
  deductions: number;
  net_pay: number;
  savings_rate_pct: number;
  data_quality: string;
}

interface ReviewData {
  month: string;
  income: { total: number; prior_month: number; trailing_12m_avg: number; mom_change_pct: number };
  spending: { total: number; prior_month: number; trailing_12m_avg: number; mom_change_pct: number };
  savings_rate: number;
  net_worth_delta: { amount: number; pct: number; direction: string };
  budget_highlights: any[];
  subscription_changes: any[];
  notable_transactions: any[];
  large_transfers: any[];
  uncategorized_count: number;
  lifestyle_flags: any[];
  freshness: any[];
  pre_tax: PreTaxBlock | null;
}

/* ── Component ────────────────────────────────────────────────────── */

export default function MonthlyReviewPage() {
  const { ownerParam } = useView();
  const { referenceDate, ready: runtimeReady } = useRuntimeContext();
  const monthOpts = useMemo(() => buildMonthOptions(referenceDate, 24), [referenceDate]);
  const [month, setMonth] = useState(monthOpts[0]);
  const [data, setData] = useState<ReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lifestyleData, setLifestyleData] = useState<any>(null);
  const [didAutoFind, setDidAutoFind] = useState(false);

  // On mount, find the latest month with data so we don't land on an empty month
  useEffect(() => {
    if (!runtimeReady || didAutoFind) return;
    setLoading(true);
    (async () => {
      for (const m of monthOpts.slice(0, 6)) {
        try {
          const monthlyPath = withOwnerQuery("/api/review/monthly", ownerParam, { month: m });
          const d = await apiFetch<ReviewData>(monthlyPath);
          if (d && (d.income.total > 0 || d.spending.total > 0)) {
            setMonth(m);
            setData(d);
            setDidAutoFind(true);
            setLoading(false);
            return;
          }
        } catch { /* try next */ }
      }
      // If nothing found, stay on the default
      setDidAutoFind(true);
      setLoading(false);
    })();
  }, [monthOpts, ownerParam, runtimeReady, didAutoFind]);

  useEffect(() => {
    setMonth(monthOpts[0]);
    setDidAutoFind(false);
  }, [monthOpts]);

  useEffect(() => {
    if (!didAutoFind) return;
    const monthlyPath = withOwnerQuery("/api/review/monthly", ownerParam, { month });
    const lifestylePath = withOwnerQuery("/api/lifestyle/creep", ownerParam);
    setLoading(true);
    apiFetch<ReviewData>(monthlyPath)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));

    apiFetch(lifestylePath)
      .then(setLifestyleData)
      .catch(() => setLifestyleData(null));
  }, [month, ownerParam, didAutoFind]);

  const navigateMonth = (dir: -1 | 1) => {
    const idx = monthOpts.indexOf(month);
    const next = idx - dir; // list is reverse chronological
    if (next >= 0 && next < monthOpts.length) setMonth(monthOpts[next]);
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          <Skeleton className="h-8 w-72 rounded-lg" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-28 rounded-xl" />
            ))}
          </div>
          <Skeleton className="h-64 rounded-xl" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <span className="material-symbols-outlined mr-2">error</span>
        Failed to load monthly review
      </div>
    );
  }

  const nwDelta = data.net_worth_delta;
  const cashSurplus = data.income.total - data.spending.total;
  const nonCashDelta = nwDelta.amount - cashSurplus;
  const nwIsUp = nwDelta.direction === 'up' || (nwDelta.direction !== 'down' && nwDelta.amount >= 0);
  const nwAbsParts = formatCurrency(Math.abs(nwDelta.amount)).replace('$', '').split('.');
  const nwAbsDollars = nwAbsParts[0] || '0';
  const nwAbsCents = nwAbsParts[1] || '00';

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* ── Header Row ──────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-foreground">
            Monthly Review — {monthName(month)}
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigateMonth(-1)}
              disabled={monthOpts.indexOf(month) === monthOpts.length - 1}
              className="p-1.5 rounded-lg hover:bg-muted disabled:opacity-30 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">chevron_left</span>
            </button>
            <select
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="text-sm border border-border rounded-lg px-3 py-1.5 bg-card text-foreground"
            >
              {monthOpts.map((m) => (
                <option key={m} value={m}>{monthName(m)}</option>
              ))}
            </select>
            <button
              onClick={() => navigateMonth(1)}
              disabled={monthOpts.indexOf(month) === 0}
              className="p-1.5 rounded-lg hover:bg-muted disabled:opacity-30 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">chevron_right</span>
            </button>
          </div>
        </div>

        {/* ── Net Worth Change — editorial hero ─────────────────── */}
        <div className="card-l1 p-6">
          <div className="relative pl-5">
            <span
              className={`absolute left-0 top-1 bottom-1 w-[3px] rounded-full ${nwIsUp ? 'bg-[var(--color-gain)]' : 'bg-[var(--color-loss)]'}`}
              aria-hidden="true"
            />
            <p className="text-numeric text-[10px] uppercase tracking-[0.25em] text-muted-foreground mb-2">
              {monthName(month)} · Net Worth Change
            </p>
            <h3
              data-testid="monthly-review-net-worth-delta-amount"
              className={`font-serif text-[56px] leading-none font-semibold tracking-tight tabular-nums ${nwIsUp ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}
            >
              {nwIsUp ? '+' : '−'}${nwAbsDollars}<span className="text-[28px] font-light opacity-60">.{nwAbsCents}</span>
            </h3>
            <p className="mt-3 text-sm text-foreground leading-relaxed">
              <span
                data-testid="monthly-review-net-worth-delta-percent"
                className={`font-semibold ${nwIsUp ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}
              >
                {fmtPct(nwDelta.pct)}
              </span>{' '}
              vs. the prior month —{' '}
              {cashSurplus >= 0 ? (
                <>
                  driven by a{' '}
                  <span className="font-semibold">{formatCurrency(cashSurplus)} cash surplus</span>
                  {' '}at a <span className="font-semibold">{data.savings_rate.toFixed(1)}% savings rate</span>
                  {Math.abs(nonCashDelta) > 100 && (
                    <>
                      , with{' '}
                      <span className={`font-semibold ${nonCashDelta >= 0 ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}>
                        {nonCashDelta >= 0 ? '+' : '−'}{formatCurrency(Math.abs(nonCashDelta))} from market moves
                      </span>
                    </>
                  )}
                  .
                </>
              ) : (
                <>
                  despite a{' '}
                  <span className="font-semibold text-[var(--color-loss)]">{formatCurrency(Math.abs(cashSurplus))} cash shortfall</span>
                  .
                </>
              )}
            </p>

            <div className="mt-4 flex items-center gap-6 flex-wrap">
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Cash surplus</span>
                <span
                  data-testid="monthly-review-cash-surplus"
                  className={`font-serif text-base font-semibold tabular-nums ${cashSurplus >= 0 ? 'text-foreground' : 'text-[var(--color-loss)]'}`}
                >
                  {cashSurplus >= 0 ? '+' : '−'}{formatCurrency(Math.abs(cashSurplus))}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Market Δ</span>
                <span className={`font-serif text-base font-semibold tabular-nums ${nonCashDelta >= 0 ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}>
                  {nonCashDelta >= 0 ? '+' : '−'}{formatCurrency(Math.abs(nonCashDelta))}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">vs Last Month</span>
                <span className={`font-serif text-base font-semibold tabular-nums ${nwIsUp ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}>
                  {fmtPct(nwDelta.pct)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ── KPI Strip (3-up — Net Worth Δ promoted above) ───── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Income */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Income</p>
            <p className="stat-value" data-testid="monthly-review-income-total">{formatCompactCurrency(data.income.total)}</p>
            <div className="mt-2">
              <span className={data.income.mom_change_pct >= 0 ? "stat-delta-pos" : "stat-delta-neg"}>
                <span className="material-symbols-outlined text-[14px]">
                  {data.income.mom_change_pct >= 0 ? "arrow_upward" : "arrow_downward"}
                </span>
                {fmtPct(data.income.mom_change_pct)}
              </span>
              <span className="text-xs text-muted-foreground ml-2">vs prior month</span>
            </div>
          </div>

          {/* Spending */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Spending</p>
            <p className="stat-value" data-testid="monthly-review-spending-total">{formatCompactCurrency(data.spending.total)}</p>
            <div className="mt-2">
              <span className={data.spending.mom_change_pct <= 0 ? "stat-delta-pos" : "stat-delta-neg"}>
                <span className="material-symbols-outlined text-[14px]">
                  {data.spending.mom_change_pct <= 0 ? "arrow_downward" : "arrow_upward"}
                </span>
                {fmtPct(data.spending.mom_change_pct)}
              </span>
              <span className="text-xs text-muted-foreground ml-2">vs prior month</span>
            </div>
          </div>

          {/* Savings Rate */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Savings Rate</p>
            <p className="stat-value" data-testid="monthly-review-savings-rate">{data.savings_rate.toFixed(1)}%</p>
            <p className="text-xs text-muted-foreground mt-2">
              12m avg: {data.income.trailing_12m_avg > 0
                ? ((1 - data.spending.trailing_12m_avg / data.income.trailing_12m_avg) * 100).toFixed(1)
                : "0"}%
            </p>
          </div>
        </div>

        {/* ── Pre-Tax (Gross) Snapshot ─────────────────────────────── */}
        {data.pre_tax && (
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c7)]">payments</span>
              Pre-Tax (Gross) Snapshot
              <span className="text-[10px] font-normal text-muted-foreground ml-1">from myPay RAS</span>
            </h2>
            <div className="grid grid-cols-5 gap-4">
              <div>
                <p className="stat-label mb-1">Gross Income</p>
                <p className="stat-value" data-testid="monthly-review-pretax-gross-income">{formatCompactCurrency(data.pre_tax.gross_income)}</p>
              </div>
              <div>
                <p className="stat-label mb-1">Federal Tax</p>
                <p className="stat-value text-loss" data-testid="monthly-review-pretax-federal-tax">−{formatCompactCurrency(data.pre_tax.federal_tax)}</p>
              </div>
              <div>
                <p className="stat-label mb-1">State Tax</p>
                <p className="stat-value text-loss" data-testid="monthly-review-pretax-state-tax">−{formatCompactCurrency(data.pre_tax.state_tax)}</p>
              </div>
              <div>
                <p className="stat-label mb-1">Net Pay</p>
                <p className="stat-value" data-testid="monthly-review-pretax-net-pay">{formatCompactCurrency(data.pre_tax.net_pay)}</p>
              </div>
              <div>
                <p className="stat-label mb-1">Pre-Tax Savings Rate</p>
                <p className="stat-value" data-testid="monthly-review-pretax-savings-rate">{data.pre_tax.savings_rate_pct.toFixed(1)}%</p>
                <p className="text-[10px] text-muted-foreground mt-1">
                  vs net-basis {data.savings_rate.toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ── Budget Performance ───────────────────────────────────── */}
        <div className="card-l1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-[var(--primary)]">pie_chart</span>
            Budget Performance
          </h2>
          {data.budget_highlights.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">No budget data for this month</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-label border-b border-border">
                    <th className="pb-2">Category</th>
                    <th className="pb-2 text-right">Budgeted</th>
                    <th className="pb-2 text-right">Actual</th>
                    <th className="pb-2 text-right">Variance</th>
                    <th className="pb-2 text-right">% Used</th>
                  </tr>
                </thead>
                <tbody>
                  {data.budget_highlights.slice(0, 8).map((b: any) => {
                    const slug = String(b.category || 'unknown')
                      .toLowerCase()
                      .replace(/[^a-z0-9]+/g, '-')
                      .replace(/(^-|-$)/g, '') || 'unknown';
                    return (
                      <tr
                        key={b.category}
                        className={`border-b border-border ${
                          b.variance > 0 ? "bg-loss-subtle/30" : b.variance < -20 ? "bg-gain-subtle/30" : ""
                        }`}
                      >
                        <td className="py-2.5 font-medium text-foreground">{b.category}</td>
                        <td className="py-2.5 text-right text-numeric text-muted-foreground" data-testid={`monthly-review-budget-budgeted-${slug}`}>{formatCurrency(b.budgeted)}</td>
                        <td className="py-2.5 text-right text-numeric text-foreground" data-testid={`monthly-review-budget-actual-${slug}`}>{formatCurrency(b.actual)}</td>
                        <td className={`py-2.5 text-right text-numeric font-semibold ${b.variance > 0 ? "text-loss" : "text-gain"}`} data-testid={`monthly-review-budget-variance-${slug}`}>
                          {b.variance > 0 ? "+" : ""}{formatCurrency(b.variance)}
                        </td>
                        <td className="py-2.5 text-right text-numeric text-muted-foreground">{b.pct_used.toFixed(0)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Two-column: Subscriptions + Notable ─────────────────── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Subscription Changes */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--primary)]">autorenew</span>
              Subscription Changes
            </h2>
            {data.subscription_changes.length === 0 ? (
              <p className="text-sm text-muted-foreground py-4 text-center">No subscription changes this month</p>
            ) : (
              <div className="space-y-2">
                {data.subscription_changes.map((sc: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-border last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="text-foreground font-medium">{sc.merchant}</span>
                      <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded-md ${
                        sc.change_type === "new" ? "bg-gain-subtle text-gain" :
                        sc.change_type === "removed" ? "bg-muted text-muted-foreground" :
                        "bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
                      }`}>
                        {sc.change_type === "price_change" ? "Price Change" : sc.change_type}
                      </span>
                    </div>
                    {sc.delta != null && (
                      <span className={`text-numeric text-xs font-semibold ${sc.delta > 0 ? "text-loss" : "text-gain"}`}>
                        {sc.delta > 0 ? "+" : ""}{formatCurrency(sc.delta)}/mo
                      </span>
                    )}
                    {sc.new_amount != null && sc.delta == null && (
                      <span className="text-numeric text-xs text-muted-foreground">{formatCurrency(sc.new_amount)}/mo</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Notable Transactions */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--primary)]">receipt_long</span>
              Notable Transactions
            </h2>
            {data.notable_transactions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-6 text-muted-foreground">
                <span className="material-symbols-outlined text-2xl mb-2">check_circle</span>
                <p className="text-sm">No notable transactions this month</p>
                <p className="text-xs mt-1">All spending was within normal ranges</p>
              </div>
            ) : (
              <div className="space-y-2">
                {data.notable_transactions.map((tx: any, idx: number) => (
                  <div key={tx.id} className="flex items-center justify-between text-sm py-2 border-b border-border last:border-0">
                    <div className="flex-1 min-w-0 mr-3">
                      <p className="font-medium text-foreground truncate">
                        {tx.merchant || tx.description}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(tx.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        {" · "}{tx.category}
                      </p>
                    </div>
                    <span
                      data-testid={`monthly-review-notable-transaction-amount-${idx + 1}`}
                      className="text-numeric text-sm font-semibold text-foreground shrink-0"
                    >
                      {formatCurrency(tx.amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Large Transfers (inter-account movements) */}
          {(data.large_transfers?.length > 0) && (
            <div className="card-l1 p-5">
              <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--chart-c7)]">swap_horiz</span>
                Large Transfers
              </h2>
              <div className="space-y-2">
                {data.large_transfers.map((tx: any) => (
                  <div key={tx.id} className="flex items-center justify-between text-sm py-2 border-b border-border last:border-0">
                    <div className="flex-1 min-w-0 mr-3">
                      <p className="font-medium text-foreground truncate">
                        {tx.merchant || tx.description}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {new Date(tx.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        {" · "}{tx.category}
                      </p>
                    </div>
                    <span className="text-numeric text-sm font-semibold text-[var(--chart-c7)] shrink-0">
                      {formatCurrency(tx.amount)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Status Row ──────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Uncategorized */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--color-warning)]">label_off</span>
              Uncategorized
            </h3>
            {data.uncategorized_count === 0 ? (
              <p className="text-sm text-muted-foreground" data-testid="monthly-review-uncategorized-count">All transactions categorized ✓</p>
            ) : (
              <div>
                <p className="text-2xl font-bold text-[var(--color-warning)]" data-testid="monthly-review-uncategorized-count">{data.uncategorized_count}</p>
                <a href={`/transactions?filter=uncategorized`} className="text-xs text-[var(--primary)] hover:underline mt-1 inline-flex items-center gap-1">
                  Review now <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                </a>
              </div>
            )}
          </div>

          {/* Lifestyle Creep */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c3)]">show_chart</span>
              Lifestyle Creep
            </h3>
            <LifestyleCreepPanel data={lifestyleData} compact />
          </div>

          {/* Data Freshness */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c2)]">sync</span>
              Data Freshness
            </h3>
            {data.freshness.length === 0 ? (
              <p className="text-sm text-muted-foreground">No freshness data</p>
            ) : (
              <div className="space-y-1.5">
                {data.freshness.map((f: any) => {
                  // Human-readable relative time conversion
                  const formatFreshness = (hours: number | null | undefined): string => {
                    if (hours == null) return "--";
                    if (hours < 0) return "Just now";
                    if (hours < 1) return "Just now";
                    if (hours < 24) return `${Math.round(hours)}h ago`;
                    if (hours < 48) return "Yesterday";
                    const days = Math.floor(hours / 24);
                    if (days < 30) return `${days} days ago`;
                    const months = Math.floor(days / 30);
                    if (months < 12) return `${months} month${months > 1 ? 's' : ''} ago`;
                    const years = Math.floor(months / 12);
                    return `${years} year${years > 1 ? 's' : ''} ago`;
                  };
                  const label = f.status === "fresh" ? "✓ Fresh" :
                    f.status === "stale" ? `⚠ ${formatFreshness(f.hours_since_update)}` :
                    f.status === "critical" ? `✕ ${formatFreshness(f.hours_since_update)}` :
                    "No data";
                  return (
                    <div key={f.institution} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{institutionDisplayName(f.institution)}</span>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-md ${
                        f.status === "fresh" ? "bg-gain-subtle text-gain" :
                        f.status === "stale" ? "bg-[var(--color-warning)]/10 text-[var(--color-warning)]" :
                        f.status === "critical" ? "bg-loss-subtle text-loss" :
                        "bg-muted text-muted-foreground"
                      }`}>
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
