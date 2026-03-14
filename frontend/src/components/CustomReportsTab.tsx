/**
 * CustomReportsTab — Merchant Sankey + Ranked List
 *
 * Features:
 *  - Timeframe selector (shared with parent)
 *  - Merchant picker: toggleable chips (top N auto-selected; "Other" always shown)
 *  - Merchant Sankey reusing the same SankeyChart component
 *  - Ranked merchant list with inline sparkline bars
 *  - Transaction list filtered by clicked merchant
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";

/* ── Types ──────────────────────────────────────────────────────────────────── */

interface MonthlyPoint { month: string; total: number; }
interface MerchantEntry {
  merchant: string;
  total: number;
  tx_count: number;
  category: string;
  monthly: MonthlyPoint[];
}
interface FlowData {
  income_categories: { category: string; total: number }[];
  spending_categories: { category: string; total: number }[];
  total_income: number;
  total_spending: number;
  net: number;
  savings_rate: number;
  available_merchants: string[];
  selected_merchants: string[];
}
interface Transaction {
  id: string;
  description: string;
  merchant?: string;
  posting_date: string;
  amount: number;
  signed_amount: number;
  category: string;
  account_id: string;
}
interface SankeyNodeData {
  name: string; value: number; color: string;
  side: "income" | "hub" | "spending"; pctLabel: string;
}
interface LayoutNode extends SankeyNodeData { h: number; y: number; }

/* ── Palette ─────────────────────────────────────────────────────────────────── */

const INCOME_COLORS = [
  "oklch(0.52 0.13 155)", "oklch(0.52 0.10 185)",
  "oklch(0.52 0.12 240)", "oklch(0.50 0.08 90)",
];
const SPEND_COLORS = [
  "oklch(0.52 0.12 240)", "oklch(0.52 0.11 290)", "oklch(0.55 0.11 45)",
  "oklch(0.48 0.13 20)",  "oklch(0.52 0.10 185)", "oklch(0.50 0.09 320)",
  "oklch(0.50 0.08 90)",  "oklch(0.52 0.13 155)", "oklch(0.46 0.12 25)",
  "oklch(0.54 0.10 270)", "oklch(0.50 0.11 60)",  "oklch(0.52 0.09 210)",
  "oklch(0.50 0.08 140)", "oklch(0.52 0.10 310)",
];
// "Other" bucket always this color
const OTHER_COLOR = "oklch(0.60 0.03 240)";

const TF_MAP: Record<string, number> = {
  "Last 30 Days": 1, "Last 3 Months": 3, "Last 6 Months": 6,
  "Year to Date": 12, "All Time": 120,
};

const fmt = (v: number) =>
  "$" + v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v: number, t: number) =>
  t > 0 ? ((v / t) * 100).toFixed(1) + "%" : "0%";

/* ── Sankey path helper ─────────────────────────────────────────────────────── */

