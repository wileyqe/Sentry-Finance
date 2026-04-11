/**
 * InvestmentsOverview — Overview tab for the Investments page.
 *
 * Three sections:
 *   1. Performance area chart (3/4 width) + asset class donut (1/4 width)
 *   2. Contributions vs. Growth horizontal bar chart (full width)
 *
 * Wired to /api/investments/holdings, /api/investments/performance,
 * and /api/investments/allocation.
 */

import { useMemo } from "react";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { formatCurrency } from "@/lib/formatCurrency";
import { useOwnerApi } from "@/lib/useOwnerApi";

/* ── Types ────────────────────────────────────────────────────────────────── */

type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

interface InvestmentsTabProps {
  timeframe: Timeframe;
  accountFilter: string;
}

interface AccountData {
  account_id: string;
  name: string;
  total_value: number;
  cash_balance: number;
  holdings: any[];
}

const CHART_COLORS = [
  "var(--chart-c1)", "var(--chart-c2)", "var(--chart-c3)", "var(--chart-c4)",
  "var(--chart-c5)", "var(--chart-c6)", "var(--chart-c7)", "var(--chart-c8)",
];

/* ── Custom Tooltip ───────────────────────────────────────────────────────── */

function PerformanceTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;

  return (
    <div className="bg-slate-900 dark:bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 shadow-xl min-w-[160px]">
      <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-1.5">{label}</p>
      <div className="flex items-center justify-between gap-6">
        <span className="text-xs text-slate-400">Value</span>
        <span className="text-xs font-bold text-white text-numeric">{formatCurrency(d.total_value)}</span>
      </div>
    </div>
  );
}

function BarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;

  return (
    <div className="bg-slate-900 dark:bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 shadow-xl min-w-[180px]">
      <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">{label}</p>
      <div className="flex flex-col gap-1.5">
        {payload.map((p: any) => (
          <div key={p.name} className="flex items-center justify-between gap-6">
            <span className="text-xs text-slate-400">{p.name}</span>
            <span className="text-xs font-bold text-white text-numeric">{formatCurrency(p.value)}</span>
          </div>
        ))}
        <div className="border-t border-slate-700 mt-1 pt-1 flex items-center justify-between gap-6">
          <span className="text-xs text-slate-400">Total</span>
          <span className="text-xs font-bold text-white text-numeric">
            {formatCurrency(payload.reduce((s: number, p: any) => s + (p.value || 0), 0))}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Component ────────────────────────────────────────────────────────────── */

export default function InvestmentsOverview({ timeframe, accountFilter }: InvestmentsTabProps) {
  const { data: holdingsData, loading: holdingsLoading } = useOwnerApi<{ accounts: AccountData[] }>(
    "/api/investments/holdings"
  );
  const allocUrl = accountFilter === "all"
    ? "/api/investments/allocation"
    : `/api/investments/allocation?account_id=${encodeURIComponent(accountFilter)}`;
  const { data: allocationData } = useOwnerApi<any>(allocUrl);

  // Performance: pass account_id to backend; "all" aggregates across accounts
  const perfUrl = useMemo(() => {
    const aid = accountFilter === "all" ? "all" : accountFilter;
    return `/api/investments/performance?account_id=${encodeURIComponent(aid)}&timeframe=${timeframe}`;
  }, [accountFilter, timeframe]);

  const { data: perfData } = useOwnerApi<{ data: any[] }>(perfUrl);

  // Compute totals
  const accounts = holdingsData?.accounts || [];
  const filteredAccounts = accountFilter === "all"
    ? accounts
    : accounts.filter((a) => a.account_id === accountFilter);

  const totalValue = filteredAccounts.reduce((s, a) => s + a.total_value, 0);

  // Performance chart data
  const perfPoints = useMemo(() => {
    if (!perfData?.data) return [];
    return perfData.data.map((d: any) => {
      const dateStr = d.date || d.month || "";
      const label = dateStr.length >= 7
        ? new Date(dateStr + (dateStr.length === 7 ? "-01" : "")).toLocaleDateString("en-US", { month: "short", year: "2-digit" })
        : dateStr;
      return { label, total_value: d.total_value };
    });
  }, [perfData]);

  // Compute change
  const firstValue = perfPoints.length > 1 ? perfPoints[0]?.total_value || 0 : 0;
  const lastValue = perfPoints.length > 0 ? perfPoints[perfPoints.length - 1]?.total_value || 0 : totalValue;
  const changeAbs = lastValue - firstValue;
  const changePct = firstValue > 0 ? (changeAbs / firstValue) * 100 : 0;
  const positive = changeAbs >= 0;

  // Asset class data from allocation API
  const assetClasses = useMemo(() => {
    if (!allocationData?.by_asset_class) return [];
    return allocationData.by_asset_class.map((c: any, i: number) => ({
      name: c.name,
      value: c.pct,
      amount: c.amount,
      color: CHART_COLORS[i % CHART_COLORS.length],
    }));
  }, [allocationData]);

  // Account bars (contributions vs growth)
  const accountBars = useMemo(() => {
    return filteredAccounts.map((a) => ({
      name: a.name,
      contributions: Math.round(a.total_value * 0.6), // approximate until contribution tracking
      growth: Math.round(a.total_value * 0.4),
    }));
  }, [filteredAccounts]);

  if (holdingsLoading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <span className="material-symbols-outlined animate-spin text-xl mr-2">progress_activity</span>
        Loading overview...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {/* ── Top: Performance Chart (3/4) + Donut (1/4) ──────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">

        {/* Performance Area Chart */}
        <div className="xl:col-span-3 card-l1 flex flex-col">
          <div className="px-6 pt-5 pb-3">
            <p className="text-label mb-1">Portfolio Value</p>
            <div className="flex items-baseline gap-3">
              <span className="stat-value">{formatCurrency(lastValue || totalValue)}</span>
              {perfPoints.length > 1 && (
                <span className={`text-sm font-semibold ${positive ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"}`}>
                  {positive ? "+" : ""}{formatCurrency(changeAbs)} ({positive ? "+" : ""}{changePct.toFixed(1)}%)
                </span>
              )}
            </div>
          </div>
          <div className="px-4 pb-4 flex-1">
            {perfPoints.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <AreaChart data={perfPoints} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="portfolioGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor={positive ? "var(--color-gain)" : "var(--color-loss)"} stopOpacity={0.20} />
                      <stop offset="95%" stopColor={positive ? "var(--color-gain)" : "var(--color-loss)"} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="0" horizontal vertical={false} stroke="var(--border)" strokeOpacity={0.5} />
                  <XAxis dataKey="label" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} dy={8} />
                  <YAxis tickFormatter={(v) => formatCurrency(v)} axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} width={80} />
                  <Tooltip content={<PerformanceTooltip />} />
                  <Area type="monotone" dataKey="total_value" stroke={positive ? "var(--color-gain)" : "var(--color-loss)"} strokeWidth={2.5} fillOpacity={1} fill="url(#portfolioGrad)" />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[280px] text-muted-foreground text-sm">
                No performance data available
              </div>
            )}
          </div>
        </div>

        {/* Asset Class Donut */}
        <div className="xl:col-span-1 card-l1 flex flex-col">
          <div className="px-5 pt-5 pb-2">
            <p className="text-label">Asset Allocation</p>
          </div>
          <div className="flex-1 flex flex-col items-center justify-center px-4 pb-4">
            <div className="relative w-full h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '12px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)' }}
                    formatter={(value: any, name: any) => [`${value}%`, name]}
                  />
                  <Pie
                    data={assetClasses}
                    cx="50%" cy="50%"
                    innerRadius={55} outerRadius={85}
                    paddingAngle={2} dataKey="value" stroke="none"
                  >
                    {assetClasses.map((entry: any, i: number) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span className="text-lg font-bold text-foreground">{assetClasses.length}</span>
                <span className="text-label">Classes</span>
              </div>
            </div>
            <div className="w-full mt-3 space-y-1.5">
              {assetClasses.map((cls: any) => (
                <div key={cls.name} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <div className="size-2.5 rounded-full" style={{ backgroundColor: cls.color }} />
                    <span className="text-muted-foreground">{cls.name}</span>
                  </div>
                  <span className="font-semibold text-foreground text-numeric">{cls.value}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Bottom: Contributions vs Growth by Account ──────────────────── */}
      <div className="card-l1 flex flex-col">
        <div className="px-6 pt-5 pb-3">
          <p className="text-label">Portfolio Value by Account</p>
        </div>
        <div className="px-4 pb-5">
          <ResponsiveContainer width="100%" height={Math.max(160, accountBars.length * 56)}>
            <BarChart
              data={accountBars}
              layout="vertical"
              margin={{ top: 0, right: 24, left: 0, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="0" horizontal={false} vertical stroke="var(--border)" strokeOpacity={0.5} />
              <XAxis
                type="number"
                tickFormatter={(v) => formatCurrency(v)}
                axisLine={false} tickLine={false}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <YAxis
                type="category" dataKey="name"
                axisLine={false} tickLine={false}
                tick={{ fontSize: 12, fill: "var(--foreground)", fontWeight: 500 }}
                width={160}
              />
              <Tooltip content={<BarTooltip />} cursor={{ fill: "var(--border)", opacity: 0.3 }} />
              <Bar
                dataKey="contributions" name="Contributions"
                stackId="a" fill="var(--chart-c2)" fillOpacity={0.45}
              />
              <Bar
                dataKey="growth" name="Growth"
                stackId="a" fill="var(--color-gain)" fillOpacity={0.85}
                radius={[0, 4, 4, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
