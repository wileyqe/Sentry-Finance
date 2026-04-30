import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { rechartsAxisTickStyle, rechartsTooltipItemStyle, rechartsTooltipLabelStyle, rechartsTooltipStyle } from "@/lib/chartStyle";
import { AnimatePresence, motion } from "framer-motion";
import { TransactionLogo } from "@/components/ui/TransactionLogo";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { useApi } from "@/lib/api";
import { useAccounts } from "@/lib/accounts";
import { useView } from "@/context/ViewContext";
import { useRuntimeContext } from "@/context/RuntimeContext";
import { KpiCardsSkeleton, ChartSkeleton, TransactionListSkeleton } from "@/components/Skeleton";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR as MONTH_NAMES, monthKeyFromDate, monthWindowFromDate, parseIsoDateLocal } from "@/lib/dateUtils";
import CreditScorePopup from "@/components/CreditScorePopup";
import SyntheticBadge from "@/components/ui/SyntheticBadge";

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

const testIdPart = (value: unknown) =>
  String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";

const creditScoreTestId = (score: any) =>
  `dashboard-credit-score-${testIdPart(score.institution_id || score.source)}-${testIdPart(score.score_type)}`;

export default function DashboardPage() {
  const navigate = useNavigate();
  const { accountNames, accounts } = useAccounts();
  const { view, owners } = useView();
  const { referenceDate, ready: runtimeReady } = useRuntimeContext();
  const hasAnySynthetic = useMemo(
    () => accounts.some((a) => !!a.is_synthetic),
    [accounts],
  );
  const accountIsSynthetic = useMemo(() => {
    const m = new Map<string, boolean>();
    for (const a of accounts) m.set(a.id, !!a.is_synthetic);
    return m;
  }, [accounts]);

  const [nwTimeframe, setNwTimeframe] = useSessionState('dashboard:nwTimeframe', '6 months');
  const [spendingTf, setSpendingTf] = useSessionState('dashboard:spendingTf', 'This month vs. last month');

  const creditCardRef = useRef<HTMLDivElement>(null);
  const [creditPopupOpen, setCreditPopupOpen] = useState(false);

  const referenceDay = useMemo(() => parseIsoDateLocal(referenceDate), [referenceDate]);
  const month = useMemo(() => monthKeyFromDate(referenceDay), [referenceDay]);
  const monthWindow = useMemo(() => monthWindowFromDate(referenceDay), [referenceDay]);
  const endOfMonth = useMemo(
    () => parseIsoDateLocal(monthWindow.end),
    [monthWindow.end],
  );

  // ── Owner-scoped API calls (every fetch goes through useOwnerApi so the
  //    active owner from the top-of-page chip switcher is honored) ─────
  const { data: txData, loading: txLoading, error: txError } = useOwnerApi(`/api/transactions?limit=8&exclude_transfers=true`);
  const { data: metricsData, loading: metricsLoading, error: metricsError } = useOwnerApi(
    runtimeReady ? `/api/reports/summary?start_date=${monthWindow.start}&end_date=${monthWindow.end}` : null,
    { skip: !runtimeReady },
  );
  const { data: recurringData, loading: recurringLoading } = useOwnerApi(`/api/recurring`);

  // Net worth chart — re-fetches when nwTimeframe or ownerParam changes
  const nwMonths = TIMEFRAME_MAP[nwTimeframe] || 6;
  const { data: nwHistoryData, error: nwHistoryError } = useOwnerApi<any>(`/api/reports/net-worth-history?months=${nwMonths}`);

  // Spending comparison chart
  const spendingTfParam = SPENDING_TF_MAP[spendingTf] || 'month_vs_last_month';
  const { data: spendingComparisonData } = useOwnerApi<any>(
    runtimeReady ? `/api/reports/spending-comparison?reference_date=${referenceDate}&timeframe=${spendingTfParam}` : null,
    { skip: !runtimeReady },
  );

  // Budget summary + budgets — household-only (V23), so we use the
  // plain useApi hook instead of useOwnerApi. The widget renders the
  // same numbers regardless of which owner the ViewSelector is on.
  const { data: budgetSummaryRaw, error: budgetSummaryError } = useApi<any>(
    runtimeReady ? `/api/budgets/summary?month=${month}` : null,
    { skip: !runtimeReady },
  );
  const { data: budgetDataRaw, error: budgetDataError } = useApi<any>(
    runtimeReady ? `/api/budgets?month=${month}` : null,
    { skip: !runtimeReady },
  );

  // Fan-in of the errors that can leave the Dashboard rendering with
  // undefined slices. Surfaced as a banner rather than blocking the
  // page so other widgets keep working; users who dismiss it still
  // see the zero/empty fallbacks downstream.
  const firstError = txError || metricsError || nwHistoryError || budgetSummaryError || budgetDataError;

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
  // DTI: trailing 12 months; the pill displays the most recent month with status color.
  const { data: dtiSeriesData } = useOwnerApi<Array<{
    month: string;
    debt_payments: number;
    gross_income: number;
    dti_ratio: number | null;
    status: "healthy" | "moderate" | "high" | "critical" | null;
  }>>(`/api/metrics/dti?months=12`);
  const latestDti = Array.isArray(dtiSeriesData) && dtiSeriesData.length > 0
    ? dtiSeriesData[dtiSeriesData.length - 1]
    : null;
  const dtiPillStyle = (() => {
    if (!latestDti?.status) return null;
    const map = {
      healthy:  { color: "var(--color-gain)",    bg: "color-mix(in oklch, var(--color-gain) 12%, transparent)" },
      moderate: { color: "var(--color-warning)", bg: "color-mix(in oklch, var(--color-warning) 14%, transparent)" },
      high:     { color: "var(--color-warning)", bg: "color-mix(in oklch, var(--color-warning) 22%, transparent)" },
      critical: { color: "var(--color-loss)",    bg: "color-mix(in oklch, var(--color-loss) 14%, transparent)" },
    } as const;
    return map[latestDti.status];
  })();
  // PR4: net debt change pill on the Monthly Net Flow card. Pulls the most
  // recent month from the rolling cash-flow endpoint (already used in the
  // Cash Flow page; cheap re-use, no extra DB load with the v40 index).
  const { data: rollingCashFlowData } = useOwnerApi<{ months: Array<{
    year: number; month: number; net_debt_change?: number;
  }> }>(`/api/cash-flow/monthly-rolling`);
  const latestNetDebtChange = (() => {
    const months = rollingCashFlowData?.months;
    if (!months || months.length === 0) return null;
    const latest = months[months.length - 1];
    return typeof latest.net_debt_change === "number" ? latest.net_debt_change : null;
  })();

  // Net-worth breakdown snapshot — powers the expandable Details on the NW card.
  const { data: accountsPayload } = useOwnerApi<{
    accounts: any[];
    manual_assets?: { real_estate: any[]; vehicles: any[] };
  }>(`/api/accounts`);
  const [nwDetailsOpen, setNwDetailsOpen] = useState(false);

  const nwBreakdown = useMemo(() => {
    const raw = accountsPayload?.accounts || [];
    const re = accountsPayload?.manual_assets?.real_estate || [];
    const veh = accountsPayload?.manual_assets?.vehicles || [];

    const sum = (rows: any[]) => rows.reduce((s, r) => s + (r.balance || 0), 0);

    const cashAccounts = raw.filter(a => ['checking', 'savings'].includes(a.type));
    const cashFromHoldings = raw.reduce((s, a) => s + (a.investment_cash || 0), 0);

    // Investments: holdings_value split out (so cash-in-brokerage doesn't
    // double-count with Cash). Falls back to full balance for legacy rows.
    const invAccounts = raw.filter(a => ['investment', 'retirement'].includes(a.type));
    const investmentsTotal = invAccounts.reduce((s, a) => {
      const eq = a.holdings_value;
      return s + (typeof eq === 'number' ? eq : (a.balance || 0));
    }, 0);

    const realEstateTotal = re.reduce((s, r) => s + (r.estimated_value || 0), 0);
    const vehiclesTotal = veh.reduce((s, v) => s + (v.latest_value || 0), 0);

    const creditCards = raw.filter(a => ['credit_card', 'credit'].includes(a.type));
    const loans = raw.filter(a => ['loan', 'mortgage'].includes(a.type));
    const bnpl = raw.filter(a => a.type === 'bnpl');
    const absSum = (rows: any[]) => Math.abs(rows.reduce((s, r) => s + (r.balance || 0), 0));

    const assets = {
      Cash: sum(cashAccounts) + cashFromHoldings,
      Investments: investmentsTotal,
      'Real Estate': realEstateTotal,
      Vehicles: vehiclesTotal,
    };
    const liabilities = {
      'Credit Cards': absSum(creditCards),
      Loans: absSum(loans),
      BNPL: absSum(bnpl),
    };
    const totalAssets = Object.values(assets).reduce((s, v) => s + v, 0);
    const totalLiabilities = Object.values(liabilities).reduce((s, v) => s + v, 0);
    return {
      assets,
      liabilities,
      totalAssets,
      totalLiabilities,
      netWorth: totalAssets - totalLiabilities,
    };
  }, [accountsPayload]);

  const NW_BUCKET_COLORS: Record<string, string> = {
    Cash: 'var(--chart-c1)',
    Investments: 'var(--chart-c2)',
    'Real Estate': 'var(--chart-c3)',
    Vehicles: 'var(--chart-c4)',
    'Credit Cards': 'var(--chart-c5)',
    Loans: 'var(--chart-c6)',
    BNPL: 'var(--chart-c7)',
  };

  // Calculations
  const latestNw = networthData.length > 0 ? networthData[networthData.length - 1].orig : null;
  const isKpiLoading = !runtimeReady || (metricsLoading && !metrics) || velocityLoading || runwayLoading || creditLoading;

  const budgetTotal = budgetSummary?.total_budgeted || 0;
  const budgetSpent = budgetSummary?.total_spent || 0;
  const budgetRemaining = budgetTotal - budgetSpent;
  const budgetPct = budgetTotal > 0 ? Math.min((budgetSpent / budgetTotal) * 100, 100) : 0;
  const budgetMonth = `${MONTH_NAMES[referenceDay.getMonth()]} ${referenceDay.getFullYear()}`;
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
    ? (globalFreshnessHours < 24 ? 'text-gain' : globalFreshnessHours < 72 ? 'text-[var(--color-warning)]' : 'text-loss')
    : 'text-muted-foreground';

  // ── Spending "editorial hero" stats ──────────────────────────────
  const daysElapsed = referenceDay.getDate();
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

  const monthName = referenceDay.toLocaleString('en-US', { month: 'long' });
  const monthOrdinal = String(referenceDay.getMonth() + 1).padStart(2, '0');

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

      {firstError && (
        <div
          role="alert"
          className="-mx-2 px-4 py-3 rounded-xl border border-[var(--color-loss)]/30 bg-loss-subtle text-loss flex items-center gap-3"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[18px]">error</span>
          <div className="text-sm">
            Some Dashboard data failed to load ({firstError.message || 'unknown error'}).
            Other widgets may show stale or empty values.
          </div>
        </div>
      )}

      {/* Top Snapshot Cards */}
      {isKpiLoading ? (
        <KpiCardsSkeleton />
      ) : (
        <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* Net Worth */}
          <motion.div
            className={`card-l1 focus-ring p-6 relative overflow-hidden group cursor-pointer ${nwDetailsOpen ? 'md:col-span-2 lg:col-span-2' : ''}`}
            role="button"
            tabIndex={0}
            aria-label="Open Accounts page"
            onClick={() => navigate('/accounts')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                navigate('/accounts');
              }
            }}
          >
            <div className="flex items-center justify-between mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">account_balance</span>
                Net Worth
                {hasAnySynthetic && <SyntheticBadge compact />}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setNwDetailsOpen(v => !v); }}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation(); }}
                  aria-expanded={nwDetailsOpen}
                  aria-label={nwDetailsOpen ? 'Hide breakdown' : 'Show breakdown'}
                  className="focus-ring flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-surface-raised transition-colors"
                  data-testid="dashboard-net-worth-details-toggle"
                >
                  <span aria-hidden="true" className="material-symbols-outlined text-[14px]">
                    {nwDetailsOpen ? 'unfold_less' : 'unfold_more'}
                  </span>
                  Details
                </button>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-surface-raised border border-border">
                  <span aria-hidden="true" className={`w-1.5 h-1.5 rounded-full bg-current ${freshnessColor}`}></span>
                  <span className="text-[10px] font-medium text-muted-foreground" data-testid="dashboard-freshness-label">{freshnessLabel}</span>
                </div>
              </div>
            </div>
            <p className="text-4xl font-bold tracking-tight text-foreground mb-2 text-numeric" data-testid="dashboard-net-worth-latest">
              {formatCurrency(latestNw?.net_worth)}
            </p>
            <div className="flex items-center gap-2 mt-auto">
              <div className={`flex items-center gap-1 text-sm font-semibold ${velocityData?.mom_pct >= 0 ? 'text-gain' : 'text-loss'}`}>
                <span aria-hidden="true" className="material-symbols-outlined text-[16px]">
                  {velocityData?.mom_pct >= 0 ? 'trending_up' : 'trending_down'}
                </span>
                <span>{Math.abs(velocityData?.mom_pct || 0)}%</span>
              </div>
              <span className="text-xs text-muted-foreground">this month</span>
            </div>

            <AnimatePresence initial={false}>
              {nwDetailsOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  onClick={(e) => e.stopPropagation()}
                  className="mt-5 pt-5 border-t border-border text-left cursor-default"
                >
                  <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-3">
                    Snapshot — {MONTH_NAMES[referenceDay.getMonth()]} {referenceDay.getFullYear()}
                  </p>

                  {/* Assets */}
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-foreground">Assets</span>
                      <span className="text-xs font-bold text-numeric text-foreground" data-testid="dashboard-net-worth-assets">
                        {formatCurrency(nwBreakdown.totalAssets)}
                      </span>
                    </div>
                    <div className="flex h-2 rounded-full overflow-hidden gap-0.5 mb-2">
                      {Object.entries(nwBreakdown.assets)
                        .filter(([, v]) => v > 0)
                        .map(([label, v]) => (
                          <div
                            key={label}
                            style={{
                              width: `${(v / Math.max(nwBreakdown.totalAssets, 1)) * 100}%`,
                              backgroundColor: NW_BUCKET_COLORS[label],
                            }}
                          />
                        ))}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {Object.entries(nwBreakdown.assets).map(([label, v]) => (
                        <div key={label} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-2 text-muted-foreground">
                            <span className="size-1.5 rounded-full" style={{ backgroundColor: NW_BUCKET_COLORS[label] }} />
                            <span>{label}</span>
                          </div>
                          <span className="font-medium text-numeric text-foreground">
                            {formatCurrency(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Liabilities */}
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-semibold text-foreground">Liabilities</span>
                      <span className="text-xs font-bold text-numeric text-loss" data-testid="dashboard-net-worth-liabilities">
                        {formatCurrency(nwBreakdown.totalLiabilities)}
                      </span>
                    </div>
                    <div className="flex h-2 rounded-full overflow-hidden gap-0.5 mb-2">
                      {Object.entries(nwBreakdown.liabilities)
                        .filter(([, v]) => v > 0)
                        .map(([label, v]) => (
                          <div
                            key={label}
                            style={{
                              width: `${(v / Math.max(nwBreakdown.totalLiabilities, 1)) * 100}%`,
                              backgroundColor: NW_BUCKET_COLORS[label],
                            }}
                          />
                        ))}
                    </div>
                    <div className="flex flex-col gap-1.5">
                      {Object.entries(nwBreakdown.liabilities).map(([label, v]) => (
                        <div key={label} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-2 text-muted-foreground">
                            <span className="size-1.5 rounded-full" style={{ backgroundColor: NW_BUCKET_COLORS[label] }} />
                            <span>{label}</span>
                          </div>
                          <span className="font-medium text-numeric text-foreground">
                            {formatCurrency(v)}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-3 border-t border-border">
                    <span className="text-xs font-semibold text-foreground">Net Worth</span>
                    <span className="text-sm font-bold text-numeric text-foreground">
                      {formatCurrency(nwBreakdown.netWorth)}
                    </span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          {/* Cash Flow & Savings Rate */}
          <motion.div
            className="card-l1 focus-ring p-6 relative overflow-hidden group cursor-pointer"
            role="button"
            tabIndex={0}
            aria-label="Open Cash Flow page"
            onClick={() => navigate('/cash-flow')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                navigate('/cash-flow');
              }
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">swap_vert</span>
                Monthly Net Flow
                {hasAnySynthetic && <SyntheticBadge compact />}
              </span>
            </div>
            {hasMonthData ? (
              <>
                <p className={`text-4xl font-bold tracking-tight mb-2 text-numeric ${totalNet >= 0 ? 'text-gain' : 'text-loss'}`} data-testid="dashboard-monthly-net-flow">
                  {totalNet >= 0 ? '+' : ''}{formatCurrency(totalNet)}
                </p>
                <div className="flex items-center gap-2 mt-auto flex-wrap">
                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-surface-raised text-xs font-medium text-muted-foreground" data-testid="dashboard-monthly-savings-rate">
                    <span aria-hidden="true" className="material-symbols-outlined text-[14px] text-accent-foreground">savings</span>
                    {savingsRate.toFixed(1)}% Savings Rate
                  </div>
                  {latestDti?.dti_ratio !== null && latestDti?.dti_ratio !== undefined && dtiPillStyle && (
                    <div
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium"
                      style={{ background: dtiPillStyle.bg, color: dtiPillStyle.color }}
                      title={`DTI: ${latestDti.dti_ratio.toFixed(1)}% — ${latestDti.status} (debt payments / gross income)`}
                      data-testid="dashboard-monthly-dti"
                    >
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px]">balance</span>
                      {latestDti.dti_ratio.toFixed(1)}% DTI
                    </div>
                  )}
                  {/* Net debt change pill — only shown when non-trivial (≥$10) so
                      months with even balance don't clutter the card. Color: red
                      when adding debt, green when paying down. */}
                  {latestNetDebtChange !== null && Math.abs(latestNetDebtChange) >= 10 && (
                    <div
                      className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium"
                      style={{
                        background: latestNetDebtChange > 0
                          ? "color-mix(in oklch, var(--color-loss) 12%, transparent)"
                          : "color-mix(in oklch, var(--color-gain) 12%, transparent)",
                        color: latestNetDebtChange > 0 ? "var(--color-loss)" : "var(--color-gain)",
                      }}
                      title={
                        latestNetDebtChange > 0
                          ? `Added ${formatCurrency(Math.abs(latestNetDebtChange))} of debt this month`
                          : `Paid down ${formatCurrency(Math.abs(latestNetDebtChange))} of debt this month`
                      }
                      data-testid="dashboard-monthly-net-debt-change"
                    >
                      <span aria-hidden="true" className="material-symbols-outlined text-[14px]">credit_card</span>
                      {latestNetDebtChange > 0 ? "+" : "−"}{formatCurrency(Math.abs(latestNetDebtChange))} debt
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="flex flex-col items-start gap-2 mt-2">
                <p className="text-2xl font-bold text-muted-foreground">--</p>
                <span className="text-xs text-muted-foreground">No data for this period</span>
              </div>
            )}
          </motion.div>

          {/* Emergency Fund Runway */}
          <motion.div
            className="card-l1 focus-ring p-6 relative overflow-hidden group cursor-pointer"
            role="button"
            tabIndex={0}
            aria-label="Open Cash Flow page"
            onClick={() => navigate('/cash-flow')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                navigate('/cash-flow');
              }
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <span className="text-label flex items-center gap-1.5">
                <span aria-hidden="true" className="material-symbols-outlined text-[18px]">health_and_safety</span>
                Runway
              </span>
            </div>
            <div className="flex items-baseline gap-2 mb-2">
              <p className="text-4xl font-bold tracking-tight text-foreground text-numeric" data-testid="dashboard-runway-months">
                {runwayData?.months_of_runway !== null ? runwayData?.months_of_runway : '—'}
              </p>
              <span className="text-muted-foreground font-medium">months</span>
            </div>
            <div className="flex items-center gap-2 mt-auto">
              <span className="text-xs text-muted-foreground" data-testid="dashboard-runway-avg-spend">
                Based on {formatCurrency(runwayData?.avg_monthly_spending)}/mo avg spend
              </span>
            </div>
          </motion.div>

          {/* Credit Scores — owner-grouped in household view, single column otherwise */}
          <motion.div
            ref={creditCardRef}
            className="card-l1 focus-ring p-6 relative overflow-hidden flex flex-col cursor-pointer"
            role="button"
            tabIndex={0}
            aria-label="View credit score trajectory"
            onClick={() => setCreditPopupOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                setCreditPopupOpen(true);
              }
            }}
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
                  ? 'text-gain'
                  : n >= 700
                  ? 'text-foreground'
                  : 'text-[var(--color-warning)]';

              // Compact pill — used inside per-owner columns when the
              // household view splits the card in two.
              const renderCompactPill = (score: any, key: string) => {
                const inst = score.institution_id ? institutionDisplayName(score.institution_id) : '';
                return (
                  <div
                    key={key}
                    className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-md bg-surface-raised border border-border min-w-0"
                  >
                    <div className="flex flex-col min-w-0">
                      <span className="text-[10px] font-semibold text-foreground truncate">
                        {inst || score.source}
                      </span>
                      <span className="text-[9px] text-muted-foreground truncate">
                        {score.source} · {score.score_type}
                      </span>
                    </div>
                    <span
                      className={`text-base font-bold text-numeric tracking-tight ${colorFor(score.score)}`}
                      data-testid={creditScoreTestId(score)}
                    >
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
                    className="flex items-center justify-between p-2.5 rounded-lg bg-surface-raised border border-border"
                  >
                    <div className="flex flex-col">
                      <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
                        {sublabel}
                      </span>
                      <span className="text-[10px] text-muted-foreground">{label}</span>
                    </div>
                    <span
                      className={`text-xl font-bold text-numeric tracking-tight ${colorFor(score.score)}`}
                      data-testid={creditScoreTestId(score)}
                    >
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
                  return <div className="text-sm text-muted-foreground italic mt-1" data-testid="dashboard-credit-score-empty">No scores available</div>;
                }

                const cols = sections.length === 2 ? 'grid-cols-2' : sections.length === 1 ? 'grid-cols-1' : 'grid-cols-3';

                return (
                  <div className={`grid ${cols} gap-3 mt-1`}>
                    {sections.map((section) => (
                      <div key={section.id} className="flex flex-col gap-1.5 min-w-0">
                        <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                          {section.name}
                        </span>
                        {section.scores.length === 0 ? (
                          <div className="flex items-center justify-center px-2 py-1.5 rounded-md border border-dashed border-border text-[10px] italic text-muted-foreground">
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
                return <div className="text-sm text-muted-foreground italic mt-1" data-testid="dashboard-credit-score-empty">No scores available</div>;
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
                <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
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
                  <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground pointer-events-none underline underline-offset-4 decoration-dotted">
                    {nwTimeframe}
                  </span>
                  <span aria-hidden="true" className="material-symbols-outlined text-muted-foreground text-sm leading-none pointer-events-none">expand_more</span>
                </div>
              </div>

              <div className="flex items-baseline gap-3 flex-wrap">
                <h3 className="font-serif text-[40px] leading-none font-semibold tracking-tight text-foreground tabular-nums">
                  ${nwDollars}<span className="text-[22px] text-muted-foreground font-light">.{nwCents}</span>
                </h3>
                {networthData.length > 1 && (
                  <span className={`text-xs font-semibold tabular-nums ${nwDeltaIsUp ? 'text-[var(--color-gain)]' : 'text-[var(--color-loss)]'}`}>
                    {nwDeltaIsUp ? '▲' : '▼'}{' '}
                    <span data-testid="dashboard-net-worth-delta-amount">{nwDeltaIsUp ? '+' : ''}{formatCurrency(nwDelta)}</span>
                    {' '}(<span data-testid="dashboard-net-worth-delta-percent">{nwDeltaIsUp ? '+' : ''}{nwDeltaPct.toFixed(1)}%</span>) ·{' '}
                    <span data-testid="dashboard-net-worth-velocity-amount">{formatCurrency(nwVelocity)}/mo</span> pace
                  </span>
                )}
              </div>
            </div>
          </div>
          {networthData.length > 0 ? (
            <div className="flex-1 w-full min-h-0 -ml-4">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={networthData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <defs>
                    <linearGradient id="netWorthGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--chart-c1)" stopOpacity={0.32} />
                      <stop offset="100%" stopColor="var(--chart-c1)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="date" tick={rechartsAxisTickStyle()} axisLine={false} tickLine={false} />
                  <YAxis width={95} tick={rechartsAxisTickStyle()} axisLine={false} tickLine={false} tickFormatter={fmtChart} />
                  <Tooltip
                    contentStyle={rechartsTooltipStyle()}
                    labelStyle={rechartsTooltipLabelStyle()}
                    itemStyle={rechartsTooltipItemStyle()}
                    formatter={(v) => fmtChart(v as number)}
                  />
                  <Area
                    type="monotone"
                    dataKey="Net Worth"
                    stroke="var(--chart-c1)"
                    strokeWidth={2}
                    fill="url(#netWorthGradient)"
                  />
                </AreaChart>
              </ResponsiveContainer>
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

            <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted-foreground">
              No. {monthOrdinal} — {monthName} · Spending
            </p>

            <h3 className="mt-2 font-serif text-[56px] leading-none font-semibold tracking-tight text-foreground tabular-nums" data-testid="dashboard-spending-current-month-total">
              ${totalDollars}<span className="text-[28px] text-muted-foreground font-light">.{totalCents}</span>
            </h3>

            {hasMonthData ? (
              <p className="mt-3 text-sm text-foreground leading-relaxed">
                <span className={`font-semibold ${spendDeltaIsUp ? 'text-[var(--color-loss)]' : 'text-[var(--color-gain)]'}`}>
                  {spendDeltaIsUp ? 'Up' : 'Down'}{' '}
                  <span data-testid="dashboard-spending-delta-amount">{formatCurrency(Math.abs(spendDelta))}</span>
                  {' '}(<span data-testid="dashboard-spending-delta-percent">{Math.abs(spendDeltaPct).toFixed(1)}%</span>)
                </span>{' '}
                {comparisonNarrative}, {daysElapsed} days in — pace suggests landing near{' '}
                <span className="font-semibold text-numeric" data-testid="dashboard-spending-projected-eom">{formatCurrency(projectedEom)}</span> by month-end.
              </p>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">No spending recorded this month yet.</p>
            )}

            <div className="mt-4 flex items-center gap-6 flex-wrap">
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Per day</span>
                <span className="font-serif text-base font-semibold tabular-nums text-foreground" data-testid="dashboard-spending-per-day">{formatCurrency(perDay)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{spendPrevLabel}</span>
                <span className="font-serif text-base font-semibold tabular-nums text-muted-foreground">{formatCurrency(prevTotal)}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Projected</span>
                <span className={`font-serif text-base font-semibold tabular-nums ${spendDeltaIsUp ? 'text-[var(--color-loss)]' : 'text-[var(--color-gain)]'}`} data-testid="dashboard-spending-projected-eom-secondary">
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
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground pointer-events-none underline underline-offset-4 decoration-dotted">
                  {spendingTf}
                </span>
                <span aria-hidden="true" className="material-symbols-outlined text-muted-foreground text-sm leading-none pointer-events-none">expand_more</span>
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
              className="text-label text-muted-foreground hover:text-[var(--color-gain)] transition-colors"
              onClick={() => navigate('/transactions')}
            >View All</button>
          </div>
          {txLoading && recentTransactions.length === 0 ? (
            <TransactionListSkeleton />
          ) : (
            <div className="flex-1 overflow-auto">
              {recentTransactions.length === 0 && !txLoading ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <span aria-hidden="true" className="material-symbols-outlined text-3xl text-muted-foreground mb-3">receipt_long</span>
                  <p className="text-sm text-muted-foreground">No transactions yet</p>
                </div>
              ) : (
                recentTransactions.map((tx: any, index: number) => (
                  <motion.div
                    whileHover={{ x: 4, backgroundColor: 'color-mix(in oklch, var(--primary) 5%, transparent)' }}
                    key={tx.id}
                    role="button"
                    tabIndex={0}
                    aria-label={`Open ${tx.merchant || tx.description || 'transaction'}`}
                    className="focus-ring py-4 border-b border-border flex items-center justify-between cursor-pointer group rounded-md"
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
                        <h4 title={tx.merchant || tx.description} className="font-bold text-sm text-foreground truncate max-w-[200px] flex items-center gap-1.5">
                          <span className="truncate">{tx.merchant || tx.description}</span>
                          {accountIsSynthetic.get(tx.account_id) && <SyntheticBadge compact />}
                        </h4>
                        {tx.merchant && tx.description && tx.merchant !== tx.description && (
                          <span title={tx.description} className="text-xs text-muted-foreground truncate max-w-[200px]">
                            {tx.description}
                          </span>
                        )}
                        <p className="text-[11px] font-medium text-muted-foreground mt-0.5">
                          {tx.category} • {accountNames[tx.account_id] || tx.account_id}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className={`text-sm text-numeric ${(tx.signed_amount ?? tx.amount) < 0 ? 'text-muted-foreground' : 'text-gain'}`} data-testid={`dashboard-recent-transaction-amount-${index + 1}`}>
                        {(tx.signed_amount ?? tx.amount) >= 0 ? '+' : ''}{formatCurrency(tx.signed_amount ?? tx.amount)}
                      </span>
                      <span aria-hidden="true" className="material-symbols-outlined text-muted-foreground text-sm group-hover:text-primary transition-colors">arrow_forward</span>
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
            className="focus-ring w-full cursor-pointer group rounded-md"
            onClick={() => navigate('/budgets')}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                navigate('/budgets');
              }
            }}
          >
            <div className="pb-4 mb-4 border-b border-border flex items-center justify-between">
              <h3 className="text-label flex items-center gap-1.5">
                Current Budget
                {hasAnySynthetic && <SyntheticBadge compact />}
              </h3>
              <span className="text-label text-muted-foreground">{budgetMonth}</span>
            </div>

            <div className="mb-6">
              <p className="text-3xl font-bold tracking-tight text-foreground mb-2 text-numeric" data-testid="dashboard-budget-spent">{formatCurrency(budgetSpent)}</p>
              <div
                className="w-full bg-surface-raised h-1 overflow-hidden relative"
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
                  className="bg-foreground h-full absolute top-0 left-0"
                />
              </div>
              <div className="flex justify-between mt-3 text-label">
                <span>Total: <span data-testid="dashboard-budget-total">{formatCurrency(budgetTotal)}</span></span>
                <span data-testid="dashboard-budget-progress-percent">{budgetPct.toFixed(0)}% used</span>
                <span><span data-testid="dashboard-budget-remaining">{formatCurrency(budgetRemaining)}</span> remaining</span>
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
                      className="focus-ring flex items-center gap-4 cursor-pointer rounded-md"
                      role="button"
                      tabIndex={0}
                      aria-label={`Open ${cat.category} budget`}
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/budgets?category=${encodeURIComponent(cat.category)}`);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          e.stopPropagation();
                          navigate(`/budgets?category=${encodeURIComponent(cat.category)}`);
                        }
                      }}
                    >
                      <span title={cat.category} className="text-sm font-bold text-foreground w-32 truncate">{cat.category}</span>
                      <div className="flex-1 bg-surface-raised h-[2px] overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 1, ease: "easeOut" }}
                          className={`h-full ${pct > 90 ? 'bg-[var(--color-loss)]' : 'bg-[var(--color-gain)]'}`}
                        />
                      </div>
                      <div className="text-right w-20 shrink-0">
                        <span className="block text-xs text-numeric text-foreground" data-testid={`dashboard-budget-category-amount-${testIdPart(cat.category)}`}>
                          {formatCurrency(cat.spent)}
                        </span>
                        <span className="block text-[10px] text-numeric tracking-widest text-muted-foreground" data-testid={`dashboard-budget-category-percent-${testIdPart(cat.category)}`}>
                          {pct.toFixed(0)}%
                        </span>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Recurring Widget */}
          <div className="flex-1 flex flex-col">
             <div className="pb-4 mb-4 border-b border-border flex items-center justify-between">
              <h3 className="text-label flex items-center gap-1.5">
                Recurring
                {hasAnySynthetic && <SyntheticBadge compact />}
              </h3>
              <span className="text-label text-muted-foreground text-numeric" data-testid="dashboard-recurring-monthly-total">{formatCurrency(recurringTotal)} /mo</span>
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
                      <span aria-hidden="true" className="material-symbols-outlined text-2xl text-muted-foreground mb-2">event_repeat</span>
                      <p className="text-sm text-muted-foreground">No recurring bills detected</p>
                    </div>
                  );
                }
                return recurringBills.slice(0, 5).map((item: any) => {
                  return (
                    <motion.div
                      whileHover={{ x: 4 }}
                      key={item.id}
                      className="focus-ring py-3 flex items-center justify-between cursor-pointer group rounded-md"
                      role="button"
                      tabIndex={0}
                      aria-label={`View recurring ${item.merchant} transactions`}
                      onClick={() => navigate(`/transactions?recurring=true&merchant=${encodeURIComponent(item.merchant)}`)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigate(`/transactions?recurring=true&merchant=${encodeURIComponent(item.merchant)}`);
                        }
                      }}
                    >
                      <div>
                        <h4 className="font-bold text-sm text-foreground">{item.merchant}</h4>
                        <p className="text-label text-muted-foreground mt-1">{item.frequency}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-numeric text-sm tracking-widest text-foreground" data-testid={`dashboard-recurring-item-amount-${testIdPart(item.id)}`}>{formatCurrency(item.expected_amount || item.last_amount || 0)}</p>
                        <p className="text-label text-muted-foreground mt-1">
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
