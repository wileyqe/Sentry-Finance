import { useState, useEffect, useCallback, useMemo } from "react";
import {
  ComposedChart, Bar, Line, Cell, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { useAccounts } from "@/lib/accounts";
import { useView } from "../context/ViewContext";
import { useRuntimeContext } from "@/context/RuntimeContext";
import { motion } from "framer-motion";
import { formatCurrency } from "@/lib/formatCurrency";
import { parseIsoDateLocal } from "@/lib/dateUtils";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/Skeleton";
import { toast } from "@/lib/toast";
import { withOwnerQuery } from "@/lib/ownerRequest";

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

/* ── Constants ──────────────────────────────────────────────────────────────── */

const API = "http://127.0.0.1:8000";

// ACCOUNT_NAMES now comes from useAccounts() hook inside the component

// Category → Material Symbol icon mapping
const CAT_ICONS: Record<string, string> = {
  "Paychecks/Salary":    "work",
  "Interest":            "account_balance",
  "Investment Income":   "trending_up",
  "Retirement Income":   "savings",
  "Rental Income":       "home",
  "Tax Refund":          "receipt",
  "Other Income":        "add_circle",
  "Groceries":           "shopping_cart",
  "Dining":              "restaurant",
  "Shopping":            "shopping_bag",
  "Entertainment":       "movie",
  "Travel":              "flight",
  "Utilities":           "bolt",
  "Auto":                "directions_car",
  "Medical":             "medical_services",
  "Insurance":           "shield",
  "Home Improvement":    "home_repair_service",
  "Mortgage":            "house",
  "Childcare":           "child_care",
  "Phone":               "smartphone",
  "Internet":            "wifi",
  "Furniture":           "chair",
  "Subscriptions":       "subscriptions",
  "Gifts":               "card_giftcard",
  "Uncategorized":       "help_outline",
};

const iconFor = (cat: string) => CAT_ICONS[cat] ?? "circle";

/* ── Formatters ─────────────────────────────────────────────────────────────── */

const fmt = (v: number) => formatCurrency(v);

const fmtFull = (v: number) => formatCurrency(v);

/* ── Period label builders ──────────────────────────────────────────────────── */

function periodDates(granularity: Granularity, year: number, index: number): { start: string; end: string; label: string } {
  if (granularity === "monthly") {
    const m = String(index).padStart(2, "0");
    const lastDay = new Date(year, index, 0).getDate();
    return {
      start: `${year}-${m}-01`,
      end:   `${year}-${m}-${String(lastDay).padStart(2, "0")}`,
      label: `${new Date(year, index - 1).toLocaleString("en-US", { month: "long" })} ${year}`,
    };
  }
  if (granularity === "quarterly") {
    const startMonth = (index - 1) * 3 + 1;
    const endMonth   = startMonth + 2;
    const lastDay = new Date(year, endMonth, 0).getDate();
    return {
      start: `${year}-${String(startMonth).padStart(2, "0")}-01`,
      end:   `${year}-${String(endMonth).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`,
      label: `Q${index} ${year}`,
    };
  }
  // yearly
  return { start: `${year}-01-01`, end: `${year}-12-31`, label: String(year) };
}

/* ── Types ──────────────────────────────────────────────────────────────────── */

type Granularity = "monthly" | "quarterly" | "yearly";

interface ChartPoint {
  label: string;
  income: number;
  spending: number;
  net: number;
  netSolid: number | null;
  netDotted: number | null;
  savings_rate: number;
  index: number;  // month, quarter, or year number
  year: number;   // calendar year this point belongs to
  // PR2 cash-out lens additions (only populated for monthly granularity)
  debt_service?: number;
  debt_accumulated?: number;
  debt_paid_down?: number;
  net_debt_change?: number;
}

interface CategoryRow {
  category: string;
  total: number;
  pct: number;
  count: number;
}

interface PeriodDetail {
  income: number;
  spending: number;
  net: number;
  savings_rate: number;
  gross_savings_rate: number;
  income_categories: CategoryRow[];
  spending_categories: CategoryRow[];
  start_date: string;
  end_date: string;
  // PR2 cash-out lens additions
  debt_service: number;       // slice of spending that's debt service
  debt_accumulated: number;   // CC merchant purchases this period (NOT in spending)
  debt_paid_down: number;     // CC payments + auto/loan/mortgage paydown
  net_debt_change: number;    // accumulated - paid_down (signed)
}

type DtiStatus = "healthy" | "moderate" | "high" | "critical";

interface DtiPoint {
  month: string;          // "YYYY-MM"
  debt_payments: number;
  gross_income: number;
  dti_ratio: number | null;
  status: DtiStatus | null;
}

const DTI_STATUS_META: Record<DtiStatus, { label: string; color: string; bg: string }> = {
  healthy:  { label: "Healthy",  color: "var(--color-gain)",    bg: "color-mix(in oklch, var(--color-gain) 12%, transparent)" },
  moderate: { label: "Moderate", color: "var(--color-warning)", bg: "color-mix(in oklch, var(--color-warning) 14%, transparent)" },
  high:     { label: "High",     color: "var(--color-warning)", bg: "color-mix(in oklch, var(--color-warning) 22%, transparent)" },
  critical: { label: "Critical", color: "var(--color-loss)",    bg: "color-mix(in oklch, var(--color-loss) 14%, transparent)" },
};

const DTI_THRESHOLDS = { healthy: 28, moderate: 36, high: 43 } as const;

/* ── Custom Tooltip ─────────────────────────────────────────────────────────── */

function CashFlowTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as ChartPoint;
  if (!d) return null;

  const netPositive = d.net >= 0;

  return (
    <div className="bg-popover text-popover-foreground border border-border rounded-xl px-4 py-3 shadow-xl min-w-[180px]">
      <p className="text-[11px] font-bold text-muted-foreground uppercase tracking-widest mb-2">{label}</p>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-muted-foreground">Income</span>
          <span className="text-xs font-bold text-[var(--color-gain)] text-numeric">{fmtFull(d.income)}</span>
        </div>
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-muted-foreground">Expenses</span>
          <span className="text-xs font-bold text-[var(--color-loss)] text-numeric">{fmtFull(d.spending)}</span>
        </div>
        <div className="border-t border-border mt-1 pt-1 flex items-center justify-between gap-6">
          <span className="text-xs text-muted-foreground">Net</span>
          <span className={`text-xs font-bold text-numeric ${netPositive ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"}`}>
            {netPositive ? "+" : ""}{fmtFull(d.net)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-muted-foreground">Savings Rate</span>
          <span className="text-xs font-bold text-foreground text-numeric">{d.savings_rate.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}

/* ── KPI Card ───────────────────────────────────────────────────────────────── */

function KpiCard({
  label,
  value,
  color,
  subtitle,
  testId,
  subtitleTestId,
}: {
  label: string;
  value: string;
  color: string;
  subtitle?: string;
  testId?: string;
  subtitleTestId?: string;
}) {
  return (
    <div className="card-l1 px-5 py-4 flex flex-col gap-1">
      <p className={`text-2xl font-extrabold text-numeric tracking-tight leading-none ${color}`} data-testid={testId}>{value}</p>
      {subtitle && <p className="text-[11px] text-muted-foreground font-medium" data-testid={subtitleTestId}>{subtitle}</p>}
      <p className="text-label mt-0.5">{label}</p>
    </div>
  );
}

/* ── Debt-to-Income Panel ───────────────────────────────────────────────────── */

function monthLabelShort(m: string): string {
  // "2026-03" → "Mar 26"
  const [y, mm] = m.split("-");
  const idx = Number(mm) - 1;
  const month = new Date(2000, idx, 1).toLocaleString("en-US", { month: "short" });
  return `${month} ${y.slice(2)}`;
}

function DtiTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p: DtiPoint = payload[0].payload;
  const meta = p.status ? DTI_STATUS_META[p.status] : null;
  return (
    <div className="rounded-md border border-border bg-card p-3 text-xs shadow-lg">
      <p className="text-[11px] font-bold text-foreground mb-2">{monthLabelShort(p.month)}</p>
      <div className="flex flex-col gap-1 text-numeric">
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Debt service</span>
          <span className="font-semibold text-foreground">{formatCurrency(p.debt_payments)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Gross income</span>
          <span className="font-semibold text-foreground">{formatCurrency(p.gross_income)}</span>
        </div>
        <div className="flex items-center justify-between gap-4 pt-1 border-t border-border mt-1">
          <span className="text-muted-foreground">DTI</span>
          <span className="font-bold text-numeric" style={{ color: meta?.color ?? "var(--foreground)" }}>
            {p.dti_ratio !== null ? `${p.dti_ratio.toFixed(1)}%` : "—"}
            {meta && <span className="ml-1.5 text-[10px] font-semibold uppercase tracking-wide">{meta.label}</span>}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Debt Accumulation Panel (PR4) ──────────────────────────────────────────── */

interface DebtAccumPoint {
  label: string;
  year: number;
  month: number;
  debt_accumulated: number;
  debt_paid_down: number;
  net_debt_change: number;
}

function DebtAccumTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null;
  const p: DebtAccumPoint = payload[0].payload;
  return (
    <div className="rounded-md border border-border bg-card p-3 text-xs shadow-lg">
      <p className="text-[11px] font-bold text-foreground mb-2">{p.label}</p>
      <div className="flex flex-col gap-1 text-numeric">
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Purchased on credit</span>
          <span className="font-semibold text-foreground">{formatCurrency(p.debt_accumulated)}</span>
        </div>
        <div className="flex items-center justify-between gap-4">
          <span className="text-muted-foreground">Paid toward debt</span>
          <span className="font-semibold text-foreground">{formatCurrency(p.debt_paid_down)}</span>
        </div>
        <div className="flex items-center justify-between gap-4 pt-1 border-t border-border mt-1">
          <span className="text-muted-foreground">Net change</span>
          <span
            className="font-bold text-numeric"
            style={{ color: p.net_debt_change > 0 ? "var(--color-loss)" : p.net_debt_change < 0 ? "var(--color-gain)" : "var(--foreground)" }}
          >
            {p.net_debt_change >= 0 ? "+" : ""}{formatCurrency(p.net_debt_change)}
          </span>
        </div>
      </div>
    </div>
  );
}

function DebtAccumulationPanel({
  data,
  loading,
}: {
  data: DebtAccumPoint[] | null;
  loading: boolean;
}) {
  const series = data ?? [];
  const latest = series.length > 0 ? series[series.length - 1] : null;
  const hasAnyActivity = series.some(p => p.debt_accumulated > 0 || p.debt_paid_down > 0);

  return (
    <div className="card-l1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <span className="text-label flex items-center gap-1.5">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">credit_card</span>
          Debt Accumulation
        </span>
        <span className="text-[11px] text-muted-foreground font-medium">
          Trailing 12 months · what you charged vs what you paid down
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-[260px] text-muted-foreground gap-3">
          <span className="material-symbols-outlined text-3xl animate-spin" style={{ animationDuration: "1.5s" }}>
            progress_activity
          </span>
          <span className="text-sm font-medium">Loading…</span>
        </div>
      ) : !hasAnyActivity ? (
        <div className="px-5 py-12 text-center text-muted-foreground">
          <p className="text-sm font-medium">No credit-card or loan activity in the trailing window.</p>
          <p className="text-[11px] mt-1">
            Tracks credit-card purchases and the cash-side payments toward them.
          </p>
          <div className="sr-only">
            <span data-testid="cash-flow-net-debt-change">$0.00</span>
            <span data-testid="cash-flow-debt-accumulated">$0.00</span>
            <span data-testid="cash-flow-debt-paid-down">$0.00</span>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-0">
          {/* ── Latest-month tiles ────────────────────────────────────── */}
          <div className="px-5 py-5 lg:border-r border-b lg:border-b-0 border-border flex flex-col gap-3">
            <div>
              <p className="text-label">Latest · {latest?.label ?? "—"}</p>
              <div className="flex items-baseline gap-2 mt-1">
                <p
                  className="text-3xl font-bold tracking-tight text-numeric"
                  data-testid="cash-flow-net-debt-change"
                  style={{
                    color: !latest || latest.net_debt_change === 0
                      ? "var(--foreground)"
                      : latest.net_debt_change > 0
                        ? "var(--color-loss)"
                        : "var(--color-gain)",
                  }}
                >
                  {latest && latest.net_debt_change !== 0 ? (latest.net_debt_change > 0 ? "+" : "") : ""}
                  {latest ? formatCurrency(Math.abs(latest.net_debt_change)) : "—"}
                </p>
                <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">net</span>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">
                {latest && latest.net_debt_change > 0
                  ? "Added to balances this month"
                  : latest && latest.net_debt_change < 0
                    ? "Paid down balances this month"
                    : "Even this month"}
              </p>
            </div>
            <div className="flex flex-col gap-2 mt-auto pt-2 border-t border-border">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Purchased on credit</span>
                <span className="font-semibold text-numeric text-foreground" data-testid="cash-flow-debt-accumulated">
                  {latest ? formatCurrency(latest.debt_accumulated) : "—"}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Paid toward debt</span>
                <span className="font-semibold text-numeric text-foreground" data-testid="cash-flow-debt-paid-down">
                  {latest ? formatCurrency(latest.debt_paid_down) : "—"}
                </span>
              </div>
            </div>
          </div>

          {/* ── Trend chart ─────────────────────────────────────────── */}
          <div className="px-2 py-4">
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart
                data={series}
                margin={{ top: 12, right: 16, left: 0, bottom: 12 }}
              >
                <CartesianGrid
                  strokeDasharray="0"
                  horizontal
                  vertical={false}
                  stroke="var(--border)"
                  strokeOpacity={0.6}
                />
                <XAxis
                  dataKey="label"
                  tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                />
                <Tooltip content={<DebtAccumTooltip />} cursor={{ fill: "var(--surface-raised)", fillOpacity: 0.4 }} />
                <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.5} />
                <Bar dataKey="net_debt_change" radius={[3, 3, 3, 3]}>
                  {series.map((p, i) => (
                    <Cell
                      key={i}
                      fill={p.net_debt_change > 0 ? "var(--color-loss)" : "var(--color-gain)"}
                      fillOpacity={0.65}
                    />
                  ))}
                </Bar>
              </ComposedChart>
            </ResponsiveContainer>
            <div className="flex items-center justify-end gap-4 px-3 mt-1">
              <div className="flex items-center gap-1.5">
                <div className="size-3 rounded-sm" style={{ background: "var(--color-loss)", opacity: 0.65 }} />
                <span className="text-[10px] text-muted-foreground font-medium">Added debt</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="size-3 rounded-sm" style={{ background: "var(--color-gain)", opacity: 0.65 }} />
                <span className="text-[10px] text-muted-foreground font-medium">Paid down</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DebtToIncomePanel({ data, loading }: { data: DtiPoint[] | null; loading: boolean }) {
  const series = data ?? [];
  const latest = series.length > 0 ? series[series.length - 1] : null;
  const latestMeta = latest?.status ? DTI_STATUS_META[latest.status] : null;

  return (
    <div className="card-l1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <span className="text-label flex items-center gap-1.5">
          <span aria-hidden="true" className="material-symbols-outlined text-[16px]">balance</span>
          Debt-to-Income
        </span>
        <span className="text-[11px] text-muted-foreground font-medium">
          Trailing 12 months · monthly debt payments / gross income
        </span>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-[260px] text-muted-foreground gap-3">
          <span className="material-symbols-outlined text-3xl animate-spin" style={{ animationDuration: "1.5s" }}>
            progress_activity
          </span>
          <span className="text-sm font-medium">Loading…</span>
        </div>
      ) : series.length === 0 ? (
        <div className="px-5 py-12 text-center text-muted-foreground">
          <p className="text-sm font-medium" data-testid="cash-flow-dti-empty-state">No debt service activity in the trailing window.</p>
          <p className="text-[11px] mt-1">DTI is computed from cash-account debits categorized as debt payments.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-0">
          {/* ── Latest-month tile ─────────────────────────────────────── */}
          <div className="px-5 py-5 lg:border-r border-b lg:border-b-0 border-border flex flex-col gap-3">
            <div>
              <p className="text-label">Latest · {latest ? monthLabelShort(latest.month) : "—"}</p>
              <div className="flex items-baseline gap-2 mt-1">
                <p
                  className="text-4xl font-bold tracking-tight text-numeric"
                  style={{ color: latestMeta?.color ?? "var(--foreground)" }}
                  data-testid="cash-flow-dti-latest-percent"
                >
                  {latest?.dti_ratio !== null && latest?.dti_ratio !== undefined ? `${latest.dti_ratio.toFixed(1)}%` : "—"}
                </p>
                {latestMeta && (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full"
                    style={{ background: latestMeta.bg, color: latestMeta.color }}
                  >
                    {latestMeta.label}
                  </span>
                )}
              </div>
            </div>
            {latest && latest.gross_income > 0 && (
              <div className="text-[11px] text-muted-foreground font-medium leading-relaxed">
                <span className="text-numeric font-semibold text-foreground" data-testid="cash-flow-dti-debt-payments">{formatCurrency(latest.debt_payments)}</span>
                {" debt service "}
                <span className="text-muted-foreground/70">/</span>
                {" "}
                <span className="text-numeric font-semibold text-foreground" data-testid="cash-flow-dti-gross-income">{formatCurrency(latest.gross_income)}</span>
                {" income"}
              </div>
            )}
            <div className="flex flex-col gap-1 mt-auto pt-2 border-t border-border text-[10px] text-muted-foreground">
              <div className="flex items-center justify-between">
                <span>Healthy</span><span className="font-semibold text-numeric">≤ 28%</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Moderate</span><span className="font-semibold text-numeric">28–36%</span>
              </div>
              <div className="flex items-center justify-between">
                <span>High</span><span className="font-semibold text-numeric">36–43%</span>
              </div>
              <div className="flex items-center justify-between">
                <span>Critical</span><span className="font-semibold text-numeric">&gt; 43%</span>
              </div>
            </div>
          </div>

          {/* ── Trend chart ───────────────────────────────────────────── */}
          <div className="px-2 py-4">
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart
                data={series}
                margin={{ top: 12, right: 16, left: 0, bottom: 12 }}
              >
                <CartesianGrid
                  strokeDasharray="0"
                  horizontal
                  vertical={false}
                  stroke="var(--border)"
                  strokeOpacity={0.6}
                />
                <XAxis
                  dataKey="month"
                  tickFormatter={monthLabelShort}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  yAxisId="left"
                  tickFormatter={(v) => `$${(v / 1000).toFixed(1)}k`}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  tickFormatter={(v) => `${v}%`}
                  tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={36}
                  domain={[0, (dataMax: number) => Math.max(50, Math.ceil(dataMax * 1.1))]}
                />
                <Tooltip content={<DtiTooltip />} cursor={{ fill: "var(--surface-raised)", fillOpacity: 0.4 }} />
                <ReferenceLine yAxisId="right" y={DTI_THRESHOLDS.healthy}  stroke="var(--color-gain)"    strokeDasharray="3 3" strokeOpacity={0.55} />
                <ReferenceLine yAxisId="right" y={DTI_THRESHOLDS.moderate} stroke="var(--color-warning)" strokeDasharray="3 3" strokeOpacity={0.55} />
                <ReferenceLine yAxisId="right" y={DTI_THRESHOLDS.high}     stroke="var(--color-loss)"    strokeDasharray="3 3" strokeOpacity={0.55} />
                <Bar
                  yAxisId="left"
                  dataKey="debt_payments"
                  fill="var(--color-loss)"
                  fillOpacity={0.45}
                  radius={[3, 3, 0, 0]}
                />
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="dti_ratio"
                  stroke="var(--foreground)"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "var(--foreground)" }}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="flex items-center justify-end gap-4 px-3 mt-1">
              <div className="flex items-center gap-1.5">
                <div className="size-3 rounded-sm" style={{ background: "var(--color-loss)", opacity: 0.45 }} />
                <span className="text-[10px] text-muted-foreground font-medium">Debt service ($)</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="w-5 h-0.5 rounded-full" style={{ background: "var(--foreground)" }} />
                <span className="text-[10px] text-muted-foreground font-medium">DTI ratio (%)</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Category Row ───────────────────────────────────────────────────────────── */

function testIdPart(value: unknown) {
  return String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";
}

function CategoryRowItem({
  cat,
  total,
  pct,
  colorVar,
  testIdPrefix,
}: {
  cat: string;
  total: number;
  pct: number;
  colorVar: string;
  testIdPrefix: string;
}) {
  const slug = testIdPart(cat);
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-raised dark:hover:bg-surface-raised transition-colors rounded-lg group">
      {/* Icon */}
      <div
        className="size-8 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: `color-mix(in oklch, ${colorVar} 12%, transparent)` }}
      >
        <span
          className="material-symbols-outlined text-[18px]"
          style={{ color: colorVar }}
        >
          {iconFor(cat)}
        </span>
      </div>

      {/* Name + bar */}
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium text-foreground truncate">{cat}</p>
        <div className="mt-1 h-1.5 bg-surface-raised dark:bg-surface-raised rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(pct, 100)}%`, background: colorVar }}
          />
        </div>
      </div>

      {/* Amount + pct */}
      <div className="text-right shrink-0">
        <p className="text-[13px] font-semibold text-numeric text-foreground" data-testid={`${testIdPrefix}-amount-${slug}`}>{fmtFull(total)}</p>
        <p className="text-[10px] text-muted-foreground" data-testid={`${testIdPrefix}-percent-${slug}`}>{pct.toFixed(1)}%</p>
      </div>
    </div>
  );
}

/* ── Category Section ───────────────────────────────────────────────────────── */

function CategorySection({
  title, total, rows, colorVar, totalIncome,
}: {
  title: string; total: number; rows: CategoryRow[]; colorVar: string; totalIncome: number;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const testIdPrefix = title.toLowerCase() === "income"
    ? "cash-flow-income-category"
    : "cash-flow-spending-category";

  return (
    <div className="card-l1 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-surface-raised dark:hover:bg-surface-raised/60 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span
            className="text-sm font-bold uppercase tracking-widest"
            style={{ color: colorVar }}
          >
            {title}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-base font-extrabold text-numeric text-foreground">{fmtFull(total)}</span>
          <span className="material-symbols-outlined text-[18px] text-muted-foreground transition-transform duration-200"
            style={{ transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)" }}>
            expand_more
          </span>
        </div>
      </button>

      {!collapsed && (
        <>
          {rows.length === 0 ? (
            <EmptyState title="No data for this period" className="py-8" />
          ) : (
            <div className="px-2 pb-2 divide-y divide-border">
              {rows.map((r) => (
                <CategoryRowItem
                  key={r.category}
                  cat={r.category}
                  total={r.total}
                  pct={totalIncome > 0 ? (r.total / totalIncome) * 100 : r.pct}
                  colorVar={colorVar}
                  testIdPrefix={testIdPrefix}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Filter Drawer ──────────────────────────────────────────────────────────── */

function FilterDrawer({
  open, onClose, accountId, onAccountChange,
}: {
  open: boolean;
  onClose: () => void;
  accountId: string;
  onAccountChange: (id: string) => void;
}) {
  const { accountNames: ACCOUNT_NAMES } = useAccounts();
  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/20 dark:bg-black/40 backdrop-blur-[2px]"
          onClick={onClose}
        />
      )}
      {/* Drawer */}
      <div
        className={`fixed right-0 top-0 z-40 h-full w-72 bg-background border-l border-border flex flex-col shadow-xl transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <span className="font-bold text-base">Filters</span>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">
          {/* Account filter */}
          <div>
            <p className="text-label mb-2">Account</p>
            <select
              className="w-full h-9 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg px-3 text-sm font-medium outline-none focus:ring-2 focus:ring-[var(--ring)]/30 cursor-pointer"
              value={accountId || "ALL"}
              onChange={e => onAccountChange(e.target.value === "ALL" ? "" : e.target.value)}
            >
              <option value="ALL">All Accounts</option>
              {Object.entries(ACCOUNT_NAMES).map(([id, name]) => (
                <option key={id} value={id}>{name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="p-5 border-t border-border flex gap-3">
          <Button
            variant="outline"
            size="lg"
            onClick={() => { onAccountChange(""); onClose(); }}
            className="flex-1 text-sm font-semibold"
          >
            Reset
          </Button>
          <Button
            size="lg"
            onClick={onClose}
            className="flex-1 text-sm font-semibold"
          >
            Apply
          </Button>
        </div>
      </div>
    </>
  );
}

/* ── Animated Trend Line ────────────────────────────────────────────────────── */

// AnimatedLine removed as it was unused

/* ── Custom Year-Break Tick ─────────────────────────────────────────────────── */

function YearBreakTick({ x, y, payload, chartPoints, granularity }: any) {
  const idx = chartPoints.findIndex((p: ChartPoint) => p.label === payload?.value);
  const pt = chartPoints[idx];
  if (!pt) return null;

  // Show year label at the first point of each year (but not in yearly mode)
  const isFirstOfYear = granularity !== "yearly" && (idx === 0 || chartPoints[idx - 1]?.year !== pt.year);

  // Count how many points belong to this year to center the label
  let yearSpan = 0;
  for (let i = idx; i < chartPoints.length && chartPoints[i].year === pt.year; i++) {
    yearSpan++;
  }

  let displayLabel = payload.value;
  if (granularity === "monthly") {
    // Extract abbreviated month name (e.g. "January 2025" -> "Jan")
    displayLabel = payload.value.split(" ")[0].substring(0, 3);
  } else if (granularity === "quarterly") {
    // Extract quarter name (e.g. "Q1 2025" -> "Q1")
    displayLabel = payload.value.split(" ")[0];
  }

  return (
    <g transform={`translate(${x},${y})`}>
      {/* Regular tick label */}
      <text
        x={0} y={6} dy={10}
        textAnchor="middle"
        fill="var(--muted-foreground)"
        fontSize={10}
        fontWeight={500}
        fontFamily="var(--font-sans)"
      >
        {displayLabel}
      </text>
      {/* Year label centered over the first occurrence (hidden in yearly mode) */}
      {isFirstOfYear && yearSpan > 0 && (
        <text
          x={0} y={6} dy={24}
          textAnchor="start"
          fill="var(--muted-foreground)"
          fontSize={10}
          fontWeight={700}
          fontFamily="var(--font-sans)"
          opacity={0.6}
        >
          {pt.year}
        </text>
      )}
    </g>
  );
}

/* ── Main Page ──────────────────────────────────────────────────────────────── */

export default function CashFlowPage() {
  const { ownerParam } = useView();
  const { referenceDate, ready: runtimeReady } = useRuntimeContext();
  const referenceDay = useMemo(() => parseIsoDateLocal(referenceDate), [referenceDate]);
  const [granularity, setGranularity] = useState<Granularity>("monthly");
  const [accountId, setAccountId] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);

  // Chart data
  const [chartPoints, setChartPoints] = useState<ChartPoint[]>([]);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState<Error | null>(null);

  // Active period (set by bar click or defaults to current/rightmost period)
  const [activePeriod, setActivePeriod] = useState<{ index: number; year: number; label: string } | null>(null);

  // Detail data for the active period
  const [detail, setDetail] = useState<PeriodDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<Error | null>(null);

  // Debt-to-Income trailing series (12 months by design — matches lender thresholds)
  const [dtiSeries, setDtiSeries] = useState<DtiPoint[] | null>(null);
  const [dtiLoading, setDtiLoading] = useState(true);

  // Animation key — bumped to force re-animation on data change
  const [animKey, setAnimKey] = useState(0);

  // ── Fetch chart data ─────────────────────────────────────────────────────
  const fetchChart = useCallback(() => {
    if (!runtimeReady) return;
    setChartLoading(true);
    setChartError(null);

    let path: string;
    if (granularity === "monthly") {
      path = "/api/cash-flow/monthly-rolling";
    } else if (granularity === "quarterly") {
      path = "/api/cash-flow/quarterly-rolling";
    } else {
      path = "/api/cash-flow/yearly";
    }
    const url = `${API}${withOwnerQuery(path, ownerParam, { account_id: accountId || undefined })}`;

    fetch(url)
      .then(r => r.json())
      .then(d => {
        let pts: ChartPoint[] = [];
        if (granularity === "monthly" && d.months) {
          pts = d.months.map((m: any) => ({
            label: m.label,
            income: m.income,
            spending: m.spending,
            net: m.net,
            savings_rate: m.savings_rate,
            index: m.month,
            year: m.year,
            netSolid: null,
            netDotted: null,
            // PR2 cash-out lens fields — pass through for the Debt
            // Accumulation panel below.
            debt_service: m.debt_service,
            debt_accumulated: m.debt_accumulated,
            debt_paid_down: m.debt_paid_down,
            net_debt_change: m.net_debt_change,
          }));
        } else if (granularity === "quarterly" && d.quarters) {
          pts = d.quarters.map((q: any) => ({
            label: q.label,
            income: q.income,
            spending: q.spending,
            net: q.net,
            savings_rate: q.savings_rate,
            index: q.quarter,
            year: q.year,
            netSolid: null,
            netDotted: null,
          }));
        } else if (granularity === "yearly" && d.years) {
          let yearData = (d.years as any[]).filter((y: any) => y.year <= referenceDay.getFullYear());
          // Only keep years with data, max 4, min 2
          yearData = yearData.filter((y: any) => y.income > 0 || y.spending > 0);
          if (yearData.length > 4) yearData = yearData.slice(-4);
          if (yearData.length < 2) {
            // Pad with current and previous year
            const currentYear = referenceDay.getFullYear();
            const needed = [currentYear - 1, currentYear];
            for (const yr of needed) {
              if (!yearData.find((y: any) => y.year === yr)) {
                yearData.push({ year: yr, label: String(yr), income: 0, spending: 0, net: 0, savings_rate: 0 });
              }
            }
            yearData.sort((a: any, b: any) => a.year - b.year);
            yearData = yearData.slice(-4);
          }
          pts = yearData.map((y: any) => ({
            label: y.label,
            income: y.income,
            spending: y.spending,
            net: y.net,
            savings_rate: y.savings_rate,
            index: y.year,
            year: y.year,
            netSolid: null,
            netDotted: null,
          }));
        }

        // Split net into solid / dotted segments
        if (pts.length >= 2) {
          for (let i = 0; i < pts.length; i++) {
            if (i < pts.length - 1) {
              // All points except last get solid net
              pts[i].netSolid = pts[i].net;
            }
            if (i === pts.length - 2) {
              // Second-to-last starts the dotted bridge
              pts[i].netDotted = pts[i].net;
            }
            if (i === pts.length - 1) {
              // Last point (current) is dotted only
              pts[i].netDotted = pts[i].net;
              pts[i].netSolid = null;
            }
          }
        } else if (pts.length === 1) {
          pts[0].netDotted = pts[0].net;
        }

        setChartPoints(pts);
        setChartLoading(false);
        setAnimKey(k => k + 1);

        // Default active period to the last (current) point
        if (pts.length > 0) {
          const last = pts[pts.length - 1];
          setActivePeriod({ index: last.index, year: last.year, label: last.label });
        }
      })
      .catch(e => {
        console.error(e);
        setChartPoints([]);
        setChartError(e instanceof Error ? e : new Error(String(e)));
        setChartLoading(false);
        toast("Failed to load cash flow chart", "error");
      });
  }, [runtimeReady, granularity, accountId, ownerParam, referenceDay]);

  useEffect(() => { fetchChart(); }, [fetchChart]);

  // ── Fetch period detail ──────────────────────────────────────────────────
  const fetchDetail = useCallback(() => {
    if (!activePeriod) return;
    setDetailLoading(true);
    setDetailError(null);

    let start: string, end: string;
    if (granularity === "yearly") {
      const yr = activePeriod.index;
      start = `${yr}-01-01`;
      end   = `${yr}-12-31`;
    } else {
      const pd = periodDates(granularity, activePeriod.year, activePeriod.index);
      start = pd.start;
      end   = pd.end;
    }

    const detailPath = withOwnerQuery("/api/cash-flow/period", ownerParam, {
      start,
      end,
      account_id: accountId || undefined,
    });
    fetch(`${API}${detailPath}`)
      .then(r => r.json())
      .then(d => { setDetail(d); setDetailLoading(false); })
      .catch(e => {
        console.error(e);
        setDetail(null);
        setDetailError(e instanceof Error ? e : new Error(String(e)));
        setDetailLoading(false);
        toast("Failed to load period detail", "error");
      });
  }, [activePeriod, granularity, accountId, ownerParam]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  // ── Fetch DTI trailing 12 months ─────────────────────────────────────────
  // Re-fires on owner switch. Account filter is intentionally not threaded —
  // DTI is a household/owner-level health metric, not per-account.
  useEffect(() => {
    setDtiLoading(true);
    const dtiPath = withOwnerQuery("/api/metrics/dti", ownerParam, { months: 12 });
    fetch(`${API}${dtiPath}`)
      .then(r => r.json())
      .then(d => {
        setDtiSeries(Array.isArray(d) ? d : []);
        setDtiLoading(false);
      })
      .catch(e => {
        console.error("DTI fetch failed", e);
        setDtiSeries([]);
        setDtiLoading(false);
      });
  }, [ownerParam]);

  // ── "Current" period reference (always the last chart point) ────────────
  const currentPeriod = useMemo(() => {
    if (!chartPoints.length) return null;
    const last = chartPoints[chartPoints.length - 1];
    return { index: last.index, year: last.year, label: last.label };
  }, [chartPoints]);

  const isViewingCurrent = activePeriod && currentPeriod
    ? activePeriod.index === currentPeriod.index && activePeriod.year === currentPeriod.year
    : true;

  const resetToCurrent = useCallback(() => {
    if (currentPeriod) setActivePeriod({ ...currentPeriod });
  }, [currentPeriod]);

  // ── Bar click handler (on each Bar, not ComposedChart) ──────────────────
  const handleBarSegmentClick = (data: any) => {
    if (!data?.payload) return;
    const pt = data.payload as ChartPoint;
    // Toggle: re-clicking the active period resets to current
    if (activePeriod && activePeriod.index === pt.index && activePeriod.year === pt.year) {
      resetToCurrent();
    } else {
      setActivePeriod({ index: pt.index, year: pt.year, label: pt.label });
    }
  };

  // ── Chart Y-axis max ─────────────────────────────────────────────────────
  const chartMax = useMemo(() => {
    if (!chartPoints.length) return undefined;
    const max = Math.max(...chartPoints.map(p => Math.max(p.income, p.spending)));
    return Math.ceil(max / 1000) * 1000 + 500;
  }, [chartPoints]);

  // ── Year-break reference lines ───────────────────────────────────────────
  const yearBreaks = useMemo(() => {
    const breaks: { label: string; year: number }[] = [];
    for (let i = 1; i < chartPoints.length; i++) {
      if (chartPoints[i].year !== chartPoints[i - 1].year) {
        breaks.push({ label: chartPoints[i].label, year: chartPoints[i].year });
      }
    }
    return breaks;
  }, [chartPoints]);

  // ── Active chart point highlight ─────────────────────────────────────────
  const activeLabel = activePeriod
    ? chartPoints.find(p => p.index === activePeriod.index && p.year === activePeriod.year)?.label
    : undefined;

  // ── Sizing per granularity ───────────────────────────────────────────────
  const maxBarSize = granularity === "monthly" ? 28 : granularity === "quarterly" ? 52 : 72;

  // OKLCH-based colors using CSS variables
  const gainColor = "var(--color-gain)";
  const lossColor = "var(--color-loss)";

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 overflow-auto"
    >

      {/* ── Sticky Toolbar — page title lives in global Header ─────────── */}
      <motion.div variants={itemVariants} className="sticky top-0 z-20 bg-background border-b border-border px-12 py-3 flex items-center justify-end gap-4">
        <div className="flex items-center gap-3">
          {/* Granularity toggle */}
          <div className="flex items-center gap-0.5 bg-surface-raised dark:bg-surface-raised/60 rounded-full p-0.5">
            {(["monthly", "quarterly", "yearly"] as Granularity[]).map(g => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`px-4 py-1.5 rounded-full text-[12.5px] font-semibold transition-all duration-150 capitalize ${
                  granularity === g
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {g.charAt(0).toUpperCase() + g.slice(1)}
              </button>
            ))}
          </div>

          {/* Filter button */}
          <button
            onClick={() => setFilterOpen(true)}
            className={`flex items-center gap-1.5 px-3 h-9 rounded-lg border text-sm font-semibold transition-all duration-150 ${
              accountId
                ? "bg-primary/10 border-primary/40 text-primary"
                : "border-border text-muted-foreground hover:text-foreground hover:border-border"
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">filter_list</span>
            Filters
            {accountId && <span className="size-2 rounded-full bg-primary" />}
          </button>
        </div>
      </motion.div>

      <motion.div variants={itemVariants} className="flex-1 px-12 py-8 flex flex-col gap-5">

        {/* ── Trend Chart Card ──────────────────────────────────────────────── */}
        <div className="card-l1 flex flex-col overflow-hidden">
          {/* Chart header — just the title, no date selectors */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-border">
            <span className="text-label">
              Cash Flow Trend
            </span>
            <span className="text-[11px] text-muted-foreground font-medium">
              {granularity === "monthly" ? "Last 18 months" : granularity === "quarterly" ? "Last 9 quarters" : "Annual overview"}
            </span>
          </div>

          {/* Chart body */}
          <div className="px-2 py-4">
            {chartLoading ? (
              <div className="flex items-center justify-center h-[300px] text-muted-foreground gap-3">
                <span className="material-symbols-outlined text-3xl animate-spin" style={{ animationDuration: "1.5s" }}>
                  progress_activity
                </span>
                <span className="text-sm font-medium">Loading…</span>
              </div>
            ) : chartError ? (
              <ErrorState
                title="Couldn't load cash flow chart"
                description={chartError.message || "Network error"}
                onRetry={fetchChart}
                className="h-[300px] border-0 shadow-none p-0"
              />
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart
                  key={animKey}
                  data={chartPoints}
                  margin={{ top: 16, right: 16, left: 0, bottom: 24 }}
                  style={{ cursor: "pointer" }}
                >
                  <CartesianGrid
                    strokeDasharray="0"
                    horizontal
                    vertical={false}
                    stroke="var(--border)"
                    strokeOpacity={0.8}
                  />
                  <XAxis
                    dataKey="label"
                    tick={<YearBreakTick chartPoints={chartPoints} granularity={granularity} />}
                    axisLine={false}
                    tickLine={false}
                    dy={6}
                    interval="preserveStartEnd"
                    minTickGap={10}
                    height={48}
                  />
                  <YAxis
                    tickFormatter={v => fmt(v)}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)", fontFamily: "var(--font-sans)" }}
                    axisLine={false}
                    tickLine={false}
                    width={70}
                    domain={([0, chartMax === undefined ? 'auto' : chartMax]) as any}
                  />
                  <Tooltip content={<CashFlowTooltip />} cursor={{ fill: "var(--border)", fillOpacity: 0.4 }} />

                  {/* Year-break reference lines (skip in yearly mode) */}
                  {granularity !== "yearly" && yearBreaks.map((brk) => (
                    <ReferenceLine
                      key={`yr-break-${brk.label}`}
                      x={brk.label}
                      stroke="var(--muted-foreground)"
                      strokeWidth={1}
                      strokeOpacity={0.2}
                      strokeDasharray="4 3"
                    />
                  ))}

                  {/* Active period reference line */}
                  {activeLabel && (
                    <ReferenceLine
                      x={activeLabel}
                      stroke="var(--color-gain)"
                      strokeWidth={2}
                      strokeDasharray="4 2"
                      strokeOpacity={0.5}
                    />
                  )}

                  {/* Income bars */}
                  <Bar
                    dataKey="income"
                    name="Income"
                    fill="var(--color-gain)"
                    fillOpacity={0.65}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={maxBarSize}
                    onClick={handleBarSegmentClick}
                    style={{ cursor: "pointer" }}
                  />

                  {/* Expense bars */}
                  <Bar
                    dataKey="spending"
                    name="Expenses"
                    fill="var(--color-loss)"
                    fillOpacity={0.65}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={maxBarSize}
                    onClick={handleBarSegmentClick}
                    style={{ cursor: "pointer" }}
                  />

                  {/* Net savings — solid trend line (all but last point) */}
                  <Line
                    dataKey="netSolid"
                    name="Net (solid)"
                    type="monotone"
                    stroke="var(--foreground)"
                    strokeWidth={2}
                    dot={false}
                    activeDot={false}
                    connectNulls={false}
                    legendType="none"
                    isAnimationActive={true}
                    animationDuration={1200}
                    animationEasing="ease-out"
                  />

                  {/* Net savings — dotted trend line (second-to-last → last) */}
                  <Line
                    dataKey="netDotted"
                    name="Net (current)"
                    type="monotone"
                    stroke="var(--foreground)"
                    strokeWidth={2}
                    strokeDasharray="6 4"
                    dot={(props: any) => {
                      // Only show dot on the last point (current period)
                      const isLast = props.index === chartPoints.length - 1;
                      if (!isLast) return <circle key={props.key} cx={0} cy={0} r={0} fill="none" />;
                      return (
                        <circle
                          key={props.key}
                          cx={props.cx}
                          cy={props.cy}
                          r={4}
                          fill="var(--foreground)"
                          strokeWidth={0}
                        />
                      );
                    }}
                    activeDot={{ r: 5 }}
                    connectNulls={false}
                    legendType="none"
                    isAnimationActive={true}
                    animationDuration={800}
                    animationBegin={1000}
                    animationEasing="ease-out"
                  />

                  {/* Invisible line for the solid dots up to second-to-last */}
                  <Line
                    dataKey="netSolid"
                    name="Net"
                    type="monotone"
                    stroke="none"
                    strokeWidth={0}
                    dot={({ cx, cy, index, payload }: any) => {
                      if (payload?.netSolid == null) return <circle key={`dot-${index}`} cx={0} cy={0} r={0} fill="none" />;
                      return (
                        <circle
                          key={`dot-${index}`}
                          cx={cx}
                          cy={cy}
                          r={3}
                          fill="var(--foreground)"
                          strokeWidth={0}
                        />
                      );
                    }}
                    activeDot={false}
                    legendType="none"
                    isAnimationActive={false}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            )}

            {/* Legend */}
            <div className="flex items-center justify-center gap-6 mt-2">
              {[
                { color: String(gainColor), label: "Income", opacity: "0.65" },
                { color: String(lossColor), label: "Expenses", opacity: "0.65" },
                { color: "var(--foreground)", label: "Net Savings", opacity: "1", isLine: true },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-1.5">
                  {item.isLine ? (
                    <div className="w-5 h-0.5 rounded-full" style={{ background: item.color }} />
                  ) : (
                    <div
                      className="size-3 rounded-sm"
                      style={{ background: item.color, opacity: item.opacity }}
                    />
                  )}
                  <span className="text-[11px] text-muted-foreground font-medium">{item.label}</span>
                </div>
              ))}
            </div>
            {granularity === "monthly" && chartPoints.length > 0 && (
              <div className="sr-only">
                <span data-testid="cash-flow-chart-monthly-points">
                  {chartPoints.map(p =>
                    `${p.label}: income ${fmtFull(p.income)}; expenses ${fmtFull(p.spending)}; net ${p.net >= 0 ? "+" : ""}${fmtFull(p.net)}; savings ${p.savings_rate.toFixed(1)}%`
                  ).join(" | ")}
                </span>
                <span data-testid="cash-flow-rolling-latest-month">
                  {(() => {
                    const latest = chartPoints[chartPoints.length - 1];
                    return latest
                      ? `${latest.label}: income ${fmtFull(latest.income)}; expenses ${fmtFull(latest.spending)}; net ${latest.net >= 0 ? "+" : ""}${fmtFull(latest.net)}; savings ${latest.savings_rate.toFixed(1)}%`
                      : "";
                  })()}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ── Period Summary Row ────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-[15px] font-bold text-foreground">
              {activePeriod?.label ?? "—"}
            </h2>
            {!isViewingCurrent && (
              <button
                onClick={resetToCurrent}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary/10 border border-primary/30 text-[11px] font-semibold text-primary hover:bg-primary/20 transition-colors"
              >
                <span className="material-symbols-outlined text-[13px]">arrow_forward</span>
                Current {granularity === "monthly" ? "month" : granularity === "quarterly" ? "quarter" : "year"}
                <span className="material-symbols-outlined text-[13px] opacity-60 hover:opacity-100">close</span>
              </button>
            )}
          </div>
          <span className="text-[11px] text-muted-foreground font-medium">
            {isViewingCurrent ? "Click a bar to drill down" : "Click again to deselect"}
          </span>
        </div>

        {/* ── KPI Cards ─────────────────────────────────────────────────────── */}
        {detailLoading ? (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {[0,1,2,3,4].map(i => (
              <Skeleton key={i} className="h-[90px] rounded-xl" />
            ))}
          </div>
        ) : detailError ? (
          <ErrorState
            title="Couldn't load period detail"
            description={detailError.message || "Network error"}
            onRetry={fetchDetail}
          />
        ) : detail ? (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            <KpiCard
              label="INCOME"
              value={fmtFull(detail.income)}
              color="text-[var(--color-gain)]"
              testId="cash-flow-current-income"
            />
            <KpiCard
              label="EXPENSES"
              value={fmtFull(detail.spending)}
              color="text-[var(--color-loss)]"
              testId="cash-flow-current-spending"
            />
            <KpiCard
              label="NET SAVINGS"
              value={(detail.net >= 0 ? "+" : "") + fmtFull(detail.net)}
              color={detail.net >= 0 ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"}
              testId="cash-flow-current-net"
            />
            <KpiCard
              label="SAVINGS RATE"
              value={`${detail.savings_rate.toFixed(1)}%`}
              color={detail.savings_rate >= 0 ? "text-[var(--chart-c2)]" : "text-[var(--color-loss)]"}
              subtitle="Net / gross income"
              testId="cash-flow-current-savings-rate"
            />
            <KpiCard
              label="DEBT SERVICE"
              value={fmtFull(detail.debt_service)}
              color="text-[var(--color-warning)]"
              testId="cash-flow-current-debt-service"
              subtitleTestId="cash-flow-current-debt-service-percent"
              subtitle={
                detail.spending > 0
                  ? `${(detail.debt_service / detail.spending * 100).toFixed(1)}% of spending`
                  : "—"
              }
            />
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
            {["INCOME","EXPENSES","NET SAVINGS","SAVINGS RATE","DEBT SERVICE"].map(l => (
              <div key={l} className="card-l1 px-5 py-4 flex flex-col gap-1">
                <p className="text-2xl font-extrabold text-muted-foreground/30">—</p>
                <p className="text-label">{l}</p>
              </div>
            ))}
          </div>
        )}

        {/* ── Category Breakdowns ───────────────────────────────────────────── */}
        {detail && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <CategorySection
              title="Income"
              total={detail.income}
              rows={detail.income_categories}
              colorVar="var(--color-gain)"
              totalIncome={detail.income}
            />
            <CategorySection
              title="Expenses"
              total={detail.spending}
              rows={detail.spending_categories}
              colorVar="var(--color-loss)"
              totalIncome={detail.spending}
            />
          </div>
        )}

        {/* ── Debt-to-Income Panel ──────────────────────────────────────────── */}
        <DebtToIncomePanel data={dtiSeries} loading={dtiLoading} />

        {/* ── Debt Accumulation Panel ───────────────────────────────────────── */}
        {/* Derived from chartPoints (monthly granularity only) — no extra fetch.
            Trailing 12 months of net debt change, with the latest month broken
            down into "purchased on credit" and "paid toward debt" tiles. */}
        <DebtAccumulationPanel
          data={
            granularity === "monthly"
              ? chartPoints.slice(-12).map(p => ({
                  label: p.label,
                  year: p.year,
                  month: p.index,
                  debt_accumulated: p.debt_accumulated ?? 0,
                  debt_paid_down: p.debt_paid_down ?? 0,
                  net_debt_change: p.net_debt_change ?? 0,
                }))
              : null
          }
          loading={chartLoading}
        />

        {/* Bottom padding */}
        <div className="h-4" />
      </motion.div>

      {/* ── Filter Drawer — only mounted when open ───────────────────────── */}
      {filterOpen && (
        <FilterDrawer
          open={filterOpen}
          onClose={() => setFilterOpen(false)}
          accountId={accountId}
          onAccountChange={setAccountId}
        />
      )}
    </motion.div>
  );
}
