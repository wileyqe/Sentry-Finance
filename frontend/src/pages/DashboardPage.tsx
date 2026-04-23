import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { AreaChart } from "@tremor/react";
import { motion } from "framer-motion";
import { TransactionLogo } from "@/components/ui/TransactionLogo";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { useApi } from "@/lib/api";
import { useAccounts } from "@/lib/accounts";
import { useView } from "@/context/ViewContext";
import { KpiCardsSkeleton, ChartSkeleton, TransactionListSkeleton } from "@/components/Skeleton";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR as MONTH_NAMES } from "@/lib/dateUtils";
import CreditScorePopup from "@/components/CreditScorePopup";

const TIMEFRAME_MAP: Record<string, number> = {
  '1 month': 1,
  '3 months': 3,
  '6 months': 6,
  '1 year': 12,
  'All time': 120,
};

const SPENDING_TF_MAP: Record<string, string> = {
  'This month vs. last month': 'month_vs_last_month',
  'This month vs. last year': 'month_vs_last_year',
  'This month vs. average month': 'month_vs_avg_month',
  'This year vs. last year': 'year_vs_last_year',
};

const springTransition: any = {
  type: "spring",
  stiffness: 300,
  damping: 30,
};

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: { opacity: 1, y: 0, transition: springTransition },
};

