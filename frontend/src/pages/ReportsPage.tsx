import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useSessionState } from "@/hooks/useSessionState";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAccounts } from "@/lib/accounts";
import { formatCurrency } from "@/lib/formatCurrency";
import { useView } from "@/context/ViewContext";


/* ── Constants ─────────────────────────────────────────────────────────────── */

// ACCOUNT_NAMES now comes from useAccounts() hook inside the component

// CATEGORIES now comes from useAccounts() hook inside the component

// Legacy fallback only — backend prefers explicit start_date/end_date.
const TF_MAP: Record<string, number> = {
  "Last 30 Days": 1,
  "Last 3 Months": 3,
  "Last 6 Months": 6,
  "Year to Date": 12,
  "All Time": 120,
};

/**
 * Resolve a timeframe preset to explicit local-time start/end dates.
 * Anchored on the user's local clock so "Year to Date" really means
 * Jan 1 of the current year, "Last 30 Days" means today minus 30 calendar
 * days, and "Last 3 Months" means the first day of (current month − 2)
 * through today.  Eliminates the UTC drift inherent in the backend's
 * legacy `date('now', '-N months')` math.
 *
 * Returns { start_date, end_date } as YYYY-MM-DD strings, or null for
 * "All Time" (no lower bound).
 */
function resolveTimeframe(label: string): { start_date: string | null; end_date: string } {
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const today = new Date();
  const end_date = fmt(today);

  if (label === "All Time") {
    return { start_date: null, end_date };
  }
  if (label === "Year to Date") {
    return { start_date: `${today.getFullYear()}-01-01`, end_date };
  }
  if (label === "Last 30 Days") {
    const s = new Date();
    s.setDate(s.getDate() - 30);
    return { start_date: fmt(s), end_date };
  }
  // "Last N Months" → first of (current month − N + 1) through today
  const m = label.match(/^Last (\d+) Months$/);
  if (m) {
    const n = parseInt(m[1], 10);
    const s = new Date(today.getFullYear(), today.getMonth() - (n - 1), 1);
    return { start_date: fmt(s), end_date };
  }
  // Unknown label — fall back to "today only" which is harmless
  return { start_date: end_date, end_date };
}

/* Color palette — tuned to match Monarch Money aesthetic */
const INCOME_COLORS = [
  "#00a3bf",  // cyan-teal (disability / main income)
  "#5a67d8",  // indigo    (other income)
  "#805ad5",  // purple    (retirement)
  "#2b6cb0",  // blue      (education benefits)
  "#2c7a7b",  // deep teal (misc)
];
const SPEND_COLORS = [
  "#e53e3e",  // red      (housing / mortgage)
  "#dd6b20",  // orange   (food)
  "#d97706",  // amber    (financial)
  "#7c3aed",  // violet   (shopping)
  "#0284c7",  // sky blue (auto)
  "#059669",  // green    (children)
  "#db2777",  // pink     (personal)
  "#6366f1",  // indigo   (entertainment)
  "#0891b2",  // cyan     (utilities)
  "#b45309",  // brown    (gifts)
  "#9333ea",  // purple   (health)
  "#475569",  // slate    (other)
];
const SAVINGS_COLOR = "#38a169"; // emerald green — always for savings
const HUB_COLOR     = "#319795"; // teal — income hub bar

/* ── Helpers ───────────────────────────────────────────────────────────────── */

const fmt = (v: number) => formatCurrency(v);

const pct = (v: number, total: number) =>
  total > 0 ? ((v / total) * 100).toFixed(2) + "%" : "0%";

/* ── Sankey helpers ───────────────────────────────────────────────────────── */

/* Convert any color to a hex-ish string for gradient stops.
   oklch() values won't work in SVG gradients on all browsers, so
   we map them back to hex when a hex was not already provided. */
function toSvgColor(c: string): string {
  // Already hex or named — pass through
  if (c.startsWith("#") || !c.startsWith("oklch")) return c;
  // Fallback: just return as-is (modern browsers support oklch in SVG)
  return c;
}

