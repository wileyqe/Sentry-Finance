import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import CustomReportsTab from "../components/CustomReportsTab";


/* ── Constants ─────────────────────────────────────────────────────────────── */

const ACCOUNT_NAMES: Record<string, string> = {
  chase_chk_001: "Chase Total Checking",
  nfcu_sav_001: "NFCU Emergency Savings",
  chase_cc_001: "Sapphire Reserve",
  amex_cc_001: "Blue Cash Preferred",
  rocket_mtg_001: "Home Mortgage",
  fidelity_inv_001: "Individual Brokerage",
  acorns_inv_001: "Acorns Invest",
};

const CATEGORIES = [
  "Income", "Paychecks/Salary", "Interest", "Investment Income",
  "Mortgage", "Transfer", "Groceries", "Dining", "Shopping",
  "Entertainment", "Travel", "Utilities", "Auto", "Medical", "Insurance",
  "Home Improvement", "Uncategorized", "Other Income",
];

const TF_MAP: Record<string, number> = {
  "Last 30 Days": 1,
  "Last 3 Months": 3,
  "Last 6 Months": 6,
  "Year to Date": 12,
  "All Time": 120,
};

/* Desaturated chart palette — matches CSS tokens in index.css */
const INCOME_COLORS = [
  "oklch(0.52 0.13 155)",  // emerald — primary
  "oklch(0.52 0.10 185)",  // teal
  "oklch(0.52 0.12 240)",  // steel blue
  "oklch(0.50 0.08 90)",   // olive
];
const SPEND_COLORS = [
  "oklch(0.52 0.12 240)",  // steel blue
  "oklch(0.52 0.11 290)",  // indigo
  "oklch(0.55 0.11 45)",   // amber
  "oklch(0.48 0.13 20)",   // terracotta
  "oklch(0.52 0.10 185)",  // teal
  "oklch(0.50 0.09 320)",  // mauve
  "oklch(0.50 0.08 90)",   // olive
  "oklch(0.52 0.13 155)",  // emerald
  "oklch(0.46 0.12 25)",   // rose
  "oklch(0.54 0.10 270)",  // slate-blue
  "oklch(0.50 0.11 60)",   // yellow-olive
  "oklch(0.52 0.09 210)",  // cyan
];

/* ── Helpers ───────────────────────────────────────────────────────────────── */

const fmt = (v: number) =>
  "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const pct = (v: number, total: number) =>
  total > 0 ? ((v / total) * 100).toFixed(2) + "%" : "0%";