export default function DashboardPage() {
  const navigate = useNavigate();
  const { accountNames } = useAccounts();
  const { view, owners } = useView();

  const [nwTimeframe, setNwTimeframe] = useSessionState('dashboard:nwTimeframe', '6 months');
  const [spendingTf, setSpendingTf] = useSessionState('dashboard:spendingTf', 'This month vs. last month');

  const creditCardRef = useRef<HTMLDivElement>(null);
  const [creditPopupOpen, setCreditPopupOpen] = useState(false);

  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const month = `${y}-${m}`;

  // Correct end-of-month date (handles Feb, short months)
  const endOfMonth = new Date(y, now.getMonth() + 1, 0);
  const endDay = String(endOfMonth.getDate()).padStart(2, '0');

  // ── Owner-scoped API calls (every fetch goes through useOwnerApi so the
  //    active owner from the top-of-page chip switcher is honored) ─────
  const { data: txData, loading: txLoading } = useOwnerApi(`/api/transactions?limit=8&exclude_transfers=true`);
  const { data: metricsData, loading: metricsLoading } = useOwnerApi(`/api/reports/summary?start_date=${y}-${m}-01&end_date=${y}-${m}-${endDay}`);
  const { data: recurringData, loading: recurringLoading } = useOwnerApi(`/api/recurring`);

  // Net worth chart — re-fetches when nwTimeframe or ownerParam changes
  const nwMonths = TIMEFRAME_MAP[nwTimeframe] || 6;
  const { data: nwHistoryData } = useOwnerApi<any>(`/api/reports/net-worth-history?months=${nwMonths}`);

  // Spending comparison chart
  const spendingTfParam = SPENDING_TF_MAP[spendingTf] || 'month_vs_last_month';
  const spendingDateStr = new Date().toISOString().split("T")[0];
  const { data: spendingComparisonData } = useOwnerApi<any>(
    `/api/reports/spending-comparison?reference_date=${spendingDateStr}&timeframe=${spendingTfParam}`
  );

  // Budget summary + budgets — household-only (V23), so we use the
  // plain useApi hook instead of useOwnerApi. The widget renders the
  // same numbers regardless of which owner the ViewSelector is on.
  const { data: budgetSummaryRaw } = useApi<any>(`/api/budgets/summary?month=${month}`);
  const { data: budgetDataRaw } = useApi<any>(`/api/budgets?month=${month}`);

  const recentTransactions = txData?.transactions || [];
  const metrics = metricsData;
  const recurringItems = recurringData?.recurring || [];

  const networthData = useMemo(() => {
    const history = (nwHistoryData?.history) || [];
    return history.map((h: any) => ({
      date: h.month,
      "Net Worth": h.net_worth,
      orig: h,
    }));
  }, [nwHistoryData]);

  const spendingData = useMemo(() => {
    const rows = spendingComparisonData?.data || [];
    let currentLabel = 'This month';
    let prevLabel = 'Last month';
    if (spendingTfParam === 'month_vs_last_year') {
      prevLabel = 'Same month last year';
    } else if (spendingTfParam === 'month_vs_avg_month') {
      prevLabel = 'Average month';
    } else if (spendingTfParam === 'year_vs_last_year') {
      currentLabel = 'This year';
      prevLabel = 'Last year';
    }
    return rows.map((d: any) => ({
      period: d.period,
      [prevLabel]: d['Previous'],
      [currentLabel]: d['Current'],
    }));
  }, [spendingComparisonData, spendingTfParam]);

  const budgetSummary = useMemo(() => {
    if (!budgetSummaryRaw) return null;
    const cats = (budgetDataRaw?.categories) || [];
    return {
      ...budgetSummaryRaw,
      total_budgeted: budgetSummaryRaw.total_budget || 0,
      categories: cats.map((b: any) => ({
        category: b.category,
        target_amount: b.target || b.target_amount || 0,
        spent: b.actual || 0,
      })),
    };
  }, [budgetSummaryRaw, budgetDataRaw]);

  // New KPI API calls
  const { data: velocityData, loading: velocityLoading } = useOwnerApi(`/api/metrics/net-worth-velocity`);
  const { data: runwayData, loading: runwayLoading } = useOwnerApi(`/api/metrics/emergency-fund`);
  const { data: creditData, loading: creditLoading } = useOwnerApi(`/api/metrics/credit-scores`);
  const { data: freshnessData } = useOwnerApi<any[]>(`/api/freshness`);

  // Calculations
  const latestNw = networthData.length > 0 ? networthData[networthData.length - 1].orig : null;
  const isKpiLoading = metricsLoading && !metrics || velocityLoading || runwayLoading || creditLoading;

  const budgetTotal = budgetSummary?.total_budgeted || 0;
  const budgetSpent = budgetSummary?.total_spent || 0;
  const budgetRemaining = budgetTotal - budgetSpent;
  const budgetPct = budgetTotal > 0 ? Math.min((budgetSpent / budgetTotal) * 100, 100) : 0;
  const budgetMonth = `${MONTH_NAMES[now.getMonth()]} ${now.getFullYear()}`;
  // Recurring total: monthly outflow only.
  // - Filter to expense rows (negative amounts) — interest credits etc. are
  //   not "monthly bills" and shouldn't be in the same line item.
  // - Normalize each row by frequency so annual subscriptions like Amazon
  //   Prime contribute amount/12, not their full $140.
  // - Display as a positive magnitude (the label is "/mo").
  const recurringTotal = (() => {
    const FREQ_DIVISOR: Record<string, number> = {
      monthly: 1, weekly: 1 / 4.33, biweekly: 1 / 2.17, quarterly: 3,
      'semi-annual': 6, annual: 12, yearly: 12,
    };
    let monthly = 0;
    for (const r of recurringItems) {
      const raw = r.expected_amount ?? r.last_amount ?? 0;
      if (raw >= 0) continue; // skip income / interest credits
      const div = FREQ_DIVISOR[(r.frequency || 'monthly').toLowerCase()] ?? 1;
      monthly += Math.abs(raw) / div;
    }
    return Math.round(monthly);
  })();

  const fmtChart = (n: number) => formatCurrency(n);

  // Savings rate
  const totalIncome = metrics?.total_income || 0;
  const totalSpending = metrics?.total_spending || 0;
  const totalNet = metrics?.net || 0;
  const savingsRate = totalIncome > 0 ? (totalNet / totalIncome) * 100 : 0;
  const hasMonthData = totalIncome > 0 || totalSpending > 0;

  // Freshness
  const globalFreshnessHours = freshnessData && freshnessData.length > 0
    ? Math.min(...freshnessData.map((f: any) => f.hours_since_update))
    : null;
  const freshnessLabel = globalFreshnessHours !== null
    ? (globalFreshnessHours < 24 ? 'Updated today' : globalFreshnessHours < 72 ? `Updated ${Math.floor(globalFreshnessHours / 24)}d ago` : 'Update needed')
    : 'Syncing...';
  const freshnessColor = globalFreshnessHours !== null
    ? (globalFreshnessHours < 24 ? 'text-emerald-500' : globalFreshnessHours < 72 ? 'text-amber-500' : 'text-rose-500')
    : 'text-slate-400';

  // ── Spending "editorial hero" stats ──────────────────────────────
  const daysElapsed = now.getDate();
  const daysInMonth = endOfMonth.getDate();
  const perDay = daysElapsed > 0 ? totalSpending / daysElapsed : 0;
  const projectedEom = perDay * daysInMonth;

  const spendingRows: any[] = spendingComparisonData?.data || [];
  const prevTotal = (() => {
    for (let i = spendingRows.length - 1; i >= 0; i--) {
      const v = spendingRows[i]?.Previous;
      if (v != null && v > 0) return v;
    }
    return 0;
  })();
  const spendDelta = totalSpending - prevTotal;
  const spendDeltaPct = prevTotal > 0 ? (spendDelta / prevTotal) * 100 : 0;
  const spendDeltaIsUp = spendDelta > 0;

  const tfParam = SPENDING_TF_MAP[spendingTf];
  const spendCurrentLabel = tfParam === 'year_vs_last_year' ? 'This year' : 'This month';
  const spendPrevLabel =
    tfParam === 'month_vs_last_year' ? 'Same month last year' :
    tfParam === 'month_vs_avg_month' ? 'Average month' :
    tfParam === 'year_vs_last_year' ? 'Last year' :
    'Last month';
  const comparisonNarrative =
    tfParam === 'month_vs_last_year' ? 'vs. the same month last year' :
    tfParam === 'month_vs_avg_month' ? 'vs. an average month' :
    tfParam === 'year_vs_last_year' ? 'vs. last year-to-date' :
    'from last month';

  const monthName = now.toLocaleString('en-US', { month: 'long' });
  const monthOrdinal = String(now.getMonth() + 1).padStart(2, '0');

  const totalParts = formatCurrency(totalSpending).replace('$', '').split('.');
  const totalDollars = totalParts[0] || '0';
  const totalCents = totalParts[1] || '00';

  // ── Net Worth "editorial hero" stats ─────────────────────────────
  const nwFirst = networthData.length > 0 ? (networthData[0]?.orig?.net_worth ?? 0) : 0;
  const nwLatest = latestNw?.net_worth ?? 0;
  const nwDelta = nwLatest - nwFirst;
  const nwDeltaPct = nwFirst > 0 ? (nwDelta / nwFirst) * 100 : 0;
  const nwWindowMonths = Math.max(1, networthData.length - 1);
  const nwVelocity = nwDelta / nwWindowMonths;
  const nwDeltaIsUp = nwDelta >= 0;

  const nwParts = formatCurrency(nwLatest).replace('$', '').split('.');
  const nwDollars = nwParts[0] || '0';
  const nwCents = nwParts[1] || '00';

  const sparkPoints: number[] = spendingData.map((d: any) => d[spendCurrentLabel] || 0);
  const sparkMax = Math.max(1, ...sparkPoints);
  const sparkPath = sparkPoints
    .map((y: number, i: number) => {
      const x = sparkPoints.length <= 1 ? 0 : (i / (sparkPoints.length - 1)) * 220;
      const yPos = 22 - (y / sparkMax) * 18;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${yPos.toFixed(1)}`;
    })
    .join(' ');

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 overflow-auto custom-scrollbar px-12 py-8 space-y-12"
    >

      {/* Top Snapshot Cards */}
      {isKpiLoading ? (
        <KpiCardsSkeleton />
      ) : (
        <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Net Worth */}
          <motion.div
            className="card-l1 p-6 relative overflow-hidden group cursor-pointer"
            onClick={() => navigate('/accounts')}
          >
            <div className="flex items-center justify-between mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">account_balance</span>
                Net Worth
              </span>
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full bg-current ${freshnessColor}`}></span>
                <span className="text-[10px] font-medium text-slate-500 dark:text-slate-400">{freshnessLabel}</span>
              </div>
            </div>
            <p className="text-4xl font-bold tracking-tight text-slate-900 dark:text-slate-100 mb-2 text-numeric">
              {formatCurrency(latestNw?.net_worth)}
            </p>
            <div className="flex items-center gap-2 mt-auto">
              <div className={`flex items-center gap-1 text-sm font-semibold ${velocityData?.mom_pct >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                <span aria-hidden="true" className="material-symbols-outlined text-[16px]">
                  {velocityData?.mom_pct >= 0 ? 'trending_up' : 'trending_down'}
                </span>
                <span>{Math.abs(velocityData?.mom_pct || 0)}%</span>
              </div>
              <span className="text-xs text-slate-400 dark:text-slate-500">this month</span>
            </div>
          </motion.div>

          {/* Cash Flow & Savings Rate */}
          <motion.div
            className="card-l1 p-6 relative overflow-hidden group cursor-pointer"
            onClick={() => navigate('/cash-flow')}
          >
            <div className="flex items-center gap-2 mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">swap_vert</span>
                Monthly Net Flow
              </span>
            </div>
            {hasMonthData ? (
              <>
                <p className={`text-4xl font-bold tracking-tight mb-2 text-numeric ${totalNet >= 0 ? 'text-emerald-600 dark:text-emerald-500' : 'text-rose-600 dark:text-rose-500'}`}>
                  {totalNet >= 0 ? '+' : ''}{formatCurrency(totalNet)}
                </p>
                <div className="flex items-center gap-2 mt-auto">
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800/50 text-xs font-medium text-slate-600 dark:text-slate-300">
                    <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-indigo-500">savings</span>
                    {savingsRate.toFixed(1)}% Savings Rate
                  </div>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-start gap-2 mt-2">
                <p className="text-2xl font-bold text-slate-300 dark:text-slate-600">--</p>
                <span className="text-xs text-slate-400 dark:text-slate-500">No data for this period</span>
              </div>
            )}
          </motion.div>

          {/* Emergency Fund Runway */}
          <motion.div
            className="card-l1 p-6 relative overflow-hidden group cursor-pointer"
            onClick={() => navigate('/cash-flow')}
          >
            <div className="flex items-center gap-2 mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">health_and_safety</span>
                Runway
              </span>
            </div>
            <div className="flex items-baseline gap-2 mb-2">
              <p className="text-4xl font-bold tracking-tight text-slate-900 dark:text-slate-100 text-numeric">
                {runwayData?.months_of_runway !== null ? runwayData?.months_of_runway : '—'}
              </p>
              <span className="text-slate-500 dark:text-slate-400 font-medium">months</span>
            </div>
            <div className="flex items-center gap-2 mt-auto">
              <span className="text-xs text-slate-400 dark:text-slate-500">
                Based on {formatCurrency(runwayData?.avg_monthly_spending)}/mo avg spend
              </span>
            </div>
          </motion.div>

          {/* Credit Scores — owner-grouped in household view, single column otherwise */}
          <motion.div
            ref={creditCardRef}
            className="card-l1 p-6 relative overflow-hidden flex flex-col cursor-pointer"
            onClick={() => setCreditPopupOpen(true)}
          >
            <div className="flex items-center gap-2 mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">speed</span>
                Credit Scores
              </span>
            </div>

            {(() => {
              const allScores = creditData?.latest || [];

              // Bucket scores by owner_id (lowercased; null becomes "")
              const byOwner: Record<string, any[]> = {};
              for (const s of allScores) {
                const key = (s.owner_id || '').toLowerCase();
                if (!byOwner[key]) byOwner[key] = [];
                byOwner[key].push(s);
              }

              // Score color tier — shared between layouts.
              const colorFor = (n: number) =>
                n >= 750
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : n >= 700
                  ? 'text-indigo-600 dark:text-indigo-400'
                  : 'text-amber-600 dark:text-amber-500';

              // Compact pill — used inside per-owner columns when the
              // household view splits the card in two.
              const renderCompactPill = (score: any, key: string) => {
                const inst = score.institution_id ? institutionDisplayName(score.institution_id) : '';
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-md bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800/60 min-w-0"
                  >
                    <div className="flex flex-col min-w-0">
                      <span className="text-[10px] font-semibold text-slate-600 dark:text-slate-300 truncate">
                        {inst || score.source}
                      </span>
                      <span className="text-[9px] text-slate-400 dark:text-slate-500 truncate">
                        {score.source} · {score.score_type}
                      </span>
                    </div>
                    <span className={`text-base font-bold font-mono tracking-tight ${colorFor(score.score)}`}>
                      {score.score}
                    </span>
                  </div>
                );
              };

              // Roomy single-column pill — used when only one owner is in scope.
              const renderFullPill = (score: any, key: string, showInst: boolean) => {
                const inst = score.institution_id ? institutionDisplayName(score.institution_id) : '';
                const label = showInst && inst ? `${inst} ${score.score_type}` : score.score_type;
                const sublabel = showInst && inst ? score.source : `${score.source}`;
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800"
                  >
                    <div className="flex flex-col">
                      <span className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        {sublabel}
                      </span>
                      <span className="text-[10px] text-slate-400 dark:text-slate-500">{label}</span>
                    </div>
                    <span className={`text-xl font-bold font-mono tracking-tight ${colorFor(score.score)}`}>
                      {score.score}
                    </span>
                  </div>
                );
              };

              // ── Household view: split into one column per configured owner.
              //    The card always reserves room for every owner so an empty
              //    second person reads as "we have a slot for them" rather
              //    than "this card is broken".
              if (view === 'ours') {
                // Primary owner first, others alphabetically. When more
                // owners are added later this still produces a stable order.
                const ordered = owners.slice().sort((a, b) => {
                  if (a.id === 'quintin') return -1;
                  if (b.id === 'quintin') return 1;
                  return a.display_name.localeCompare(b.display_name);
                });
                const sections = ordered.map((o) => ({
                  id: o.id,
                  name: o.display_name,
                  scores: byOwner[o.id.toLowerCase()] || [],
                }));
                // Surface legacy rows that lack an owner_id rather than dropping them.
                const orphans = byOwner[''] || [];
                if (orphans.length > 0) {
                  sections.push({ id: '_orphan', name: 'Unassigned', scores: orphans });
                }

                if (sections.length === 0 || sections.every((s) => s.scores.length === 0)) {
                  return <div className="text-sm text-slate-400 italic mt-1">No scores available</div>;
                }

                const cols = sections.length === 2 ? 'grid-cols-2' : sections.length === 1 ? 'grid-cols-1' : 'grid-cols-3';

                return (
                  <div className={`grid ${cols} gap-3 mt-1`}>
                    {sections.map((section) => (
                      <div key={section.id} className="flex flex-col gap-1.5 min-w-0">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                          {section.name}
                        </span>
                        {section.scores.length === 0 ? (
                          <div className="flex items-center justify-center px-2 py-1.5 rounded-md border border-dashed border-slate-200 dark:border-slate-800 text-[10px] italic text-slate-400 dark:text-slate-500">
                            No scores yet
                          </div>
                        ) : (
                          section.scores
                            .slice(0, 2)
                            .map((s: any, i: number) =>
                              renderCompactPill(s, `${section.id}-${s.institution_id || s.source}-${i}`)
                            )
                        )}
                      </div>
                    ))}
                  </div>
                );
              }

              // ── Owner-specific view: single-column, full-size pills.
              //    The active chip already tells the user whose scores
              //    these are, so no per-owner header is needed.
              const ownerScores = byOwner[view.toLowerCase()] || [];
              if (ownerScores.length === 0) {
                return <div className="text-sm text-slate-400 italic mt-1">No scores available</div>;
              }
              const bureauCounts: Record<string, number> = {};
              ownerScores.forEach((s: any) => {
                const k = `${s.source}-${s.score_type}`;
                bureauCounts[k] = (bureauCounts[k] || 0) + 1;
              });
              const hasDupes = Object.values(bureauCounts).some((c) => c > 1);
              const showInst = hasDupes || ownerScores.length > 2;

              return (
                <div className="flex flex-col gap-3 mt-1">
                  {ownerScores
                    .slice(0, 4)
                    .map((s: any, i: number) =>
                      renderFullPill(s, `${s.institution_id || s.source}-${s.score_type}-${i}`, showInst)
                    )}
                </div>
              );
            })()}
          </motion.div>
        </motion.div>
      )}

      <CreditScorePopup
        open={creditPopupOpen}
        onClose={() => setCreditPopupOpen(false)}
        anchorRef={creditCardRef}
      />

      {/* Main Charts Section */}
      <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* Net Worth — editorial hero header */}
        <div className="flex flex-col h-[320px]">
          <div className="mb-4 pb-4 border-b border-border shrink-0 h-[84px]">
            <div className="relative pl-5 h-full flex flex-col justify-between">
              <span
                className={`absolute left-0 top-0 bottom-0 w-[3px] rounded-full ${nwDeltaIsUp ? 'bg-[var(--color-gain)]' : 'bg-[var(--color-loss)]'}`}
                aria-hidden="true"
              ></span>

              <div className="flex items-center justify-between gap-4">
                <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">
                  No. {monthOrdinal} — {monthName} · Net Worth
                </p>
                <div className="relative flex items-center gap-1.5">
                  <select
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    value={nwTimeframe}
                    onChange={(e) => setNwTimeframe(e.target.value)}
                  >
                    {Object.keys(TIMEFRAME_MAP).map(tf => (
                      <option key={tf} value={tf}>{tf}</option>
                    ))}
                  </select>
                  <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400 pointer-events-none underline underline-offset-4 decoration-dotted">
                    {nwTimeframe}
                  </span>
                  <span aria-hidden="true" className="material-symbols-outlined text-slate-400 text-sm leading-none pointer-events-none">expand_more</span>
                </div>
              </div>

              <div className="flex items-baseline gap-3 flex-wrap">
                <h3 className="font-serif text-[40px] leading-none font-semibold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">
                  ${nwDollars}<span className="text-[22px] text-slate-400 dark:text-slate-500 font-light">.{nwCents}</span>
                </h3>
                {networthData.length > 1 && (
                  <span className={`text-xs font-semibold tabular-nums ${nwDeltaIsUp ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}>
                    {nwDeltaIsUp ? '▲' : '▼'} {nwDeltaIsUp ? '+' : ''}{formatCurrency(nwDelta)} ({nwDeltaIsUp ? '+' : ''}{nwDeltaPct.toFixed(1)}%) · {formatCurrency(nwVelocity)}/mo pace
                  </span>
                )}
              </div>
            </div>
          </div>
          {networthData.length > 0 ? (
            <div className="flex-1 w-full min-h-0 -ml-4">
              <AreaChart
                className="h-full"
                data={networthData}
                index="date"
                categories={['Net Worth']}
                colors={['emerald']}
                valueFormatter={fmtChart}
                showLegend={false}
                showGridLines={false}
                showYAxis={true}
                yAxisWidth={95}
                curveType="monotone"
              />
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <ChartSkeleton className="w-full h-full" />
            </div>
          )}
        </div>

        {/* Cumulative Spending — editorial hero */}
        <div className="flex flex-col h-[320px] overflow-hidden">
          <div className="relative flex-1 pl-5 flex flex-col">
            <span className="absolute left-0 top-1 bottom-1 w-[3px] bg-[var(--color-loss)] rounded-full" aria-hidden="true"></span>

            <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400">
              No. {monthOrdinal} — {monthName} · Spending
            </p>

            <h3 className="mt-2 font-serif text-[56px] leading-none font-semibold tracking-tight text-slate-900 dark:text-slate-100 tabular-nums">
              ${totalDollars}<span className="text-[28px] text-slate-400 dark:text-slate-500 font-light">.{totalCents}</span>
            </h3>

            {hasMonthData ? (
              <p className="mt-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                <span className={`font-semibold ${spendDeltaIsUp ? 'text-[var(--color-loss)]' : 'text-[var(--color-gain)]'}`}>
                  {spendDeltaIsUp ? 'Up' : 'Down'} {formatCurrency(Math.abs(spendDelta))} ({Math.abs(spendDeltaPct).toFixed(1)}%)
                </span>{' '}
                {comparisonNarrative}, {daysElapsed} days in — pace suggests landing near{' '}
                <span className="font-semibold text-numeric">{formatCurrency(projectedEom)}</span> by month-end.
              </p>
            ) : (
              <p className="mt-3 text-sm text-slate-400">No spending recorded this month yet.</p>
            )}

            <div className="mt-4 flex items-center gap-6 flex-wrap">
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Per day</span>
                <span className="font-serif text-base font-semibold tabular-nums text-slate-900 dark:text-slate-100">{formatCurrency(perDay)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{spendPrevLabel}</span>
                <span className="font-serif text-base font-semibold tabular-nums text-slate-500 dark:text-slate-400">{formatCurrency(prevTotal)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Projected</span>
                <span className={`font-serif text-base font-semibold tabular-nums ${spendDeltaIsUp ? 'text-[var(--color-loss)]' : 'text-[var(--color-gain)]'}`}>
                  {formatCurrency(projectedEom)}
                </span>
              </div>
            </div>

            <div className="mt-auto pt-4 border-t border-border flex items-center justify-between">
              {sparkPoints.length > 0 ? (
                <svg viewBox="0 0 220 24" className="h-6 w-[220px]" role="img" aria-label="Cumulative spend sparkline">
                  <path d={sparkPath} fill="none" stroke="var(--color-loss)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                <span className="h-6 w-[220px]"></span>
              )}
              <div className="relative flex items-center gap-1.5">
                <select
                  className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  value={spendingTf}
                  onChange={(e) => setSpendingTf(e.target.value)}
                >
                  {Object.keys(SPENDING_TF_MAP).map(tf => (
                    <option key={tf} value={tf}>{tf}</option>
                  ))}
                </select>
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500 dark:text-slate-400 pointer-events-none underline underline-offset-4 decoration-dotted">
                  {spendingTf}
                </span>
                <span aria-hidden="true" className="material-symbols-outlined text-slate-400 text-sm leading-none pointer-events-none">expand_more</span>
              </div>
            </div>
          </div>
        </div>
      </motion.div>

      <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-3 gap-12 pt-8">

        {/* Transactions Mini */}
        <div className="col-span-1 lg:col-span-2 flex flex-col">
          <div className="pb-4 mb-4 border-b border-border flex items-center justify-between">
            <h3 className="text-label">Recent Transactions</h3>
            <button
              className="text-label text-slate-400 hover:text-[var(--color-gain)] transition-colors"
              onClick={() => navigate('/transactions')}
            >View All</button>
          </div>
          {txLoading && recentTransactions.length === 0 ? (
            <TransactionListSkeleton />
          ) : (
            <div className="flex-1 overflow-auto">
              {recentTransactions.length === 0 && !txLoading ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <span aria-hidden="true" className="material-symbols-outlined text-3xl text-slate-300 dark:text-slate-600 mb-3">receipt_long</span>
                  <p className="text-sm text-slate-400">No transactions yet</p>
                </div>
              ) : (
                recentTransactions.map((tx: any) => (
                  <motion.div
                    whileHover={{ x: 4, backgroundColor: 'rgba(16, 185, 129, 0.05)' }}
                    key={tx.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Open ${tx.merchant || tx.description || 'transaction'}`}
                    className="py-4 border-b border-slate-100 dark:border-slate-800/50 flex items-center justify-between cursor-pointer group focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 rounded-md"
                    onClick={() => navigate('/transactions', { state: { selectedTxId: tx.id } })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        navigate('/transactions', { state: { selectedTxId: tx.id } });
                      }
                    }}
                  >
                    <div className="flex items-center gap-3">
                      <TransactionLogo merchantName={tx.merchant || tx.description || 'Unknown'} size="md" />
                      <div className="flex flex-col min-w-0">
                        <h4 title={tx.merchant || tx.description} className="font-bold text-sm text-slate-900 dark:text-slate-100 truncate max-w-[200px]">
                          {tx.merchant || tx.description}
                        </h4>
                        {tx.merchant && tx.description && tx.merchant !== tx.description && (
                          <span title={tx.description} className="text-xs text-slate-500 dark:text-slate-400 truncate max-w-[200px]">
                            {tx.description}
                          </span>
                        )}
                        <p className="text-[11px] font-medium text-slate-400 mt-0.5">
                          {tx.category} • {accountNames[tx.account_id] || tx.account_id}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className={`text-sm text-numeric ${(tx.signed_amount ?? tx.amount) < 0 ? 'text-slate-500' : 'text-gain'}`}>
                        {(tx.signed_amount ?? tx.amount) >= 0 ? '+' : ''}{formatCurrency(tx.signed_amount ?? tx.amount)}
                      </span>
                      <span aria-hidden="true" className="material-symbols-outlined text-slate-300 dark:text-slate-700 text-sm group-hover:text-emerald-500 transition-colors">arrow_forward</span>
                    </div>
                  </motion.div>
                ))
              )}
            </div>
          )}
        </div>

        {/* Right side stack */}
        <div className="col-span-1 flex flex-col gap-12">

          {/* Budget Widget */}
          <div
            role="button"
            tabIndex={0}
            aria-label="Open Budgets page"
            className="w-full cursor-pointer group focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 rounded-md"
            onClick={() => navigate('/budgets')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                navigate('/budgets');
              }
            }}
          >
            <div className="pb-4 mb-4 border-b border-border flex items-center justify-between">
              <h3 className="text-label">Current Budget</h3>
              <span className="text-label text-slate-400">{budgetMonth}</span>
            </div>

            <div className="mb-6">
              <p className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 mb-2">{formatCurrency(budgetSpent)}</p>
              <div
                className="w-full bg-slate-100 dark:bg-slate-800 h-1 overflow-hidden relative"
                role="progressbar"
                aria-label="Budget spent this month"
                aria-valuenow={Math.round(budgetPct)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${budgetPct}%` }}
                  transition={{ duration: 1, ease: "easeOut" }}
                  className="bg-slate-900 dark:bg-slate-300 h-full absolute top-0 left-0"
                />
              </div>
              <div className="flex justify-between mt-3 text-label">
                <span>Total: {formatCurrency(budgetTotal)}</span>
                <span>{formatCurrency(budgetRemaining)} remaining</span>
              </div>
            </div>

            {budgetSummary?.categories && (
              <div className="space-y-4 mt-6">
                {budgetSummary.categories.slice(0, 4).map((cat: any) => {
                  const pct = cat.target_amount > 0 ? Math.min((cat.spent / cat.target_amount) * 100, 100) : 0;
                  return (
                    <motion.div
                      whileHover={{ x: 2 }}
                      key={cat.category}
                      className="flex items-center gap-4 cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/budgets?category=${encodeURIComponent(cat.category)}`);
                      }}
                    >
                      <span title={cat.category} className="text-sm font-bold text-slate-900 dark:text-slate-100 w-32 truncate">{cat.category}</span>
                      <div className="flex-1 bg-slate-100 dark:bg-slate-800 h-[2px] overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 1, ease: "easeOut" }}
                          className={`h-full ${pct > 90 ? 'bg-[var(--color-loss)]' : 'bg-[var(--color-gain)]'}`}
                        />
                      </div>
                      <span className="text-xs font-mono tracking-widest text-slate-500 w-10 text-right">{pct.toFixed(0)}%</span>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Recurring Widget */}
          <div className="flex-1 flex flex-col">
             <div className="pb-4 mb-4 border-b border-border flex items-center justify-between">
              <h3 className="text-label">Recurring</h3>
              <span className="text-label text-slate-400">{formatCurrency(recurringTotal)} /mo</span>
            </div>
            <div className="flex-1 overflow-auto">
              {(() => {
                // Recurring widget shows monthly bills only — exclude
                // positive-amount rows (interest credits, recurring
                // income) so the list matches the /mo header which is
                // also outflows-only.
                const recurringBills = recurringItems.filter(
                  (item: any) => (item.expected_amount ?? item.last_amount ?? 0) < 0
                );
                if (recurringBills.length === 0 && !recurringLoading) {
                  return (
                    <div className="flex flex-col items-center justify-center py-8 text-center">
                      <span aria-hidden="true" className="material-symbols-outlined text-2xl text-slate-300 dark:text-slate-600 mb-2">event_repeat</span>
                      <p className="text-sm text-slate-400">No recurring bills detected</p>
                    </div>
                  );
                }
                return recurringBills.slice(0, 5).map((item: any) => {
                  return (
                    <motion.div
                      whileHover={{ x: 4 }}
                      key={item.id}
                      className="py-3 flex items-center justify-between cursor-pointer group"
                      onClick={() => navigate(`/transactions?recurring=true&merchant=${encodeURIComponent(item.merchant)}`)}
                    >
                      <div>
                        <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">{item.merchant}</h4>
                        <p className="text-label text-slate-400 mt-1">{item.frequency}</p>
                      </div>
                      <div className="text-right">
                        <p className="font-mono text-sm tracking-widest">{formatCurrency(item.expected_amount || item.last_amount || 0)}</p>
                        <p className="text-label text-slate-400 mt-1">
                          {item.next_expected ? new Date(item.next_expected).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}
                        </p>
                      </div>
                    </motion.div>
                  );
                });
              })()}
            </div>
          </div>

        </div>
      </motion.div>

    </motion.div>
  );
}
