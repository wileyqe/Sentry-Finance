import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Label,
} from "recharts";
import { motion } from "framer-motion";

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

const ACCOUNT_NAMES: Record<string, string> = {
  chase_chk_001:   "Chase Total Checking",
  nfcu_sav_001:    "NFCU Emergency Savings",
  chase_cc_001:    "Sapphire Reserve",
  amex_cc_001:     "Blue Cash Preferred",
  rocket_mtg_001:  "Home Mortgage",
  fidelity_inv_001:"Individual Brokerage",
  acorns_inv_001:  "Acorns Invest",
};

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

const fmt = (v: number) =>
  "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 });

const fmtFull = (v: number) =>
  "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

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
}

/* ── Custom Tooltip ─────────────────────────────────────────────────────────── */

function CashFlowTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as ChartPoint;
  if (!d) return null;

  const netPositive = d.net >= 0;

  return (
    <div className="bg-slate-900 dark:bg-slate-950 border border-slate-700 rounded-xl px-4 py-3 shadow-xl min-w-[180px]">
      <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">{label}</p>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-slate-400">Income</span>
          <span className="text-xs font-bold text-[var(--color-gain)] text-numeric">{fmtFull(d.income)}</span>
        </div>
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-slate-400">Expenses</span>
          <span className="text-xs font-bold text-[var(--color-loss)] text-numeric">{fmtFull(d.spending)}</span>
        </div>
        <div className="border-t border-slate-700 mt-1 pt-1 flex items-center justify-between gap-6">
          <span className="text-xs text-slate-400">Net</span>
          <span className={`text-xs font-bold text-numeric ${netPositive ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"}`}>
            {netPositive ? "+" : "-"}{fmtFull(d.net)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-6">
          <span className="text-xs text-slate-400">Savings Rate</span>
          <span className="text-xs font-bold text-slate-200 text-numeric">{d.savings_rate.toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}

/* ── KPI Card ───────────────────────────────────────────────────────────────── */

function KpiCard({ label, value, color, subtitle }: { label: string; value: string; color: string; subtitle?: string }) {
  return (
    <div className="card-l1 px-5 py-4 flex flex-col gap-1">
      <p className={`text-2xl font-extrabold text-numeric tracking-tight leading-none ${color}`}>{value}</p>
      {subtitle && <p className="text-[11px] text-muted-foreground font-medium">{subtitle}</p>}
      <p className="text-label mt-0.5">{label}</p>
    </div>
  );
}

/* ── Category Row ───────────────────────────────────────────────────────────── */

function CategoryRowItem({ cat, total, pct, colorVar }: { cat: string; total: number; pct: number; colorVar: string }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors rounded-lg group">
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
        <div className="mt-1 h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${Math.min(pct, 100)}%`, background: colorVar }}
          />
        </div>
      </div>

      {/* Amount + pct */}
      <div className="text-right shrink-0">
        <p className="text-[13px] font-semibold text-numeric text-foreground">{fmtFull(total)}</p>
        <p className="text-[10px] text-muted-foreground">{pct.toFixed(1)}%</p>
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

  return (
    <div className="card-l1 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed(c => !c)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
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
            <div className="flex items-center justify-center py-8 text-muted-foreground">
              <p className="text-sm">No data for this period</p>
            </div>
          ) : (
            <div className="px-2 pb-2 divide-y divide-slate-100 dark:divide-slate-800/50">
              {rows.map((r) => (
                <CategoryRowItem
                  key={r.category}
                  cat={r.category}
                  total={r.total}
                  pct={totalIncome > 0 ? (r.total / totalIncome) * 100 : r.pct}
                  colorVar={colorVar}
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
        className={`fixed right-0 top-0 z-40 h-full w-72 bg-white dark:bg-[#0f1117] border-l border-slate-200 dark:border-slate-800 flex flex-col shadow-xl transition-transform duration-300 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-800">
          <span className="font-bold text-base">Filters</span>
          <button onClick={onClose} className="text-slate-400 hover:text-foreground transition-colors">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">
          {/* Account filter */}
          <div>
            <p className="text-label mb-2">Account</p>
            <select
              className="w-full h-9 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 text-sm font-medium outline-none focus:ring-2 focus:ring-emerald-500/30 cursor-pointer"
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

        <div className="p-5 border-t border-slate-100 dark:border-slate-800 flex gap-3">
          <button
            onClick={() => { onAccountChange(""); onClose(); }}
            className="flex-1 h-9 rounded-lg border border-slate-200 dark:border-slate-700 text-sm font-semibold text-slate-500 hover:text-foreground transition-colors"
          >
            Reset
          </button>
          <button
            onClick={onClose}
            className="flex-1 h-9 rounded-lg bg-[var(--primary)] text-white text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            Apply
          </button>
        </div>
      </div>
    </>
  );
}

/* ── Animated Trend Line ────────────────────────────────────────────────────── */

function AnimatedLine(props: any) {
  const ref = useRef<SVGPathElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const length = el.getTotalLength();
    el.style.setProperty("--line-length", String(length));
    el.style.strokeDasharray = String(length);
    el.style.strokeDashoffset = String(length);

    // Force reflow to restart animation
    void el.getBoundingClientRect();
    el.style.animation = "none";
    void el.getBoundingClientRect();
    el.style.animation = `draw-line 1.2s ease-out forwards`;
  }, [props.d]);

  return <path {...props} ref={ref} className="cashflow-trend-line" />;
}

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
        {payload.value}
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
  const today = new Date();
  const [granularity, setGranularity] = useState<Granularity>("monthly");
  const [accountId, setAccountId] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);

  // Chart data
  const [chartPoints, setChartPoints] = useState<ChartPoint[]>([]);
  const [chartLoading, setChartLoading] = useState(true);

  // Active period (set by bar click or defaults to current/rightmost period)
  const [activePeriod, setActivePeriod] = useState<{ index: number; year: number; label: string } | null>(null);

  // Detail data for the active period
  const [detail, setDetail] = useState<PeriodDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Animation key — bumped to force re-animation on data change
  const [animKey, setAnimKey] = useState(0);

  // ── Fetch chart data ─────────────────────────────────────────────────────
  const fetchChart = useCallback(() => {
    setChartLoading(true);
    const acctParam = accountId ? `?account_id=${accountId}` : "";
    const acctParamAmp = accountId ? `&account_id=${accountId}` : "";

    let url: string;
    if (granularity === "monthly") {
      url = `${API}/api/cash-flow/monthly-rolling${acctParam}`;
    } else if (granularity === "quarterly") {
      url = `${API}/api/cash-flow/quarterly-rolling${acctParam}`;
    } else {
      url = `${API}/api/cash-flow/yearly${acctParam}`;
    }

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
          let yearData = (d.years as any[]).filter((y: any) => y.year <= today.getFullYear());
          // Only keep years with data, max 4, min 2
          yearData = yearData.filter((y: any) => y.income > 0 || y.spending > 0);
          if (yearData.length > 4) yearData = yearData.slice(-4);
          if (yearData.length < 2) {
            // Pad with current and previous year
            const currentYear = today.getFullYear();
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
      .catch(e => { console.error(e); setChartLoading(false); });
  }, [granularity, accountId]);

  useEffect(() => { fetchChart(); }, [fetchChart]);

  // ── Fetch period detail ──────────────────────────────────────────────────
  const fetchDetail = useCallback(() => {
    if (!activePeriod) return;
    setDetailLoading(true);

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

    const acctParam = accountId ? `&account_id=${accountId}` : "";
    fetch(`${API}/api/cash-flow/period?start=${start}&end=${end}${acctParam}`)
      .then(r => r.json())
      .then(d => { setDetail(d); setDetailLoading(false); })
      .catch(e => { console.error(e); setDetailLoading(false); });
  }, [activePeriod, granularity, accountId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

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
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto"
    >

      {/* ── Sticky Header ──────────────────────────────────────────────────── */}
      <motion.div variants={itemVariants} className="sticky top-0 z-20 bg-background border-b border-border px-12 py-3 flex items-center justify-between gap-4">
        <h1 className="text-xl font-bold tracking-tight">Cash Flow</h1>

        <div className="flex items-center gap-3">
          {/* Granularity toggle */}
          <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5">
            {(["monthly", "quarterly", "yearly"] as Granularity[]).map(g => (
              <button
                key={g}
                onClick={() => setGranularity(g)}
                className={`px-4 py-1.5 rounded-full text-[12.5px] font-semibold transition-all duration-150 capitalize ${
                  granularity === g
                    ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
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
                ? "bg-emerald-50 dark:bg-emerald-500/10 border-emerald-400/40 text-emerald-600 dark:text-emerald-400"
                : "border-border text-muted-foreground hover:text-foreground hover:border-slate-300 dark:hover:border-slate-600"
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">filter_list</span>
            Filters
            {accountId && <span className="size-2 rounded-full bg-emerald-500" />}
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
                    interval={0}
                    height={48}
                  />
                  <YAxis
                    tickFormatter={v => fmt(v)}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)", fontFamily: "var(--font-sans)" }}
                    axisLine={false}
                    tickLine={false}
                    width={70}
                    domain={[0, chartMax]}
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
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-400/30 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 transition-colors"
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
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[0,1,2,3].map(i => (
              <div key={i} className="card-l1 px-5 py-4 h-[90px] animate-pulse bg-slate-100 dark:bg-slate-800/40" />
            ))}
          </div>
        ) : detail ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              label="INCOME"
              value={fmtFull(detail.income)}
              color="text-[var(--color-gain)]"
            />
            <KpiCard
              label="EXPENSES"
              value={fmtFull(detail.spending)}
              color="text-[var(--color-loss)]"
            />
            <KpiCard
              label="NET SAVINGS"
              value={(detail.net >= 0 ? "+" : "-") + fmtFull(detail.net)}
              color={detail.net >= 0 ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]"}
            />
            <KpiCard
              label="SAVINGS RATE"
              value={`${detail.savings_rate.toFixed(1)}%`}
              color={detail.savings_rate >= 0 ? "text-[var(--chart-c2)]" : "text-[var(--color-loss)]"}
              subtitle={`Net: ${detail.savings_rate.toFixed(1)}%  /  Gross: ${detail.gross_savings_rate.toFixed(1)}%`}
            />
          </div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {["INCOME","EXPENSES","NET SAVINGS","SAVINGS RATE"].map(l => (
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