/* SVG curved link path for Sankey */
function sankeyLinkPath(
  sx: number, sy: number, sh: number,
  tx: number, ty: number, th: number,
): string {
  const mx = (sx + tx) / 2;
  return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}
          L${tx},${ty + th} C${mx},${ty + th} ${mx},${sy + sh} ${sx},${sy + sh} Z`;
}

/* ── Custom SVG Sankey ─────────────────────────────────────────────────────── */

interface SankeyNodeData {
  name: string;
  value: number;
  color: string;
  side: "income" | "hub" | "spending";
  pctLabel: string;
}

function SankeyChart({
  incomeNodes,
  spendNodes,
  totalIncome,
  totalSpending: _ts,
  savings,
  activeNode,
  onNodeClick,
  containerWidth,
}: {
  incomeNodes: SankeyNodeData[];
  spendNodes: SankeyNodeData[];
  totalIncome: number;
  totalSpending: number;
  savings: number;
  activeNode: string | null;
  onNodeClick: (name: string, side: string) => void;
  containerWidth: number;
}) {
  /* ── Layout constants ─────────────────────────────────────────────────── */
  const NODE_W = 22;
  const NODE_PAD = 12;
  const MIN_NODE_H = 20;
  const LABEL_W = 200; // space for labels outside the chart
  const LABEL_PAD = 50; // extra vertical padding for bottom labels

  // Use full container width with proportional columns
  const svgW = Math.max(800, containerWidth);

  // 3 columns spread across the full width
  // Income labels ← [col0] ==flow== [col1 hub] ==flow== [col2] → Spending labels
  const col0x = LABEL_W;                          // ~200px from left
  const col2x = svgW - LABEL_W - NODE_W;          // ~200px from right
  const col1x = (col0x + NODE_W + col2x) / 2;     // centered between col0 and col2

  /* ── Compute node heights ─────────────────────────────────────────────── */
  const PAD_Y = 40;
  const incomeTotal = incomeNodes.reduce((s, n) => s + n.value, 0);
  const spendTotal = spendNodes.reduce((s, n) => s + n.value, 0) + savings;
  const maxColumn = Math.max(incomeTotal, spendTotal, totalIncome);

  // Dynamic height based on node count — constrain it so it doesn't blow up vertically
  const nodesCount = Math.max(incomeNodes.length, spendNodes.length + (savings > 0 ? 1 : 0));
  const chartH = Math.max(400, Math.min(650, nodesCount * 45 + 100));
  const innerH = chartH - PAD_Y * 2;

  const scaleH = (val: number) => Math.max(MIN_NODE_H, (val / maxColumn) * (innerH - NODE_PAD * nodesCount));

  // Lay out income nodes
  let incY = PAD_Y;
  const incomeLayout = incomeNodes.map(n => {
    const h = scaleH(n.value);
    const y = incY;
    incY += h + NODE_PAD;
    return { ...n, x: col0x, y, h };
  });

  // Hub node
  const hubH = scaleH(totalIncome);
  const hubY = PAD_Y + (innerH - hubH) / 2; // center vertically

  // Spending nodes + savings
  const allSpend = [...spendNodes.map(n => ({ ...n }))];
  if (savings > 0) {
    allSpend.unshift({
      name: "Savings",
      value: savings,
      color: "oklch(0.52 0.12 240)",
      side: "spending" as const,
      pctLabel: pct(savings, totalIncome),
    });
  }

  let spY = PAD_Y;
  const spendLayout = allSpend.map(n => {
    const h = scaleH(n.value);
    const y = spY;
    spY += h + NODE_PAD;
    return { ...n, x: col2x, y, h };
  });

  // Total SVG height — include extra padding for bottom labels
  const svgH = Math.max(chartH, incY + LABEL_PAD, spY + LABEL_PAD);

  /* ── Build links ──────────────────────────────────────────────────────── */
  // Income → Hub links
  let hubSourceY = hubY;
  const incomeLinks = incomeLayout.map(n => {
    const linkH = (n.value / totalIncome) * hubH;
    const link = {
      sx: n.x + NODE_W, sy: n.y, sh: n.h,
      tx: col1x, ty: hubSourceY, th: linkH,
      color: n.color,
      name: n.name,
      side: n.side,
    };
    hubSourceY += linkH;
    return link;
  });

  // Hub → Spending links
  let hubTargetY = hubY;
  const spendLinks = spendLayout.map(n => {
    const linkH = (n.value / totalIncome) * hubH;
    const link = {
      sx: col1x + NODE_W, sy: hubTargetY, sh: linkH,
      tx: n.x, ty: n.y, th: n.h,
      color: n.color,
      name: n.name,
      side: n.side,
    };
    hubTargetY += linkH;
    return link;
  });

  /* ── Render ───────────────────────────────────────────────────────────── */
  const isActive = (name: string) => activeNode === name;

  return (
    <svg
      width={svgW}
      height={svgH}
      viewBox={`0 0 ${svgW} ${svgH}`}
      style={{ display: "block", margin: "0 auto", maxWidth: "100%" }}
    >
      <defs>
        {[...incomeLinks, ...spendLinks].map((l, i) => (
          <linearGradient key={`grad-${i}`} id={`link-grad-${i}`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor={l.color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={l.color} stopOpacity={0.12} />
          </linearGradient>
        ))}
      </defs>

      {/* ── Links ──────────────────────────────────────────────────────── */}
      {incomeLinks.map((l, i) => (
        <path
          key={`il-${i}`}
          d={sankeyLinkPath(l.sx, l.sy, l.sh, l.tx, l.ty, l.th)}
          fill={`url(#link-grad-${i})`}
          stroke={l.color}
          strokeWidth={0.5}
          strokeOpacity={0.2}
          style={{
            cursor: "pointer",
            opacity: activeNode && !isActive(l.name) ? 0.25 : 1,
            transition: "opacity 0.3s",
          }}
          onClick={() => onNodeClick(l.name, "income")}
        />
      ))}
      {spendLinks.map((l, i) => (
        <path
          key={`sl-${i}`}
          d={sankeyLinkPath(l.sx, l.sy, l.sh, l.tx, l.ty, l.th)}
          fill={`url(#link-grad-${incomeLinks.length + i})`}
          stroke={l.color}
          strokeWidth={0.5}
          strokeOpacity={0.2}
          style={{
            cursor: "pointer",
            opacity: activeNode && !isActive(l.name) ? 0.25 : 1,
            transition: "opacity 0.3s",
          }}
          onClick={() => onNodeClick(l.name, l.side)}
        />
      ))}

      {/* ── Income nodes (left column) ─────────────────────────────────── */}
      {incomeLayout.map((n, i) => (
        <g key={`in-${i}`} style={{ cursor: "pointer" }} onClick={() => onNodeClick(n.name, "income")}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            rx={4} ry={4}
            fill={isActive(n.name) ? "#fff" : n.color}
            stroke={isActive(n.name) ? n.color : "none"}
            strokeWidth={2.5}
            style={{
              filter: isActive(n.name) ? `drop-shadow(0 0 8px ${n.color}80)` : "none",
              opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
              transition: "all 0.3s",
            }}
          />
          {/* Label — left side of income nodes */}
          <circle cx={n.x - 14} cy={n.y + 12} r={5} fill={n.color}
            style={{ opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "opacity 0.3s" }} />
          <text x={n.x - 24} y={n.y + 13} textAnchor="end" dominantBaseline="central"
            style={{
              fontSize: 13, fontWeight: 700,
              fill: isActive(n.name) ? n.color : "#334155",
              opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
              transition: "all 0.3s",
            }}>
            {n.name}
          </text>
          <text x={n.x - 24} y={n.y + 30} textAnchor="end" dominantBaseline="central"
            style={{
              fontSize: 11, fontWeight: 600, fill: "#64748b",
              opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
              transition: "opacity 0.3s",
            }}>
            {fmt(n.value)} ({n.pctLabel})
          </text>
        </g>
      ))}

      {/* ── Hub node (center) ──────────────────────────────────────────── */}
      <g>
        <rect
          x={col1x} y={hubY} width={NODE_W} height={hubH}
          rx={4} ry={4}
          fill="oklch(0.52 0.13 155)"
        />
        <text x={col1x + NODE_W / 2} y={hubY + hubH / 2 - 10} textAnchor="middle" dominantBaseline="central"
          style={{ fontSize: 14, fontWeight: 800, fill: "#0f172a" }}>
          Income
        </text>
        <text x={col1x + NODE_W / 2} y={hubY + hubH / 2 + 10} textAnchor="middle" dominantBaseline="central"
          style={{ fontSize: 11, fontWeight: 600, fill: "#475569" }}>
          {fmt(totalIncome)}
        </text>
      </g>

      {/* ── Spending nodes (right column) ──────────────────────────────── */}
      {spendLayout.map((n, i) => {
        const clickSide = n.name === "Savings" ? "spending" : n.side;
        return (
          <g key={`sp-${i}`} style={{ cursor: "pointer" }} onClick={() => onNodeClick(n.name, clickSide)}>
            <rect
              x={n.x} y={n.y} width={NODE_W} height={n.h}
              rx={4} ry={4}
              fill={isActive(n.name) ? "#fff" : n.color}
              stroke={isActive(n.name) ? n.color : "none"}
              strokeWidth={2.5}
              style={{
                filter: isActive(n.name) ? `drop-shadow(0 0 8px ${n.color}80)` : "none",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
                transition: "all 0.3s",
              }}
            />
            {/* Label — right side of spending nodes */}
            <circle cx={n.x + NODE_W + 14} cy={n.y + 12} r={5} fill={n.color}
              style={{ opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "opacity 0.3s" }} />
            <text x={n.x + NODE_W + 24} y={n.y + 13} textAnchor="start" dominantBaseline="central"
              style={{
                fontSize: 13, fontWeight: 700,
                fill: isActive(n.name) ? n.color : "#334155",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
                transition: "all 0.3s",
              }}>
              {n.name}
            </text>
            <text x={n.x + NODE_W + 24} y={n.y + 30} textAnchor="start" dominantBaseline="central"
              style={{
                fontSize: 11, fontWeight: 600, fill: "#64748b",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1,
                transition: "opacity 0.3s",
              }}>
              {fmt(n.value)} ({n.pctLabel})
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* ── Main Component ────────────────────────────────────────────────────────── */

export default function ReportsPage() {
  const [reportTab, setReportTab] = useState<"cash_flow" | "custom_reports">("cash_flow");
  const [timeframe, setTimeframe] = useState("Last 3 Months");

  const [flowData, setFlowData] = useState<any>(null);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [activeFilter, setActiveFilter] = useState<{ name: string; side: string } | null>(null);
  const [editingTxId, setEditingTxId] = useState<string | null>(null);
  const txListRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(1000);
  const chartContainerRef = useRef<HTMLDivElement>(null);

  // Responsive width
  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      for (const e of entries) setContainerWidth(e.contentRect.width);
    });
    if (chartContainerRef.current) obs.observe(chartContainerRef.current);
    return () => obs.disconnect();
  }, []);

  // Fetch flow data
  const fetchFlow = useCallback(() => {
    const months = TF_MAP[timeframe] || 1;
    fetch(`http://127.0.0.1:8000/api/reports/flow?months=${months}`)
      .then(r => r.json())
      .then(setFlowData)
      .catch(console.error);
  }, [timeframe]);
  useEffect(() => { fetchFlow(); }, [fetchFlow]);

  // Fetch transactions for the period
  const fetchTransactions = useCallback(() => {
    const months = TF_MAP[timeframe] || 1;
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    const sd = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-01`;
    const ed = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    fetch(`http://127.0.0.1:8000/api/transactions?limit=1000&start_date=${sd}&end_date=${ed}`)
      .then(r => r.json())
      .then(d => setTransactions(d.transactions || []))
      .catch(console.error);
  }, [timeframe]);
  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

  /* ── Build Sankey node data ─────────────────────────────────────────────── */
  const sankeyData = useMemo(() => {
    if (!flowData) return null;
    const incCats = (flowData.income_categories || []) as any[];
    const spdCats = (flowData.spending_categories || []) as any[];
    const totalIncome = flowData.total_income || 0;
    const totalSpending = flowData.total_spending || 0;
    const savings = Math.max(0, totalIncome - totalSpending);

    const incomeNodes: SankeyNodeData[] = incCats.map((c: any, i: number) => ({
      name: c.category,
      value: c.total,
      color: INCOME_COLORS[i % INCOME_COLORS.length],
      side: "income" as const,
      pctLabel: pct(c.total, totalIncome),
    }));

    const spendNodes: SankeyNodeData[] = spdCats.map((c: any, i: number) => ({
      name: c.category,
      value: c.total,
      color: SPEND_COLORS[i % SPEND_COLORS.length],
      side: "spending" as const,
      pctLabel: pct(c.total, totalSpending),
    }));

    return { incomeNodes, spendNodes, totalIncome, totalSpending, savings };
  }, [flowData]);

  /* ── Filtered transactions ──────────────────────────────────────────────── */
  const filteredTx = activeFilter
    ? transactions.filter(tx => {
        if (activeFilter.name === "Savings") return false; // savings is virtual
        const amt = tx.signed_amount ?? tx.amount;
        if (activeFilter.side === "income") {
          // Income: positive signed_amount, match category
          return amt > 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Other Income"));
        }
        // Spending: negative signed_amount, match category
        return amt < 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Uncategorized"));
      })
    : transactions;

  // Auto-scroll when filter changes
  useEffect(() => {
    if (activeFilter && txListRef.current) {
      setTimeout(() => {
        txListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    }
  }, [activeFilter]);

  /* ── Summary stats ──────────────────────────────────────────────────────── */
  const summary = useMemo(() => {
    if (filteredTx.length === 0) return null;
    const amounts = filteredTx.map(t => t.signed_amount ?? t.amount);
    const absAmounts = amounts.map(Math.abs);
    const totalAbs = absAmounts.reduce((s, v) => s + v, 0);
    const dates = filteredTx.map(t => t.posting_date).filter(Boolean).sort();
    return {
      count: filteredTx.length,
      largest: Math.max(...absAmounts),
      average: totalAbs / filteredTx.length,
      total: totalAbs,
      first: dates[0],
      last: dates[dates.length - 1],
    };
  }, [filteredTx]);

  /* ── Inline category edit ───────────────────────────────────────────────── */
  const handleCategoryPatch = (txId: string, newCat: string) => {
    setTransactions(prev => prev.map(t => t.id === txId ? { ...t, category: newCat } : t));
    setEditingTxId(null);
    fetch(`http://127.0.0.1:8000/api/transactions/${txId}/category?category=${encodeURIComponent(newCat)}`, { method: "PATCH" })
      .catch(console.error);
    setTimeout(fetchFlow, 500);
  };

  /* ── Node click handler ─────────────────────────────────────────────────── */
  const onNodeClick = (name: string, side: string) => {
    if (activeFilter?.name === name) {
      setActiveFilter(null);
    } else {
      setActiveFilter({ name, side });
    }
  };

  /* ── Timeframe label ────────────────────────────────────────────────────── */
  const timeLabel = useMemo(() => {
    const months = TF_MAP[timeframe] || 1;
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    const fmtDate = (d: Date) => `${d.toLocaleString("en-US", { month: "short" })} ${d.getDate()}, ${d.getFullYear()}`;
    return `${fmtDate(start)} – ${fmtDate(end)}`;
  }, [timeframe]);

  /* ── Render ──────────────────────────────────────────────────────────────── */
  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar">

      {/* ── Page header with subtabs + timeframe ─────────────────────────── */}
      <div className="px-6 pt-5 pb-0 flex items-center justify-between gap-4 border-b border-slate-100 dark:border-slate-800">
        {/* Subtab pills */}
        <div className="flex gap-1">
          {(["cash_flow", "custom_reports"] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setReportTab(tab)}
              className={`px-4 py-2 text-xs font-bold rounded-t-lg border-b-2 transition-all ${
                reportTab === tab
                  ? "border-primary text-primary bg-primary/5"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/40"
              }`}
            >
              {tab === "cash_flow" ? "Cash Flow" : "Custom Reports"}
            </button>
          ))}
        </div>
        {/* Shared timeframe selector */}
        <select
          className="bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer mb-1"
          value={timeframe}
          onChange={e => { setTimeframe(e.target.value); setActiveFilter(null); }}
        >
          {Object.keys(TF_MAP).map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {/* ── Custom Reports Tab ────────────────────────────────────────────── */}
      {reportTab === "custom_reports" && (
        <div className="pt-4">
          <CustomReportsTab timeframe={timeframe} />
        </div>
      )}

      {/* ── Cash Flow Tab ─────────────────────────────────────────────────── */}
      {reportTab === "cash_flow" && (
      <>
      {/* ── Summary cards row ──────────────────────────────────────────────── */}

      <div className="px-6 pt-4 pb-2 grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Total Income",     value: flowData?.total_income,   color: "text-gain" },
          { label: "Total Expenses",   value: flowData?.total_spending, color: "text-loss" },
          { label: "Total Net Income", value: flowData?.net,            color: (flowData?.net ?? 0) >= 0 ? "text-gain" : "text-loss" },
          { label: "Savings Rate",     value: flowData?.savings_rate,   isPct: true, color: "text-[var(--chart-c2)]" },
        ].map((card, i) => (
          <div key={i} className="bg-white dark:bg-background-dark/40 border border-slate-200 dark:border-slate-800 rounded-xl px-5 py-4 text-center">
            <p className={`text-xl lg:text-2xl font-extrabold text-numeric ${card.color} mb-0.5`}>
              {card.isPct
                ? `${(card.value ?? 0).toFixed(1)}%`
                : fmt(card.value ?? 0)
              }
            </p>
            <p className="text-label">{card.label}</p>
          </div>
        ))}
      </div>

      {/* ── Sankey Chart — DOMINATES THE PAGE ──────────────────────────────── */}
      <div className="px-6 pb-4" ref={chartContainerRef}>
        <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-visible flex flex-col">
          {/* Chart header */}
          <div className="px-6 py-3 flex items-center justify-between border-b border-slate-100 dark:border-slate-800">
            <div>
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">CASH FLOW</span>
              <span className="text-[11px] text-slate-400 ml-3">{timeLabel}</span>
            </div>
            <select
              className="bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
              value={timeframe}
              onChange={e => { setTimeframe(e.target.value); setActiveFilter(null); }}
            >
              {Object.keys(TF_MAP).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* Chart body — fills remaining space */}
          <div className="p-4 flex items-center justify-center">
            {sankeyData ? (
              <SankeyChart
                incomeNodes={sankeyData.incomeNodes}
                spendNodes={sankeyData.spendNodes}
                totalIncome={sankeyData.totalIncome}
                totalSpending={sankeyData.totalSpending}
                savings={sankeyData.savings}
                activeNode={activeFilter?.name ?? null}
                onNodeClick={onNodeClick}
                containerWidth={containerWidth - 80}
              />
            ) : (
              <div className="flex flex-col items-center gap-2 text-slate-400">
                <span className="material-symbols-outlined text-4xl animate-spin" style={{ animationDuration: "2s" }}>hourglass_top</span>
                <p className="text-sm font-semibold">Loading flow data...</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Filtered Transactions + Summary ────────────────────────────────── */}
      <div ref={txListRef} className="px-6 pb-6 flex flex-col lg:flex-row gap-4">
        {/* Transaction List */}
        <div className="flex-1 bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl flex flex-col overflow-hidden">
          {/* Header */}
          <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-3 flex-wrap">
              <h3 className="font-bold text-base">Transactions</h3>
              {activeFilter && (
                <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold border ${
                  activeFilter.side === "income"
                    ? "bg-[var(--color-gain)]/10 text-[var(--color-gain)] border-[var(--color-gain)]/30"
                    : "bg-[var(--color-loss)]/10 text-[var(--color-loss)] border-[var(--color-loss)]/30"
                }`}>
                  <span className="material-symbols-outlined text-[11px]">{activeFilter.side === "income" ? "trending_up" : "trending_down"}</span>
                  {activeFilter.name}
                  <button onClick={() => setActiveFilter(null)} className="ml-1 hover:opacity-70">
                    <span className="material-symbols-outlined text-[11px]">close</span>
                  </button>
                </div>
              )}
            </div>
            <span className="text-xs text-slate-500 font-semibold shrink-0">
              {filteredTx.length} transaction{filteredTx.length !== 1 ? "s" : ""}
            </span>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto max-h-[400px] custom-scrollbar divide-y divide-slate-100 dark:divide-primary/5">
            {filteredTx.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-slate-400">
                <span className="material-symbols-outlined text-3xl mb-2">filter_list_off</span>
                <p className="font-semibold text-sm">No matching transactions</p>
                <p className="text-xs">Try selecting a different category or timeframe</p>
              </div>
            ) : (
              filteredTx.map(tx => (
                <div key={tx.id} className="px-5 py-2.5 flex items-center gap-3 hover:bg-slate-50 dark:hover:bg-primary/5 transition-colors group">
                  {/* Direction */}
                  <div className={`size-7 rounded-full flex items-center justify-center shrink-0 ${
                    (tx.signed_amount ?? tx.amount) >= 0 ? "bg-[var(--color-gain)]/10 text-[var(--color-gain)]" : "bg-[var(--color-loss)]/10 text-[var(--color-loss)]"
                  }`}>
                    <span className="material-symbols-outlined text-sm">
                      {(tx.signed_amount ?? tx.amount) >= 0 ? "arrow_downward" : "arrow_upward"}
                    </span>
                  </div>

                  {/* Description */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold truncate">{tx.description || tx.merchant}</p>
                    <p className="text-[10px] text-slate-400">{tx.posting_date}</p>
                  </div>

                  {/* Category badge */}
                  <div className="relative">
                    {editingTxId === tx.id ? (
                      <select
                        autoFocus
                        className="text-xs font-bold bg-white dark:bg-slate-800 border border-primary/30 rounded-lg px-2 py-1 outline-none shadow-lg z-20"
                        value={tx.category || "Uncategorized"}
                        onChange={e => handleCategoryPatch(tx.id, e.target.value)}
                        onBlur={() => setEditingTxId(null)}
                      >
                        {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    ) : (
                      <button
                        onClick={() => setEditingTxId(tx.id)}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-primary/10 text-primary border border-primary/20 hover:bg-primary/20 hover:border-primary/40 transition-all cursor-pointer group/cat"
                        title="Click to reclassify"
                      >
                        {tx.category || "Uncategorized"}
                        <span className="material-symbols-outlined text-[9px] opacity-0 group-hover/cat:opacity-100 transition-opacity">edit</span>
                      </button>
                    )}
                  </div>

                  {/* Account */}
                  <span className="text-[10px] text-slate-500 font-semibold hidden xl:block w-28 truncate text-right">
                    {ACCOUNT_NAMES[tx.account_id] || tx.account_id}
                  </span>

                  {/* Amount */}
                  <span className={`text-sm font-bold w-24 text-right shrink-0 text-numeric ${
                    (tx.signed_amount ?? tx.amount) < 0 ? "text-loss" : "text-gain"
                  }`}>
                    {(tx.signed_amount ?? tx.amount) < 0 ? "-" : "+"}${Math.abs(tx.signed_amount ?? tx.amount).toFixed(2)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Summary Panel */}
        <div className="w-full lg:w-[260px] shrink-0">
          <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-5 sticky top-24">
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-sm">Summary</h3>
              <span className="material-symbols-outlined text-sm text-slate-400">tune</span>
            </div>
            {summary ? (
              <div className="space-y-3">
                {[
                  { label: "Total transactions", value: summary.count.toString() },
                  { label: "Largest transaction", value: fmt(summary.largest), color: "text-primary" },
                  { label: "Average transaction", value: fmt(summary.average) },
                  { label: "Total spending", value: fmt(summary.total), color: "font-extrabold" },
                  { label: "First transaction", value: summary.first },
                  { label: "Last transaction", value: summary.last },
                ].map((item, idx) => (
                  <div key={idx} className="flex items-center justify-between">
                    <span className="text-[11px] text-slate-500">{item.label}</span>
                    <span className={`text-[11px] font-bold ${item.color || "text-slate-700 dark:text-slate-300"}`}>{item.value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-6 text-slate-400">
                <span className="material-symbols-outlined text-xl mb-2">insights</span>
                <p className="text-xs text-center">Select a category from the chart to see a summary</p>
              </div>
            )}
          </div>
        </div>
      </div>
      </>
      )}
    </div>
  );
}
