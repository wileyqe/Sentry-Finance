import { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../lib/api";
import { useView } from "../context/ViewContext";
import LifestyleCreepPanel from "../components/LifestyleCreepPanel";

/* ── Helpers ──────────────────────────────────────────────────────── */

const fmt$ = (n: number) =>
  "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const fmtPct = (n: number | null | undefined) =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

const monthName = (m: string) => {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1).toLocaleString("en-US", { month: "long", year: "numeric" });
};

/* ── Month selector helper ────────────────────────────────────────── */

function buildMonthOptions(count = 24) {
  const opts: string[] = [];
  const d = new Date();
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

interface ReviewData {
  month: string;
  income: { total: number; prior_month: number; trailing_12m_avg: number; mom_change_pct: number };
  spending: { total: number; prior_month: number; trailing_12m_avg: number; mom_change_pct: number };
  savings_rate: number;
  net_worth_delta: { amount: number; pct: number; direction: string };
  budget_highlights: any[];
  subscription_changes: any[];
  notable_transactions: any[];
  uncategorized_count: number;
  lifestyle_flags: any[];
  freshness: any[];
}

/* ── Component ────────────────────────────────────────────────────── */

export default function MonthlyReviewPage() {
  const { ownerParam } = useView();
  const monthOpts = useMemo(() => buildMonthOptions(24), []);
  const [month, setMonth] = useState(monthOpts[0]);
  const [data, setData] = useState<ReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lifestyleData, setLifestyleData] = useState<any>(null);

  useEffect(() => {
    const ownerSuffix = ownerParam ? `&owner_id=${ownerParam}` : '';
    const ownerQs = ownerParam ? `?owner_id=${ownerParam}` : '';
    setLoading(true);
    apiFetch(`/api/review/monthly?month=${month}${ownerSuffix}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));

    apiFetch(`/api/lifestyle/creep${ownerQs}`)
      .then(setLifestyleData)
      .catch(() => setLifestyleData(null));
  }, [month, ownerParam]);

  const navigateMonth = (dir: -1 | 1) => {
    const idx = monthOpts.indexOf(month);
    const next = idx - dir; // list is reverse chronological
    if (next >= 0 && next < monthOpts.length) setMonth(monthOpts[next]);
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          <div className="h-8 w-72 rounded-lg bg-slate-200 dark:bg-slate-800 animate-pulse" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="card-l1 h-28 animate-pulse bg-slate-100 dark:bg-slate-800/50" />
            ))}
          </div>
          <div className="card-l1 h-64 animate-pulse bg-slate-100 dark:bg-slate-800/50" />
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-slate-400">
        <span className="material-symbols-outlined mr-2">error</span>
        Failed to load monthly review
      </div>
    );
  }

  const nwDelta = data.net_worth_delta;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* ── Header Row ──────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100">
            Monthly Review — {monthName(month)}
          </h1>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigateMonth(-1)}
              disabled={monthOpts.indexOf(month) === monthOpts.length - 1}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">chevron_left</span>
            </button>
            <select
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              className="text-sm border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-1.5 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200"
            >
              {monthOpts.map((m) => (
                <option key={m} value={m}>{monthName(m)}</option>
              ))}
            </select>
            <button
              onClick={() => navigateMonth(1)}
              disabled={monthOpts.indexOf(month) === 0}
              className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30 transition-colors"
            >
              <span className="material-symbols-outlined text-[20px]">chevron_right</span>
            </button>
          </div>
        </div>

        {/* ── KPI Strip ───────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4">
          {/* Income */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Income</p>
            <p className="stat-value">{fmt$(data.income.total)}</p>
            <div className="mt-2">
              <span className={data.income.mom_change_pct >= 0 ? "stat-delta-pos" : "stat-delta-neg"}>
                <span className="material-symbols-outlined text-[14px]">
                  {data.income.mom_change_pct >= 0 ? "arrow_upward" : "arrow_downward"}
                </span>
                {fmtPct(data.income.mom_change_pct)}
              </span>
              <span className="text-xs text-slate-400 ml-2">vs prior month</span>
            </div>
          </div>

          {/* Spending */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Spending</p>
            <p className="stat-value">{fmt$(data.spending.total)}</p>
            <div className="mt-2">
              <span className={data.spending.mom_change_pct <= 0 ? "stat-delta-pos" : "stat-delta-neg"}>
                <span className="material-symbols-outlined text-[14px]">
                  {data.spending.mom_change_pct <= 0 ? "arrow_downward" : "arrow_upward"}
                </span>
                {fmtPct(data.spending.mom_change_pct)}
              </span>
              <span className="text-xs text-slate-400 ml-2">vs prior month</span>
            </div>
          </div>

          {/* Savings Rate */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Savings Rate</p>
            <p className="stat-value">{data.savings_rate.toFixed(1)}%</p>
            <p className="text-xs text-slate-400 mt-2">
              12m avg: {data.income.trailing_12m_avg > 0
                ? ((1 - data.spending.trailing_12m_avg / data.income.trailing_12m_avg) * 100).toFixed(1)
                : "0"}%
            </p>
          </div>

          {/* Net Worth Delta */}
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Net Worth Change</p>
            <p className={`stat-value ${nwDelta.direction === "up" ? "text-gain" : nwDelta.direction === "down" ? "text-loss" : ""}`}>
              {nwDelta.amount >= 0 ? "+" : "−"}{fmt$(nwDelta.amount)}
            </p>
            <div className="mt-2">
              <span className={nwDelta.direction === "up" ? "stat-delta-pos" : nwDelta.direction === "down" ? "stat-delta-neg" : "chip-l2"}>
                <span className="material-symbols-outlined text-[14px]">
                  {nwDelta.direction === "up" ? "arrow_upward" : nwDelta.direction === "down" ? "arrow_downward" : "remove"}
                </span>
                {fmtPct(nwDelta.pct)}
              </span>
            </div>
          </div>
        </div>

        {/* ── Budget Performance ───────────────────────────────────── */}
        <div className="card-l1 p-5">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-emerald-500">pie_chart</span>
            Budget Performance
          </h2>
          {data.budget_highlights.length === 0 ? (
            <p className="text-sm text-slate-400 py-4 text-center">No budget data for this month</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-label border-b border-slate-200 dark:border-slate-700">
                    <th className="pb-2">Category</th>
                    <th className="pb-2 text-right">Budgeted</th>
                    <th className="pb-2 text-right">Actual</th>
                    <th className="pb-2 text-right">Variance</th>
                    <th className="pb-2 text-right">% Used</th>
                  </tr>
                </thead>
                <tbody>
                  {data.budget_highlights.slice(0, 8).map((b: any) => (
                    <tr
                      key={b.category}
                      className={`border-b border-slate-100 dark:border-slate-800 ${
                        b.variance > 0 ? "bg-loss-subtle/30" : b.variance < -20 ? "bg-gain-subtle/30" : ""
                      }`}
                    >
                      <td className="py-2.5 font-medium text-slate-700 dark:text-slate-200">{b.category}</td>
                      <td className="py-2.5 text-right text-numeric text-slate-500">{fmt$(b.budgeted)}</td>
                      <td className="py-2.5 text-right text-numeric text-slate-700 dark:text-slate-200">{fmt$(b.actual)}</td>
                      <td className={`py-2.5 text-right text-numeric font-semibold ${b.variance > 0 ? "text-loss" : "text-gain"}`}>
                        {b.variance > 0 ? "+" : ""}{fmt$(b.variance)}
                      </td>
                      <td className="py-2.5 text-right text-numeric text-slate-500">{b.pct_used.toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Two-column: Subscriptions + Notable ─────────────────── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Subscription Changes */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-emerald-500">autorenew</span>
              Subscription Changes
            </h2>
            {data.subscription_changes.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No subscription changes this month</p>
            ) : (
              <div className="space-y-2">
                {data.subscription_changes.map((sc: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-sm py-2 border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="text-slate-700 dark:text-slate-200 font-medium">{sc.merchant}</span>
                      <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded-md ${
                        sc.change_type === "new" ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400" :
                        sc.change_type === "removed" ? "bg-slate-100 dark:bg-slate-800 text-slate-500" :
                        "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400"
                      }`}>
                        {sc.change_type === "price_change" ? "Price Change" : sc.change_type}
                      </span>
                    </div>
                    {sc.delta != null && (
                      <span className={`font-mono text-xs font-semibold ${sc.delta > 0 ? "text-loss" : "text-gain"}`}>
                        {sc.delta > 0 ? "+" : ""}{fmt$(sc.delta)}/mo
                      </span>
                    )}
                    {sc.new_amount != null && sc.delta == null && (
                      <span className="font-mono text-xs text-slate-500">{fmt$(sc.new_amount)}/mo</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Notable Transactions */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-emerald-500">receipt_long</span>
              Notable Transactions
            </h2>
            {data.notable_transactions.length === 0 ? (
              <p className="text-sm text-slate-400 py-4 text-center">No notable transactions</p>
            ) : (
              <div className="space-y-2">
                {data.notable_transactions.map((tx: any) => (
                  <div key={tx.id} className="flex items-center justify-between text-sm py-2 border-b border-slate-100 dark:border-slate-800 last:border-0">
                    <div className="flex-1 min-w-0 mr-3">
                      <p className="font-medium text-slate-700 dark:text-slate-200 truncate">
                        {tx.merchant || tx.description}
                      </p>
                      <p className="text-xs text-slate-400">
                        {new Date(tx.date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                        {" · "}{tx.category}
                      </p>
                    </div>
                    <span className="font-mono text-sm font-semibold text-slate-700 dark:text-slate-200 shrink-0">
                      {fmt$(tx.amount)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Status Row ──────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Uncategorized */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-amber-500">label_off</span>
              Uncategorized
            </h3>
            {data.uncategorized_count === 0 ? (
              <p className="text-sm text-slate-400">All transactions categorized ✓</p>
            ) : (
              <div>
                <p className="text-2xl font-bold text-amber-600 dark:text-amber-400">{data.uncategorized_count}</p>
                <a href={`/transactions?filter=uncategorized`} className="text-xs text-emerald-600 dark:text-emerald-400 hover:underline mt-1 inline-flex items-center gap-1">
                  Review now <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                </a>
              </div>
            )}
          </div>

          {/* Lifestyle Creep */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-orange-500">show_chart</span>
              Lifestyle Creep
            </h3>
            <LifestyleCreepPanel data={lifestyleData} compact />
          </div>

          {/* Data Freshness */}
          <div className="card-l1 p-5">
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-sky-500">sync</span>
              Data Freshness
            </h3>
            {data.freshness.length === 0 ? (
              <p className="text-sm text-slate-400">No freshness data</p>
            ) : (
              <div className="space-y-1.5">
                {data.freshness.map((f: any) => (
                  <div key={f.institution} className="flex items-center justify-between text-sm">
                    <span className="text-slate-600 dark:text-slate-300">{f.institution}</span>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-md ${
                      f.status === "fresh" ? "bg-emerald-100 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400" :
                      f.status === "stale" ? "bg-amber-100 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400" :
                      f.status === "critical" ? "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400" :
                      "bg-slate-100 dark:bg-slate-800 text-slate-500"
                    }`}>
                      {f.status === "fresh" ? "✓ Fresh" :
                       f.status === "stale" ? `⚠ ${f.hours_since_update?.toFixed(0)}h ago` :
                       f.status === "critical" ? `✕ ${f.hours_since_update?.toFixed(0)}h ago` :
                       "No data"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