/* SVG curved link path for Sankey */
function sankeyLinkPath(
  sx: number, sy: number, sh: number,
  tx: number, ty: number, th: number,
): string {
  const mx = (sx + tx) / 2;
  return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}
          L${tx},${ty + th} C${mx},${ty + th} ${mx},${sy + sh} ${sx},${sy + sh} Z`;
}

/* ── Custom SVG Sankey — Monarch Money faithful ───────────────────────────── */

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
  const NODE_W  = 18;   // thin flat bars (Monarch style)
  const NODE_PAD = 10;  // vertical gap between nodes
  const MIN_NODE_H = 18;
  const LABEL_W  = 210; // reserved px on left & right for labels
  const LABEL_PAD = 60; // extra bottom SVG padding

  // Full-width SVG
  const svgW = Math.max(860, containerWidth);

  // Column positions
  const col0x = LABEL_W;                           // income nodes (left)
  const col2x = svgW - LABEL_W - NODE_W;           // spending nodes (right)
  const col1x = Math.round((col0x + NODE_W + col2x) / 2); // hub (center)

  /* ── Heights ──────────────────────────────────────────────────────────── */
  const PAD_Y = 44;
  const nodesCount = Math.max(
    incomeNodes.length,
    spendNodes.length + (savings > 0 ? 1 : 0)
  );
  const chartH  = Math.max(420, Math.min(680, nodesCount * 52 + 100));
  const innerH  = chartH - PAD_Y * 2;
  const maxVal  = Math.max(
    incomeNodes.reduce((s, n) => s + n.value, 0),
    spendNodes.reduce((s, n) => s + n.value, 0) + Math.max(0, savings),
    totalIncome,
  );
  const scaleH  = (v: number) =>
    Math.max(MIN_NODE_H, (v / maxVal) * (innerH - NODE_PAD * nodesCount));

  // Income layout
  let incY = PAD_Y;
  const incomeLayout = incomeNodes.map(n => {
    const h = scaleH(n.value);
    const y = incY;
    incY += h + NODE_PAD;
    return { ...n, x: col0x, y, h };
  });

  // Hub
  const hubH = scaleH(totalIncome);
  const hubY = PAD_Y + (innerH - hubH) / 2;

  // Spending + savings (savings pinned to top)
  const actualSavings = Math.max(0, savings);
  const allSpend = [...spendNodes.map(n => ({ ...n }))];
  if (actualSavings > 0) {
    allSpend.unshift({
      name: "Savings",
      value: actualSavings,
      color: SAVINGS_COLOR,
      side: "spending" as const,
      pctLabel: pct(actualSavings, totalIncome),
    });
  }

  let spY = PAD_Y;
  const spendLayout = allSpend.map(n => {
    const h = scaleH(n.value);
    const y = spY;
    spY += h + NODE_PAD;
    return { ...n, x: col2x, y, h };
  });

  const svgH = Math.max(chartH, incY + LABEL_PAD, spY + LABEL_PAD);

  /* ── Build links with per-link bi-color gradient data ─────────────────── */
  let hubSrcY = hubY;
  const incomeLinks = incomeLayout.map(n => {
    const linkH = (n.value / totalIncome) * hubH;
    const link = {
      sx: n.x + NODE_W, sy: n.y,        sh: n.h,
      tx: col1x,        ty: hubSrcY,    th: linkH,
      srcColor: n.color,
      dstColor: HUB_COLOR,
      name: n.name, side: n.side,
    };
    hubSrcY += linkH;
    return link;
  });

  let hubDstY = hubY;
  const spendLinks = spendLayout.map(n => {
    const linkH = (n.value / totalIncome) * hubH;
    const link = {
      sx: col1x + NODE_W, sy: hubDstY,  sh: linkH,
      tx: n.x,            ty: n.y,      th: n.h,
      srcColor: HUB_COLOR,
      dstColor: n.color,
      name: n.name, side: n.side,
    };
    hubDstY += linkH;
    return link;
  });

  const allLinks = [...incomeLinks, ...spendLinks];

  /* ── Render ───────────────────────────────────────────────────────────── */
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const isActive  = (name: string) => activeNode === name;
  const dimmed    = (name: string) => !!(activeNode && !isActive(name));
  // lit = hovered OR nothing is hovered (fall-through) — drives full vs half opacity
  const lit       = (name: string) => hoveredNode === null || hoveredNode === name;

  /* Inline label renderer — Monarch anatomy:
       ● Name (bold, dark)
         $X,XXX.XX (XX%)  (smaller, muted) */
  const NodeLabel = ({
    nodeColor, name, value, pctLbl, x, anchor, yTop, nodeH, active, faded,
  }: {
    nodeColor: string; name: string; value: number; pctLbl: string;
    x: number; anchor: "start" | "end"; yTop: number; nodeH: number;
    active: boolean; faded: boolean;
  }) => {
    const dotCx = anchor === "end"
      ? x - 14
      : x + NODE_W + 14;
    const textX  = anchor === "end"
      ? x - 24
      : x + NODE_W + 24;
    const midY   = yTop + Math.min(nodeH / 2, 16);
    // Label opacity: faded (click-dim) → 0.15 | at rest → 0.5 | hovered → 1
    const labelOpacity = faded ? 0.15 : lit(name) ? 1 : 0.5;
    return (
      <g style={{ opacity: labelOpacity, transition: "opacity 0.2s ease" }}>
        <circle cx={dotCx} cy={midY} r={4.5}
          fill={nodeColor} />
        <text x={textX} y={midY - 1} textAnchor={anchor} dominantBaseline="auto"
          style={{ fontSize: 12.5, fontWeight: 700,
            fill: active ? nodeColor : "#1e293b",
            fontFamily: "'Geist Variable', Inter, sans-serif",
          }}>
          {name}
        </text>
        <text x={textX} y={midY + 15} textAnchor={anchor} dominantBaseline="auto"
          style={{ fontSize: 10.5, fontWeight: 500, fill: "#64748b",
            fontFamily: "'Geist Variable', Inter, sans-serif",
          }}>
          {fmt(value)} ({pctLbl})
        </text>
      </g>
    );
  };

  return (
    <svg
      width={svgW}
      height={svgH}
      viewBox={`0 0 ${svgW} ${svgH}`}
      overflow="visible"
      style={{ display: "block" }}
    >
      {/* ── Per-link bi-color gradients ───────────────────────────────── */}
      <defs>
        {allLinks.map((l, i) => {
          // Gradient opacity: half at rest, full on hover
          const hovered = hoveredNode === l.name;
          const s0 = dimmed(l.name) ? 0.05 : hovered ? 0.50 : hoveredNode ? 0.25 : 0.25;
          const s1 = dimmed(l.name) ? 0.02 : hovered ? 0.20 : hoveredNode ? 0.10 : 0.10;
          return (
            <linearGradient
              key={`g${i}`} id={`g${i}`}
              gradientUnits="userSpaceOnUse"
              x1={l.sx} x2={l.tx} y1={0} y2={0}
            >
              <stop offset="0%"   stopColor={toSvgColor(l.srcColor)} stopOpacity={s0} />
              <stop offset="100%" stopColor={toSvgColor(l.dstColor)} stopOpacity={s1} />
            </linearGradient>
          );
        })}
      </defs>

      {/* ── Ribbons: income → hub ─────────────────────────────────────── */}
      {incomeLinks.map((l, i) => (
        <path
          key={`il${i}`}
          d={sankeyLinkPath(l.sx, l.sy, l.sh, l.tx, l.ty, l.th)}
          fill={`url(#g${i})`}
          stroke={toSvgColor(l.srcColor)}
          strokeWidth={0.6}
          strokeOpacity={dimmed(l.name) ? 0.05 : lit(l.name) ? 0.18 : 0.09}
          style={{
            cursor: "pointer",
            opacity: dimmed(l.name) ? 0.10 : lit(l.name) ? 1 : 0.5,
            transition: "opacity 0.2s ease",
          }}
          onClick={() => onNodeClick(l.name, "income")}
          onMouseEnter={() => setHoveredNode(l.name)}
          onMouseLeave={() => setHoveredNode(null)}
        >
          <title>{l.name}</title>
        </path>
      ))}

      {/* ── Ribbons: hub → spending ───────────────────────────────────── */}
      {spendLinks.map((l, i) => (
        <path
          key={`sl${i}`}
          d={sankeyLinkPath(l.sx, l.sy, l.sh, l.tx, l.ty, l.th)}
          fill={`url(#g${incomeLinks.length + i})`}
          stroke={toSvgColor(l.dstColor)}
          strokeWidth={0.6}
          strokeOpacity={dimmed(l.name) ? 0.05 : lit(l.name) ? 0.18 : 0.09}
          style={{
            cursor: "pointer",
            opacity: dimmed(l.name) ? 0.10 : lit(l.name) ? 1 : 0.5,
            transition: "opacity 0.2s ease",
          }}
          onClick={() => onNodeClick(l.name, l.side)}
          onMouseEnter={() => setHoveredNode(l.name)}
          onMouseLeave={() => setHoveredNode(null)}
        />
      ))}

      {/* ── Income node bars (left column) ───────────────────────────── */}
      {incomeLayout.map((n, i) => (
        <g key={`in${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(n.name, "income")}
          onMouseEnter={() => setHoveredNode(n.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            fill={isActive(n.name) ? "#fff" : n.color}
            stroke={isActive(n.name) ? n.color : "none"}
            strokeWidth={2}
            style={{
              opacity: dimmed(n.name) ? 0.15 : lit(n.name) ? 1 : 0.5,
              filter: isActive(n.name) ? `drop-shadow(0 0 6px ${n.color}90)` : "none",
              transition: "all 0.2s ease",
            }}
          />
          <NodeLabel
            nodeColor={n.color} name={n.name} value={n.value} pctLbl={n.pctLabel}
            x={n.x} anchor="end" yTop={n.y} nodeH={n.h}
            active={isActive(n.name)} faded={dimmed(n.name)}
          />
        </g>
      ))}

      {/* ── Hub node (center) — label floats in ribbon corridor to the left ── */}
      <g>
        <rect
          x={col1x} y={hubY} width={NODE_W} height={hubH}
          fill={HUB_COLOR}
        />
        {/* Label floats 75% of the way from income column → hub, dark text */}
        {(() => {
          // x = right-edge of income column + 75% of the corridor to the hub
          const labelX = col0x + NODE_W + (col1x - col0x - NODE_W) * 0.75;
          const labelY = hubY + hubH / 2;
          return (
            <>
              <text
                x={labelX} y={labelY - 9}
                textAnchor="middle" dominantBaseline="central"
                style={{
                  fontSize: 11, fontWeight: 800,
                  fill: "#1e293b", letterSpacing: "0.03em",
                  fontFamily: "'Geist Variable', Inter, sans-serif",
                }}
              >
                Income
              </text>
              <text
                x={labelX} y={labelY + 9}
                textAnchor="middle" dominantBaseline="central"
                style={{
                  fontSize: 9.5, fontWeight: 600, fill: "#475569",
                  fontFamily: "'Geist Variable', Inter, sans-serif",
                }}
              >
                {fmt(totalIncome)}
              </text>
            </>
          );
        })()}
      </g>

      {/* ── Spending + Savings node bars (right column) ───────────────── */}
      {spendLayout.map((n, i) => {
        const clickSide = n.name === "Savings" ? "spending" : n.side;
        return (
          <g key={`sp${i}`} style={{ cursor: "pointer" }}
            onClick={() => onNodeClick(n.name, clickSide)}
            onMouseEnter={() => setHoveredNode(n.name)}
            onMouseLeave={() => setHoveredNode(null)}>
            <rect
              x={n.x} y={n.y} width={NODE_W} height={n.h}
              fill={isActive(n.name) ? "#fff" : n.color}
              stroke={isActive(n.name) ? n.color : "none"}
              strokeWidth={2}
              style={{
                opacity: dimmed(n.name) ? 0.15 : lit(n.name) ? 1 : 0.5,
                filter: isActive(n.name) ? `drop-shadow(0 0 6px ${n.color}90)` : "none",
                transition: "all 0.2s ease",
              }}
            />
            <NodeLabel
              nodeColor={n.color} name={n.name} value={n.value} pctLbl={n.pctLabel}
              x={n.x} anchor="start" yTop={n.y} nodeH={n.h}
              active={isActive(n.name)} faded={dimmed(n.name)}
            />
          </g>
        );
      })}
    </svg>
  );
}

/* ── Phase 14 Phase A debug panel ─────────────────────────────────────────── */

// Renders the `payroll_decomposition` block from `/api/reports/flow`.
// This is a *debug* view — the visible Sankey SVG is unchanged in Phase A.
// The real SVG redesign lands in Phase B behind the mockup gate.

const _WITHHOLDING_LABEL: Record<string, string> = {
  federal_tax:   "Federal Tax",
  state_tax:     "State Tax",
  sbp_premium:   "SBP Premium",
  health:        "Health",
  dental_vision: "Dental / Vision",
  other:         "Other",
};

const _WITHHOLDING_COLOR: Record<string, string> = {
  federal_tax:   "#dc2626",
  state_tax:     "#ea580c",
  sbp_premium:   "#ca8a04",
  health:        "#db2777",
  dental_vision: "#9333ea",
  other:         "#475569",
};

function PayrollDecompositionDebugPanel({
  decomposition,
}: {
  decomposition: {
    payroll_rows: Array<{
      snapshot_id: number;
      owner_id: string | null;
      source_label: string;
      pay_period: string;
      gross_cents: number;
      net_cents: number;
      matched_txn_id: string | null;
      withholdings: Array<{ kind: string; cents: number; bucket: string }>;
    }>;
    total_gross_cents: number;
    total_net_cents: number;
    excluded_transaction_ids: string[];
  };
}) {
  const totalGross = decomposition.total_gross_cents / 100;
  const totalNet = decomposition.total_net_cents / 100;
  const totalWithheld = totalGross - totalNet;
  const matched = decomposition.excluded_transaction_ids.length;
  const total = decomposition.payroll_rows.length;

  return (
    <div className="card-l1 border border-amber-200 dark:border-amber-900/40 bg-amber-50/30 dark:bg-amber-950/10">
      <div className="px-6 py-3 flex items-center justify-between border-b border-amber-200/70 dark:border-amber-900/30">
        <div>
          <span className="text-label text-amber-700 dark:text-amber-300">
            PAYROLL DECOMPOSITION
          </span>
          <span className="text-[11px] text-slate-500 ml-3 font-semibold">
            Phase 14 · Phase A debug view — Sankey SVG unchanged
          </span>
        </div>
        <span className="text-[11px] font-bold text-slate-500">
          {matched}/{total} matched to a deposit
        </span>
      </div>

      <div className="px-6 py-4 grid grid-cols-1 lg:grid-cols-4 gap-3 border-b border-amber-200/40 dark:border-amber-900/20">
        <div>
          <p className="text-label">Gross pay</p>
          <p className="text-xl font-extrabold text-numeric">{fmt(totalGross)}</p>
        </div>
        <div>
          <p className="text-label">Withheld</p>
          <p className="text-xl font-extrabold text-numeric text-loss">{fmt(totalWithheld)}</p>
        </div>
        <div>
          <p className="text-label">Net pay</p>
          <p className="text-xl font-extrabold text-numeric text-gain">{fmt(totalNet)}</p>
        </div>
        <div>
          <p className="text-label">Snapshots</p>
          <p className="text-xl font-extrabold text-numeric">{total}</p>
        </div>
      </div>

      <div className="px-6 py-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">
              <th className="text-left  py-2 pr-3">Period</th>
              <th className="text-left  py-2 pr-3">Source</th>
              <th className="text-left  py-2 pr-3">Owner</th>
              <th className="text-right py-2 pr-3">Gross</th>
              <th className="text-right py-2 pr-3">Net</th>
              <th className="text-left  py-2 pr-3">Withholdings (→ CONSUMED)</th>
              <th className="text-center py-2">Deposit match</th>
            </tr>
          </thead>
          <tbody>
            {decomposition.payroll_rows.map(r => {
              const isMatched = r.matched_txn_id !== null;
              return (
                <tr
                  key={`${r.pay_period}-${r.snapshot_id}`}
                  className="border-t border-slate-100 dark:border-slate-800 hover:bg-amber-100/30 dark:hover:bg-amber-900/10"
                >
                  <td className="py-2 pr-3 font-bold">{r.pay_period}</td>
                  <td className="py-2 pr-3 text-slate-500 truncate max-w-[160px]">
                    {r.source_label}
                  </td>
                  <td className="py-2 pr-3 text-slate-500">{r.owner_id ?? "—"}</td>
                  <td className="py-2 pr-3 text-right font-numeric">
                    {fmt(r.gross_cents / 100)}
                  </td>
                  <td className="py-2 pr-3 text-right font-numeric text-gain">
                    {fmt(r.net_cents / 100)}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-wrap gap-1.5">
                      {r.withholdings.map(w => (
                        <span
                          key={w.kind}
                          className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-slate-200 dark:border-slate-700"
                          title={`${w.kind} → ${w.bucket}`}
                        >
                          <span
                            className="inline-block size-2 rounded-full"
                            style={{ background: _WITHHOLDING_COLOR[w.kind] ?? "#64748b" }}
                          />
                          <span className="font-semibold">
                            {_WITHHOLDING_LABEL[w.kind] ?? w.kind}
                          </span>
                          <span className="text-slate-500 font-numeric">
                            {fmt(w.cents / 100)}
                          </span>
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="py-2 text-center">
                    {isMatched ? (
                      <span
                        className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full bg-[var(--color-gain)]/10 text-[var(--color-gain)]"
                        title={`matched to txn ${r.matched_txn_id}`}
                      >
                        <span className="material-symbols-outlined text-[11px]">link</span>
                        matched
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-700 dark:text-amber-300">
                        <span className="material-symbols-outlined text-[11px]">warning</span>
                        no deposit
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {matched === 0 && total > 0 && (
          <p className="text-[11px] text-slate-500 mt-3 italic">
            No payroll snapshots matched a deposit transaction in this window.
            Phase D's scorecard will flag these as <em>missing deposit</em> drift
            sources. (Common with seeded data — source labels and transaction
            merchants are independent.)
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────────────── */

export default function ReportsPage() {
  const { accountNames: ACCOUNT_NAMES, categories: CATEGORIES } = useAccounts();
  // Active view (Quintin / Household / Amy) — threaded into every fetch
  // so the Sankey and transaction list respond to the ViewSelector.
  // Before this wiring the page always rendered the household roll-up.
  const { ownerParam } = useView();

  const [timeframe, setTimeframe] = useSessionState("reports:timeframe", "Last 3 Months");
  const [accountIdFilter, setAccountIdFilter] = useSessionState<string>("reports:accountIdFilter", "");
  const [categoryFilter, setCategoryFilter] = useSessionState<string>("reports:categoryFilter", "");
  const [merchantFilter, setMerchantFilter] = useSessionState<string>("reports:merchantFilter", "");
  const [tagFilter, setTagFilter] = useSessionState<string>("reports:tagFilter", "");

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

  // Resolve the user's preset to explicit local-time dates so the
  // Sankey, transactions panel, and timeLabel all use the same window.
  const window_ = useMemo(() => resolveTimeframe(timeframe), [timeframe]);

  // Fetch flow data
  const fetchFlow = useCallback(() => {
    const params = new URLSearchParams();
    if (window_.start_date) params.set("start_date", window_.start_date);
    params.set("end_date", window_.end_date);
    if (accountIdFilter) params.set("account_id", accountIdFilter);
    if (ownerParam) params.set("owner_id", ownerParam);
    fetch(`http://127.0.0.1:8000/api/reports/flow?${params}`)
      .then(r => r.json())
      .then(setFlowData)
      .catch(console.error);
  }, [window_, accountIdFilter, ownerParam]);
  useEffect(() => { fetchFlow(); }, [fetchFlow]);

  // Fetch transactions for the same window — keeps the side panel
  // and Sankey in lockstep so totals reconcile.
  const fetchTransactions = useCallback(() => {
    const params = new URLSearchParams();
    params.set("limit", "1000");
    if (window_.start_date) params.set("start_date", window_.start_date);
    params.set("end_date", window_.end_date);
    if (accountIdFilter) params.set("account_id", accountIdFilter);
    if (ownerParam) params.set("owner_id", ownerParam);
    fetch(`http://127.0.0.1:8000/api/transactions?${params}`)
      .then(r => r.json())
      .then(d => setTransactions(d.transactions || []))
      .catch(console.error);
  }, [window_, accountIdFilter, ownerParam]);
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
      pctLabel: pct(c.total, totalIncome),   // % of total income, Monarch-style
    }));

    return { incomeNodes, spendNodes, totalIncome, totalSpending, savings };
  }, [flowData]);

  /* ── Filtered transactions ──────────────────────────────────────────────── */
  const filteredTx = useMemo(() => {
    return transactions.filter(tx => {
      // 1. Sankey filter
      if (activeFilter) {
        if (activeFilter.name === "Savings") return false;
        const amt = tx.signed_amount ?? tx.amount;
        if (activeFilter.side === "income") {
          if (!(amt >= 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Other Income")))) return false;
        } else {
          if (!(amt < 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Uncategorized")))) return false;
        }
      }

      // 2. Category filter
      if (categoryFilter && tx.category !== categoryFilter) return false;

      // 3. Merchant filter
      if (merchantFilter) {
        const q = merchantFilter.toLowerCase();
        const desc = (tx.description || tx.merchant || "").toLowerCase();
        if (!desc.includes(q)) return false;
      }

      // 4. Tag filter (was checking categoryFilter — fixed to tagFilter)
      if (tagFilter) {
        const q = tagFilter.toLowerCase();
        const desc = (tx.description || tx.merchant || tx.raw_description || "").toLowerCase();
        if (!desc.includes(q)) return false;
      }

      return true;
    });
  }, [transactions, activeFilter, categoryFilter, merchantFilter, tagFilter]);

  // Auto-scroll when filter changes
  useEffect(() => {
    if (activeFilter && txListRef.current) {
      setTimeout(() => {
        txListRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    }
  }, [activeFilter]);

  /* ── Summary stats ──────────────────────────────────────────────────────── */
  // Drop transfer rows so the side panel agrees with the Sankey totals
  // (the Sankey already filters via the canonical pattern in the API).
  const summary = useMemo(() => {
    const cleanTx = filteredTx.filter((t: any) => !t.transfer_tag);
    if (cleanTx.length === 0) return null;
    const amounts = cleanTx.map(t => t.signed_amount ?? t.amount);
    const income = amounts.filter(a => a >= 0).reduce((s, v) => s + v, 0);
    const spending = Math.abs(amounts.filter(a => a < 0).reduce((s, v) => s + v, 0));
    const isIncome = activeFilter?.side === "income";
    const displayTotal = isIncome ? income : spending;
    const absAmounts = amounts.map(Math.abs);
    const dates = cleanTx.map(t => t.posting_date).filter(Boolean).sort();
    return {
      count: cleanTx.length,
      largest: Math.max(...absAmounts),
      average: displayTotal / cleanTx.length,
      total: displayTotal,
      totalLabel: isIncome ? "Total income" : "Total spending",
      first: dates[0],
      last: dates[dates.length - 1],
    };
  }, [filteredTx, activeFilter]);

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

  /* ── Timeframe label — uses the SAME window as the Sankey + side panel ── */
  const timeLabel = useMemo(() => {
    const fmtDate = (s: string) => {
      const d = new Date(s + "T12:00:00");
      return `${d.toLocaleString("en-US", { month: "short" })} ${d.getDate()}, ${d.getFullYear()}`;
    };
    if (!window_.start_date) return "All time";
    return `${fmtDate(window_.start_date)} – ${fmtDate(window_.end_date)}`;
  }, [window_]);

  /* ── Render ──────────────────────────────────────────────────────────────── */
  const hasActiveFilters = accountIdFilter || categoryFilter || merchantFilter || tagFilter || timeframe !== "Last 3 Months";

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar">

      {/* ── Sticky Toolbar — page title lives in global Header ─────────── */}
      <div className="px-12 py-3 flex items-center gap-3 flex-wrap border-b border-border sticky top-0 bg-background z-10">
        <Select value={timeframe} onValueChange={(val: string | null) => { if (val) { setTimeframe(val); setActiveFilter(null); } }}>
          <SelectTrigger className="w-[160px] h-9 text-xs font-semibold">
            <SelectValue placeholder="Timeframe" />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(TF_MAP).map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={accountIdFilter || "ALL"} onValueChange={(val: string | null) => { setAccountIdFilter(val === "ALL" || !val ? "" : val); setActiveFilter(null); }}>
          <SelectTrigger className="w-[180px] h-9 text-xs font-semibold">
            <SelectValue placeholder="All Accounts" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All Accounts</SelectItem>
            {Object.entries(ACCOUNT_NAMES).map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={categoryFilter || "ALL"} onValueChange={(val: string | null) => { setCategoryFilter(val === "ALL" || !val ? "" : val); }}>
          <SelectTrigger className="w-[170px] h-9 text-xs font-semibold">
            <SelectValue placeholder="All Categories" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All Categories</SelectItem>
            {CATEGORIES.map(cat => <SelectItem key={cat} value={cat}>{cat}</SelectItem>)}
          </SelectContent>
        </Select>

        {/* Merchant Input */}
        <div className="relative">
          <span className="material-symbols-outlined text-sm text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2">storefront</span>
          <input
            type="text"
            placeholder="Merchant..."
            value={merchantFilter}
            onChange={(e) => setMerchantFilter(e.target.value)}
            className="pl-9 pr-4 h-9 bg-card border border-border rounded-md text-xs font-semibold outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[150px]"
          />
        </div>

        {/* Tags Input */}
        <div className="relative">
          <span className="material-symbols-outlined text-sm text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2">sell</span>
          <input
            type="text"
            placeholder="Tag..."
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            className="pl-9 pr-4 h-9 bg-card border border-border rounded-md text-xs font-semibold outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[140px]"
          />
        </div>

        {/* Clear Filters */}
        {hasActiveFilters && (
          <button
            className="flex items-center gap-1 px-3 h-9 text-xs font-semibold text-muted-foreground hover:text-[var(--color-loss)] transition-colors"
            onClick={() => {
              setTimeframe("Last 3 Months");
              setAccountIdFilter("");
              setCategoryFilter("");
              setMerchantFilter("");
              setTagFilter("");
              setActiveFilter(null);
            }}
          >
            <span className="material-symbols-outlined text-xs">close</span>
            Clear
          </button>
        )}
      </div>

      {/* ── Summary cards row ──────────────────────────────────────────────── */}

      <div className="px-12 pt-4 pb-2 grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Total Income",     value: flowData?.total_income,   color: "text-gain" },
          { label: "Total Expenses",   value: flowData?.total_spending, color: "text-loss" },
          { label: "Total Net Income", value: flowData?.net,            color: (flowData?.net ?? 0) >= 0 ? "text-gain" : "text-loss" },
          { label: "Savings Rate",     value: flowData?.savings_rate,   isPct: true, color: "text-[var(--chart-c2)]" },
        ].map((card, i) => (
          <div key={i} className="card-l1 px-5 py-4 text-center">
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
      <div className="px-12 pb-4" ref={chartContainerRef}>
        <div className="card-l1 overflow-visible flex flex-col">
          {/* Chart header */}
          <div className="px-6 py-3 flex items-center justify-between border-b border-slate-100 dark:border-slate-800">
            <div>
              <span className="text-label">CASH FLOW</span>
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

          {/* Chart body — overflow visible so SVG labels can bleed outside */}
          <div className="py-4 overflow-visible">
            {sankeyData ? (
              sankeyData.totalIncome === 0 && sankeyData.totalSpending === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                  <span className="material-symbols-outlined text-4xl mb-3">show_chart</span>
                  <p className="text-sm font-semibold">No data for this period</p>
                  <p className="text-xs mt-1">Try selecting a different timeframe or removing filters</p>
                </div>
              ) : (
                <div style={{ overflowX: "auto", overflowY: "visible" }}>
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
                </div>
              )
            ) : (
              <div className="flex flex-col items-center gap-2 text-slate-400">
                <span className="material-symbols-outlined text-4xl animate-spin" style={{ animationDuration: "2s" }}>hourglass_top</span>
                <p className="text-sm font-semibold">Loading flow data...</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Phase 14 Phase A debug panel: payroll decomposition ──────────── */}
      {flowData?.payroll_decomposition?.payroll_rows?.length > 0 && (
        <div className="px-12 pb-4">
          <PayrollDecompositionDebugPanel
            decomposition={flowData.payroll_decomposition}
          />
        </div>
      )}

      {/* ── Filtered Transactions + Summary ────────────────────────────────── */}
      <div ref={txListRef} className="px-12 pb-12 flex flex-col lg:flex-row gap-4">
        {/* Transaction List */}
        <div className="flex-1 card-l1 flex flex-col overflow-hidden">
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
                    {(tx.signed_amount ?? tx.amount) >= 0 ? "+" : ""}{formatCurrency(tx.signed_amount ?? tx.amount)}
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
                  { label: summary.totalLabel, value: fmt(summary.total), color: "font-extrabold" },
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
    </div>
  );
}
