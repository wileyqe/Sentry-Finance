import { useState } from "react";
import { formatCurrency } from "@/lib/formatCurrency";

interface PeriodTotal {
  label: string;
  total: number;
}

interface CreepCategory {
  category: string;
  period_totals: PeriodTotal[];
  annualized_growth_pct: number | null;
  income_growth_pct: number | null;
  excess_pct: number | null;
  flagged: boolean;
  trend: "accelerating" | "steady" | "decelerating";
}

interface LifestyleCreepResult {
  period_start: string;
  period_end: string;
  income_growth_pct: number | null;
  categories: CreepCategory[];
  flagged_count: number;
  flag_threshold_pct: number;
  insufficient_data?: boolean;
}

interface LifestyleCreepPanelProps {
  data: LifestyleCreepResult | null;
  compact?: boolean;
  onLookbackChange?: (years: number) => void;
}

const fmt = (n: number | null | undefined) =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

const fmtDollar = (n: number) => formatCurrency(n);

const trendIcon: Record<string, string> = {
  accelerating: "trending_up",
  steady: "trending_flat",
  decelerating: "trending_down",
};

export default function LifestyleCreepPanel({ data, compact = false, onLookbackChange }: LifestyleCreepPanelProps) {
  const [lookback, setLookback] = useState(2);

  if (!data) {
    return (
      <div className="card-l1 p-5">
        <div className="flex items-center gap-2 text-slate-400">
          <span className="material-symbols-outlined text-[18px]">hourglass_empty</span>
          <span className="text-sm">Loading lifestyle analysis…</span>
        </div>
      </div>
    );
  }

  if (data.insufficient_data) {
    return (
      <div className="card-l1 p-5">
        <div className="flex items-center gap-2 text-slate-400">
          <span className="material-symbols-outlined text-[18px]">info</span>
          <span className="text-sm">Need 24+ months of data for lifestyle creep analysis</span>
        </div>
      </div>
    );
  }

  const flagged = data.categories.filter((c) => c.flagged);

  /* ── Compact mode (Monthly Review) ──────────────────────────────── */
  if (compact) {
    if (flagged.length === 0) {
      return (
        <div className="flex items-center gap-2 text-sm">
          <span className="material-symbols-outlined text-[18px] text-gain">check_circle</span>
          <span className="text-slate-500">No lifestyle creep detected</span>
        </div>
      );
    }

    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px] text-loss">warning</span>
          <span className="text-sm font-semibold text-loss">
            {flagged.length} {flagged.length === 1 ? "category" : "categories"} outpacing income
          </span>
        </div>
        <div className="space-y-1 pl-6">
          {flagged.slice(0, 3).map((c) => (
            <div key={c.category} className="flex items-center justify-between text-sm">
              <span className="text-slate-600 dark:text-slate-300">{c.category}</span>
              <span className="font-mono text-xs font-semibold text-loss bg-loss-subtle px-2 py-0.5 rounded-md">
                {fmt(c.excess_pct)} excess
              </span>
            </div>
          ))}
          {flagged.length > 3 && (
            <span className="text-xs text-slate-400">+{flagged.length - 3} more</span>
          )}
        </div>
        <a
          href="/review/yearly"
          className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 hover:underline mt-1"
        >
          View full analysis
          <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
        </a>
      </div>
    );
  }

  /* ── Full mode (Yearly Wrap-Up) ─────────────────────────────────── */
  const periodLabels = data.categories.length > 0
    ? data.categories[0].period_totals.map((pt) => pt.label)
    : [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          {data.income_growth_pct != null ? (
            <p className="text-sm text-slate-600 dark:text-slate-300">
              Income grew <span className="font-semibold">{fmt(data.income_growth_pct)}</span>
              {" — "}
              {flagged.length > 0 ? (
                <span className="text-loss font-semibold">
                  {flagged.length} spending {flagged.length === 1 ? "category" : "categories"} exceeded that
                </span>
              ) : (
                <span className="text-gain font-semibold">no categories exceeded that</span>
              )}
            </p>
          ) : (
            <p className="text-sm text-slate-400">Insufficient income data to compare</p>
          )}
        </div>
        <select
          value={lookback}
          onChange={(e) => {
            const val = Number(e.target.value);
            setLookback(val);
            onLookbackChange?.(val);
          }}
          className="text-xs border border-slate-200 dark:border-slate-700 rounded-lg px-2 py-1.5 bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300"
        >
          <option value={2}>2 years</option>
          <option value={3}>3 years</option>
        </select>
      </div>

      {/* Table */}
      {data.categories.length === 0 ? (
        <div className="text-center py-8 text-slate-400 text-sm">
          <span className="material-symbols-outlined text-4xl mb-2 block opacity-40">
            check_circle
          </span>
          No lifestyle creep detected.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-label border-b border-slate-200 dark:border-slate-700">
                <th className="pb-2 pr-4">Category</th>
                {periodLabels.map((l) => (
                  <th key={l} className="pb-2 pr-4 text-right">{l}</th>
                ))}
                <th className="pb-2 pr-4 text-right">Growth</th>
                <th className="pb-2 pr-4 text-right">vs Income</th>
                <th className="pb-2 text-center">Trend</th>
                <th className="pb-2 text-center w-10">Flag</th>
              </tr>
            </thead>
            <tbody>
              {data.categories.map((c) => (
                <tr
                  key={c.category}
                  className={`border-b border-slate-100 dark:border-slate-800 ${
                    c.flagged
                      ? "border-l-2 border-l-[var(--color-loss)] bg-loss-subtle/30"
                      : "opacity-70"
                  }`}
                >
                  <td className="py-2.5 pr-4 font-medium text-slate-700 dark:text-slate-200">
                    {c.category}
                  </td>
                  {c.period_totals.map((pt) => (
                    <td key={pt.label} className="py-2.5 pr-4 text-right text-numeric text-slate-500 dark:text-slate-400">
                      {fmtDollar(pt.total)}
                    </td>
                  ))}
                  <td className={`py-2.5 pr-4 text-right font-mono font-semibold ${
                    c.annualized_growth_pct != null && c.annualized_growth_pct > 0 ? "text-loss" : "text-gain"
                  }`}>
                    {fmt(c.annualized_growth_pct)}
                  </td>
                  <td className={`py-2.5 pr-4 text-right font-mono font-semibold ${
                    c.flagged ? "text-loss" : "text-slate-400"
                  }`}>
                    {fmt(c.excess_pct)}
                  </td>
                  <td className="py-2.5 text-center">
                    <span
                      className={`material-symbols-outlined text-[16px] ${
                        c.trend === "accelerating"
                          ? "text-loss"
                          : c.trend === "decelerating"
                          ? "text-gain"
                          : "text-slate-400"
                      }`}
                      title={c.trend}
                    >
                      {trendIcon[c.trend] || "trending_flat"}
                    </span>
                  </td>
                  <td className="py-2.5 text-center">
                    {c.flagged && (
                      <span className="material-symbols-outlined text-[16px] text-loss">flag</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