function sankeyLinkPath(sx: number, sy: number, sh: number, tx: number, ty: number, th: number) {
  const mx = (sx + tx) / 2;
  return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}
          L${tx},${ty + th} C${mx},${ty + th} ${mx},${sy + sh} ${sx},${sy + sh} Z`;
}

/* ── Sankey component (merchant edition) ────────────────────────────────────── */

function MerchantSankeyChart({
  incomeNodes, spendNodes, totalIncome, savings, activeNode, onNodeClick, containerWidth,
}: {
  incomeNodes: SankeyNodeData[]; spendNodes: SankeyNodeData[];
  totalIncome: number; savings: number;
  activeNode: string | null; onNodeClick: (n: string, s: string) => void;
  containerWidth: number;
}) {
  const NODE_W = 22;
  const HEIGHT = 420;
  const LEFT_X = 120;
  const RIGHT_X = containerWidth - 260;
  const HUB_X = (LEFT_X + NODE_W + RIGHT_X) / 2 - 11;
  const HUB_W = 22;
  const PADDING = 4;

  const totalSpending = spendNodes.reduce((s, n) => s + n.value, 0);
  const hubH = Math.max((totalSpending / Math.max(totalIncome, 1)) * (HEIGHT - 20), 20);

  // ── Income layout
  const incomeH = HEIGHT - (incomeNodes.length - 1) * PADDING;
  const incomeLayout: LayoutNode[] = incomeNodes.map((n) => ({ ...n, h: (n.value / Math.max(totalIncome, 1)) * incomeH, y: 0 }));
  let incY = 0;
  incomeLayout.forEach(n => { n.y = incY; incY += n.h + PADDING; });

  // ── Spending layout
  const spendH = HEIGHT - (spendNodes.length - 1) * PADDING;
  const spendLayout: LayoutNode[] = spendNodes.map(n => ({ ...n, h: (n.value / Math.max(totalSpending, 1)) * spendH, y: 0 }));
  let spY = Math.max(0, (HEIGHT - spendH) / 2);
  spendLayout.forEach(n => { n.y = spY; spY += n.h + PADDING; });

  const hubY = Math.max(0, (HEIGHT - hubH) / 2);
  const isActive = (name: string) => activeNode === name;

  return (
    <svg
      width={containerWidth} height={HEIGHT + 20}
      style={{ fontFamily: "var(--font-sans, system-ui)", overflow: "visible" }}
    >
      {/* ── Income → Hub links ── */}
      {incomeLayout.map((n, i) => {
        let hubOffset = 0;
        for (let j = 0; j < i; j++) {
          hubOffset += (incomeLayout[j].value / Math.max(totalIncome, 1)) * hubH;
        }
        const th = (n.value / Math.max(totalIncome, 1)) * hubH;
        return (
          <path key={`il-${i}`}
            d={sankeyLinkPath(LEFT_X + NODE_W, n.y!, n.h!, HUB_X, hubY + hubOffset, th)}
            fill={n.color} opacity={activeNode && !isActive(n.name) ? 0.12 : 0.22}
            style={{ transition: "opacity 0.3s" }}
          />
        );
      })}

      {/* ── Hub → Spending links ── */}
      {spendLayout.map((n, i) => {
        let hubOffset = 0;
        for (let j = 0; j < i; j++) {
          hubOffset += (spendLayout[j].value / Math.max(totalSpending, 1)) * hubH;
        }
        const sh = (n.value / Math.max(totalSpending, 1)) * hubH;
        const color = n.name === "Other" ? OTHER_COLOR : n.color;
        return (
          <path key={`sl-${i}`}
            d={sankeyLinkPath(HUB_X + HUB_W, hubY + hubOffset, sh, RIGHT_X, n.y!, n.h!)}
            fill={color} opacity={activeNode && !isActive(n.name) ? 0.12 : 0.22}
            style={{ transition: "opacity 0.3s" }}
          />
        );
      })}

      {/* ── Hub node ── */}
      <rect x={HUB_X} y={hubY} width={HUB_W} height={hubH} rx={4} fill="oklch(0.50 0.08 240)" />

      {/* ── Savings label at bottom of hub ── */}
      {savings > 0 && (
        <text x={HUB_X + HUB_W / 2} y={hubY + hubH + 18}
          textAnchor="middle" style={{ fontSize: 11, fill: "oklch(0.52 0.13 155)", fontWeight: 700 }}>
          +{fmt(savings)} saved
        </text>
      )}

      {/* ── Income nodes ── */}
      {incomeLayout.map((n, i) => (
        <g key={`in-${i}`} style={{ cursor: "pointer" }} onClick={() => onNodeClick(n.name, "income")}>
          <rect x={LEFT_X} y={n.y!} width={NODE_W} height={n.h!} rx={4}
            fill={isActive(n.name) ? "#fff" : n.color}
            stroke={isActive(n.name) ? n.color : "none"} strokeWidth={2}
            style={{ filter: isActive(n.name) ? `drop-shadow(0 0 6px ${n.color}80)` : "none",
              opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "all 0.3s" }} />
          <circle cx={LEFT_X - 14} cy={n.y! + 12} r={5} fill={n.color}
            style={{ opacity: activeNode && !isActive(n.name) ? 0.35 : 1 }} />
          <text x={LEFT_X - 24} y={n.y! + 13} textAnchor="end" dominantBaseline="central"
            style={{ fontSize: 12, fontWeight: 700, fill: isActive(n.name) ? n.color : "#334155",
              opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "all 0.3s" }}>
            {n.name}
          </text>
          {n.h! > 18 && (
            <text x={LEFT_X - 24} y={n.y! + 28} textAnchor="end"
              style={{ fontSize: 10, fill: "#94a3b8",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1 }}>
              {fmt(n.value)}
            </text>
          )}
        </g>
      ))}

      {/* ── Spending nodes ── */}
      {spendLayout.map((n, i) => {
        const color = n.name === "Other" ? OTHER_COLOR : n.color;
        return (
          <g key={`sp-${i}`} style={{ cursor: n.name === "Other" ? "default" : "pointer" }}
            onClick={() => n.name !== "Other" && onNodeClick(n.name, "spending")}>
            <rect x={RIGHT_X} y={n.y!} width={NODE_W} height={n.h!} rx={4}
              fill={isActive(n.name) ? "#fff" : color}
              stroke={isActive(n.name) ? color : "none"} strokeWidth={2}
              style={{ filter: isActive(n.name) ? `drop-shadow(0 0 6px ${color}80)` : "none",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "all 0.3s" }} />
            <circle cx={RIGHT_X + NODE_W + 14} cy={n.y! + 12} r={5} fill={color}
              style={{ opacity: activeNode && !isActive(n.name) ? 0.35 : 1 }} />
            <text x={RIGHT_X + NODE_W + 24} y={n.y! + 13} textAnchor="start" dominantBaseline="central"
              style={{ fontSize: 12, fontWeight: 700, fill: isActive(n.name) ? color : "#334155",
                opacity: activeNode && !isActive(n.name) ? 0.35 : 1, transition: "all 0.3s" }}>
              {n.name}
            </text>
            {n.h! > 18 && (
              <text x={RIGHT_X + NODE_W + 24} y={n.y! + 28} textAnchor="start"
                style={{ fontSize: 10, fill: "#94a3b8",
                  opacity: activeNode && !isActive(n.name) ? 0.35 : 1 }}>
                {fmt(n.value)} · {pct(n.value, spendNodes.reduce((s, x) => s + x.value, 0))}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/* ── Sparkline bar ──────────────────────────────────────────────────────────── */

function Sparkline({ monthly, color }: { monthly: MonthlyPoint[]; color: string }) {
  if (!monthly.length) return <div className="w-24 h-6" />;
  const max = Math.max(...monthly.map(m => m.total), 0.01);
  return (
    <div className="flex items-end gap-0.5 h-6 w-24">
      {monthly.map((m, i) => (
        <div key={i} className="flex-1 rounded-sm transition-all"
          style={{ height: `${Math.max(4, (m.total / max) * 24)}px`, backgroundColor: color, opacity: 0.7 }}
          title={`${m.month}: ${fmt(m.total)}`}
        />
      ))}
    </div>
  );
}

/* ── Main CustomReportsTab ──────────────────────────────────────────────────── */

export default function CustomReportsTab({ timeframe }: { timeframe: string }) {
  const [merchantData, setMerchantData] = useState<MerchantEntry[]>([]);
  const [flowData, setFlowData] = useState<FlowData | null>(null);
  const [selectedMerchants, setSelectedMerchants] = useState<string[]>([]);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [focusedMerchant, setFocusedMerchant] = useState<string | null>(null);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);
  const [containerWidth, setContainerWidth] = useState(900);
  const [pickerOpen, setPickerOpen] = useState(true);
  const [flowOpen, setFlowOpen] = useState(true);
  const [tableOpen, setTableOpen] = useState(true);
  const [sortCol, setSortCol] = useState<"merchant" | "total" | "tx_count" | "trend" | "avg">("total");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const chartRef = useRef<HTMLDivElement>(null);
  const txRef = useRef<HTMLDivElement>(null);

  // Responsive chart width
  useEffect(() => {
    const obs = new ResizeObserver(e => {
      for (const en of e) setContainerWidth(en.contentRect.width);
    });
    if (chartRef.current) obs.observe(chartRef.current);
    return () => obs.disconnect();
  }, []);

  const months = TF_MAP[timeframe] || 6;

  // Fetch merchant list
  const fetchMerchants = useCallback(() => {
    setLoading(true);
    fetch(`http://127.0.0.1:8000/api/reports/merchants?months=${months}&limit=50`)
      .then(r => r.json())
      .then(d => {
        const list: MerchantEntry[] = d.merchants || [];
        setMerchantData(list);
        // Auto-select top 10 on first load or timeframe change
        setSelectedMerchants(prev => {
          if (prev.length === 0 || true) return list.slice(0, 10).map(m => m.merchant);
          return prev;
        });
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [months]);

  useEffect(() => { fetchMerchants(); }, [fetchMerchants]);

  // Fetch flow data for Sankey whenever selection changes
  const fetchFlow = useCallback(() => {
    if (selectedMerchants.length === 0) return;
    const q = selectedMerchants.map(encodeURIComponent).join(",");
    fetch(`http://127.0.0.1:8000/api/reports/merchant-flow?months=${months}&merchants=${q}`)
      .then(r => r.json())
      .then(setFlowData)
      .catch(console.error);
  }, [months, selectedMerchants]);

  useEffect(() => { fetchFlow(); }, [fetchFlow]);

  // Fetch transactions when a merchant is focused
  useEffect(() => {
    if (!focusedMerchant) { setTransactions([]); return; }
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    const sd = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-01`;
    const ed = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    fetch(`http://127.0.0.1:8000/api/transactions?limit=500&start_date=${sd}&end_date=${ed}`)
      .then(r => r.json())
      .then(d => {
        const txs: Transaction[] = (d.transactions || []).filter((t: Transaction) => {
          const m = t.merchant || t.description || "";
          return m.toLowerCase().includes(focusedMerchant.toLowerCase()) ||
                 focusedMerchant.toLowerCase().includes((m || "").toLowerCase());
        });
        setTransactions(txs);
        setTimeout(() => txRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
      })
      .catch(console.error);
  }, [focusedMerchant, months]);

  // Toggle merchant in/out of selection
  const toggleMerchant = (name: string) => {
    setSelectedMerchants(prev =>
      prev.includes(name) ? prev.filter(m => m !== name) : [...prev, name]
    );
  };

  // Sankey node data from flowData
  const sankeyData = useMemo(() => {
    if (!flowData) return null;
    const totalIncome = flowData.total_income;
    const totalSpending = flowData.total_spending;
    const savings = Math.max(0, totalIncome - totalSpending);

    const incomeNodes: SankeyNodeData[] = flowData.income_categories.map((c, i) => ({
      name: c.category, value: c.total, color: INCOME_COLORS[i % INCOME_COLORS.length],
      side: "income" as const, pctLabel: pct(c.total, totalIncome),
    }));

    const spendNodes: SankeyNodeData[] = flowData.spending_categories.map((c, i) => ({
      name: c.category,
      value: c.total,
      color: c.category === "Other" ? OTHER_COLOR : SPEND_COLORS[i % SPEND_COLORS.length],
      side: "spending" as const,
      pctLabel: pct(c.total, totalSpending),
    }));

    return { incomeNodes, spendNodes, totalIncome, totalSpending, savings };
  }, [flowData]);

  const maxTotal = useMemo(() =>
    Math.max(...merchantData.map(m => m.total), 0.01), [merchantData]);

  // Sorted merchant list
  const sortedMerchants = useMemo(() => {
    const dir = sortDir === "desc" ? -1 : 1;
    return [...merchantData].sort((a, b) => {
      if (sortCol === "merchant") return dir * a.merchant.localeCompare(b.merchant);
      if (sortCol === "total")    return dir * (a.total - b.total);
      if (sortCol === "tx_count") return dir * (a.tx_count - b.tx_count);
      if (sortCol === "avg")      return dir * ((a.total / Math.max(a.tx_count, 1)) - (b.total / Math.max(b.tx_count, 1)));
      if (sortCol === "trend") {
        const aLast = a.monthly[a.monthly.length - 1]?.total ?? 0;
        const bLast = b.monthly[b.monthly.length - 1]?.total ?? 0;
        return dir * (aLast - bLast);
      }
      return 0;
    });
  }, [merchantData, sortCol, sortDir]);

  const handleSort = (col: typeof sortCol) => {
    if (sortCol === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortCol(col); setSortDir("desc"); }
  };

  const SortIcon = ({ col }: { col: typeof sortCol }) =>
    sortCol === col
      ? <span className="ml-0.5 opacity-70">{sortDir === "desc" ? "↓" : "↑"}</span>
      : <span className="ml-0.5 opacity-20">↕</span>;

  const onSankeyNodeClick = (name: string, side: string) => {
    if (side === "spending" && name !== "Other") {
      setFocusedMerchant(prev => prev === name ? null : name);
      setActiveNode(prev => prev === name ? null : name);
    } else {
      setActiveNode(prev => prev === name ? null : name);
    }
  };

  return (
    <div className="flex flex-col gap-4">

      {/* ── Merchant Picker ─────────────────────────────────────────────────── */}
      <div className="px-6 pt-2">
        <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
          {/* Header row — always visible */}
          <div
            className="flex items-center justify-between px-4 py-3 cursor-pointer select-none hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
            onClick={() => setPickerOpen(o => !o)}
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-slate-400 text-base transition-transform duration-200"
                style={{ transform: pickerOpen ? "rotate(0deg)" : "rotate(-90deg)" }}>
                expand_more
              </span>
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">
                MERCHANT PICKER
              </span>
              <span className="text-[11px] text-slate-400">
                {selectedMerchants.length} selected
              </span>
            </div>
            {/* Quick-action buttons only visible when open */}
            {pickerOpen && (
              <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                <button
                  onClick={() => setSelectedMerchants(merchantData.slice(0, 10).map(m => m.merchant))}
                  className="text-[10px] font-bold px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-primary hover:border-primary/30 transition-all"
                >
                  Top 10
                </button>
                <button
                  onClick={() => setSelectedMerchants(merchantData.map(m => m.merchant))}
                  className="text-[10px] font-bold px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-primary hover:border-primary/30 transition-all"
                >
                  All
                </button>
                <button
                  onClick={() => setSelectedMerchants([])}
                  className="text-[10px] font-bold px-2 py-1 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-loss hover:border-loss/30 transition-all"
                >
                  Clear
                </button>
              </div>
            )}
          </div>
          {/* Chips — only visible when open */}
          {pickerOpen && (
            <div className="px-4 pb-4">
              <div className="flex flex-wrap gap-2 max-h-[120px] overflow-y-auto custom-scrollbar">
                {merchantData.map((m, i) => {
                  const color = SPEND_COLORS[i % SPEND_COLORS.length];
                  const isSelected = selectedMerchants.includes(m.merchant);
                  return (
                    <button
                      key={m.merchant}
                      onClick={() => toggleMerchant(m.merchant)}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-bold border transition-all ${
                        isSelected
                          ? "border-transparent text-white shadow-sm"
                          : "bg-transparent border-slate-200 dark:border-slate-700 text-slate-500 hover:border-slate-400"
                      }`}
                      style={isSelected ? { backgroundColor: color, borderColor: color } : {}}
                    >
                      <span>{m.merchant}</span>
                      <span className="opacity-70">{fmt(m.total)}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Merchant Sankey ─────────────────────────────────────────────────── */}
      <div className="px-6" ref={chartRef}>
        <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-visible">
          {/* Header — always visible */}
          <div
            className="flex items-center justify-between px-4 py-3 cursor-pointer select-none hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
            onClick={() => setFlowOpen(o => !o)}
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-slate-400 text-base transition-transform duration-200"
                style={{ transform: flowOpen ? "rotate(0deg)" : "rotate(-90deg)" }}>
                expand_more
              </span>
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">MERCHANT FLOW</span>
              {!flowOpen && flowData && (
                <span className="text-[11px] text-slate-400">
                  {fmt(flowData.total_income)} in · {fmt(flowData.total_spending)} out
                </span>
              )}
            </div>
            {activeNode && (
              <button
                onClick={e => { e.stopPropagation(); setActiveNode(null); setFocusedMerchant(null); }}
                className="text-[10px] font-bold px-2 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-500 hover:text-primary transition-all"
              >
                Clear filter ✕
              </button>
            )}
          </div>

          {/* Body — collapsible */}
          {flowOpen && (
            <>
              <div className="border-t border-slate-100 dark:border-slate-800 p-4 flex items-center justify-center">
                {loading ? (
                  <div className="flex flex-col items-center gap-2 text-slate-400 py-12">
                    <span className="material-symbols-outlined text-4xl animate-spin" style={{ animationDuration: "2s" }}>
                      hourglass_top
                    </span>
                    <p className="text-sm font-semibold">Building merchant data...</p>
                  </div>
                ) : sankeyData && containerWidth > 200 ? (
                  <MerchantSankeyChart
                    incomeNodes={sankeyData.incomeNodes}
                    spendNodes={sankeyData.spendNodes}
                    totalIncome={sankeyData.totalIncome}
                    savings={sankeyData.savings}
                    activeNode={activeNode}
                    onNodeClick={onSankeyNodeClick}
                    containerWidth={containerWidth - 80}
                  />
                ) : (
                  <div className="py-12 text-slate-400 text-sm text-center">
                    <span className="material-symbols-outlined text-2xl block mb-2">bar_chart</span>
                    Select at least one merchant above to build the chart
                  </div>
                )}
              </div>
              {flowData && (
                <div className="px-6 py-3 border-t border-slate-100 dark:border-slate-800 grid grid-cols-4 gap-4">
                  {[
                    { label: "Total Income",  value: fmt(flowData.total_income),  color: "text-gain" },
                    { label: "Total Spend",   value: fmt(flowData.total_spending), color: "text-loss" },
                    { label: "Net",           value: fmt(flowData.net),            color: flowData.net >= 0 ? "text-gain" : "text-loss" },
                    { label: "Savings Rate",  value: `${flowData.savings_rate.toFixed(1)}%`, color: "text-primary" },
                  ].map((s, i) => (
                    <div key={i} className="text-center">
                      <p className={`text-base font-extrabold text-numeric ${s.color}`}>{s.value}</p>
                      <p className="text-label">{s.label}</p>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* ── Ranked Merchant Table ────────────────────────────────────────────── */}
      <div className="px-6 pb-2">
        <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
          {/* Header — always visible */}
          <div
            className="flex items-center justify-between px-5 py-3 cursor-pointer select-none hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
            onClick={() => setTableOpen(o => !o)}
          >
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-slate-400 text-base transition-transform duration-200"
                style={{ transform: tableOpen ? "rotate(0deg)" : "rotate(-90deg)" }}>
                expand_more
              </span>
              <span className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">TOP MERCHANTS</span>
              <span className="text-[11px] text-slate-400">
                {merchantData.length} merchants · click a row to drill down
              </span>
            </div>
          </div>
          {/* Table body — collapsible */}
          {tableOpen && (
            <div className="overflow-x-auto border-t border-slate-100 dark:border-slate-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 dark:border-slate-800">
                    <th
                      className="px-5 py-2 text-left text-[10px] font-bold text-slate-400 uppercase cursor-pointer hover:text-slate-600 select-none"
                      onClick={() => handleSort("merchant")}
                    >
                      Merchant <SortIcon col="merchant" />
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-bold text-slate-400 uppercase">Category</th>
                    <th
                      className="px-3 py-2 text-right text-[10px] font-bold text-slate-400 uppercase cursor-pointer hover:text-slate-600 select-none"
                      onClick={() => handleSort("trend")}
                    >
                      Trend <SortIcon col="trend" />
                    </th>
                    <th
                      className="px-3 py-2 text-right text-[10px] font-bold text-slate-400 uppercase cursor-pointer hover:text-slate-600 select-none"
                      onClick={() => handleSort("total")}
                    >
                      Total <SortIcon col="total" />
                    </th>
                    <th
                      className="px-5 py-2 text-right text-[10px] font-bold text-slate-400 uppercase cursor-pointer hover:text-slate-600 select-none"
                      onClick={() => handleSort("tx_count")}
                    >
                      Txns <SortIcon col="tx_count" />
                    </th>
                    <th
                      className="px-5 py-2 text-right text-[10px] font-bold text-slate-400 uppercase cursor-pointer hover:text-slate-600 select-none"
                      onClick={() => handleSort("avg")}
                    >
                      Avg Txn <SortIcon col="avg" />
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50 dark:divide-slate-800/50">
                  {sortedMerchants.slice(0, 30).map((m, i) => {
                    const color = SPEND_COLORS[i % SPEND_COLORS.length];
                    const isFocused = focusedMerchant === m.merchant;
                    return (
                      <tr
                        key={m.merchant}
                        onClick={() => setFocusedMerchant(prev => prev === m.merchant ? null : m.merchant)}
                        className={`cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40 ${
                          isFocused ? "bg-primary/5 dark:bg-primary/10" : ""
                        }`}
                      >
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-3">
                            <div className="w-16 h-1 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{ width: `${(m.total / maxTotal) * 100}%`, backgroundColor: color }}
                              />
                            </div>
                            <span className={`font-semibold ${isFocused ? "text-primary" : "text-slate-800 dark:text-slate-200"}`}>
                              {m.merchant}
                            </span>
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500">
                            {m.category}
                          </span>
                        </td>
                        <td className="px-3 py-3 flex justify-end">
                          <Sparkline monthly={m.monthly} color={color} />
                        </td>
                        <td className="px-3 py-3 text-right font-bold text-numeric text-slate-800 dark:text-slate-200">
                          {fmt(m.total)}
                        </td>
                        <td className="px-5 py-3 text-right text-slate-500 tabular-nums">{m.tx_count}</td>
                        <td className="px-5 py-3 text-right text-slate-500 tabular-nums text-xs">
                          {fmt(m.total / Math.max(m.tx_count, 1))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── Transaction list ─────────────────────────────────────────────────── */}
      {focusedMerchant && (
        <div ref={txRef} className="px-6 pb-6">
          <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h3 className="font-bold text-sm">Transactions</h3>
                <span className="text-xs font-bold px-2.5 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                  {focusedMerchant}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500">{transactions.length} results</span>
                <button onClick={() => { setFocusedMerchant(null); setActiveNode(null); }}
                  className="text-slate-400 hover:text-slate-600">
                  <span className="material-symbols-outlined text-sm">close</span>
                </button>
              </div>
            </div>
            <div className="divide-y divide-slate-50 dark:divide-slate-800/50 max-h-[360px] overflow-y-auto custom-scrollbar">
              {transactions.length === 0 ? (
                <div className="py-10 text-center text-slate-400 text-sm">No transactions found</div>
              ) : transactions.map(tx => (
                <div key={tx.id} className="px-5 py-3 flex items-center gap-3 hover:bg-slate-50 dark:hover:bg-slate-800/30">
                  <div className={`size-7 rounded-full flex items-center justify-center shrink-0 ${
                    tx.signed_amount >= 0 ? "bg-[var(--color-gain)]/10 text-[var(--color-gain)]" : "bg-[var(--color-loss)]/10 text-[var(--color-loss)]"
                  }`}>
                    <span className="material-symbols-outlined text-sm">
                      {tx.signed_amount >= 0 ? "arrow_downward" : "arrow_upward"}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold truncate">{tx.description}</p>
                    <p className="text-[10px] text-slate-400">{tx.posting_date}</p>
                  </div>
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 shrink-0">
                    {tx.category}
                  </span>
                  <span className={`text-sm font-bold w-24 text-right text-numeric ${
                    tx.signed_amount < 0 ? "text-loss" : "text-gain"
                  }`}>
                    {tx.signed_amount < 0 ? "-" : "+"}${Math.abs(tx.signed_amount).toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
