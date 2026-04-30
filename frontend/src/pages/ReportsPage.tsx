import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { Card } from "@/components/ui/card";
import { PageShell } from "@/components/ui/page-shell";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAccounts } from "@/lib/accounts";
import { formatCurrency } from "@/lib/formatCurrency";
import { useView } from "@/context/ViewContext";
import { useRuntimeContext } from "@/context/RuntimeContext";
import { chartColor } from "@/lib/chartStyle";
import { formatIsoDate, parseIsoDateLocal } from "@/lib/dateUtils";


/* ── Constants ─────────────────────────────────────────────────────────────── */

// ACCOUNT_NAMES now comes from useAccounts() hook inside the component

// CATEGORIES now comes from useAccounts() hook inside the component

// Timeframe presets — order matters (rendered top-to-bottom in the
// dropdown). Default is "Current Month" so the page lands on the same
// window users compare to on the Cash Flow page (which also defaults to
// the current month).
const TF_OPTIONS: readonly string[] = [
  "Current Month",
  "Last Month",
  "Last 3 Months",
  "Year to Date",
  "Last Year",
  "All Time",
] as const;

const TF_DEFAULT = "Current Month";

// Map old saved-state values forward when a user upgrades from a prior
// build. Anything unknown silently falls back to TF_DEFAULT.
const TF_LEGACY_MIGRATION: Record<string, string> = {
  "Last 30 Days": "Current Month",
  "Last 6 Months": "Last 3 Months",
};

function migrateTimeframe(stored: string): string {
  if (TF_OPTIONS.includes(stored as any)) return stored;
  if (TF_LEGACY_MIGRATION[stored]) return TF_LEGACY_MIGRATION[stored];
  return TF_DEFAULT;
}

/**
 * Resolve a timeframe preset to explicit local-time start/end dates.
 * Anchored on the user's local clock so window edges align with
 * calendar months in the user's timezone (no UTC drift).
 *
 * Returns { start_date, end_date } as YYYY-MM-DD strings; `start_date`
 * is null only for "All Time".
 */
function resolveTimeframe(label: string, referenceDate: string): { start_date: string | null; end_date: string } {
  const fmt = formatIsoDate;
  const lastDayOfMonth = (year: number, monthZeroBased: number) =>
    new Date(year, monthZeroBased + 1, 0);
  const today = parseIsoDateLocal(referenceDate);
  const end_date = fmt(today);

  if (label === "All Time") {
    return { start_date: null, end_date };
  }
  if (label === "Current Month") {
    return {
      start_date: fmt(new Date(today.getFullYear(), today.getMonth(), 1)),
      end_date,
    };
  }
  if (label === "Last Month") {
    const firstOfLastMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const lastOfLastMonth = lastDayOfMonth(today.getFullYear(), today.getMonth() - 1);
    return { start_date: fmt(firstOfLastMonth), end_date: fmt(lastOfLastMonth) };
  }
  if (label === "Year to Date") {
    return { start_date: `${today.getFullYear()}-01-01`, end_date };
  }
  if (label === "Last Year") {
    const yr = today.getFullYear() - 1;
    return { start_date: `${yr}-01-01`, end_date: `${yr}-12-31` };
  }
  // "Last N Months" → first of (current month − N + 1) through today
  const m = label.match(/^Last (\d+) Months$/);
  if (m) {
    const n = parseInt(m[1], 10);
    const s = new Date(today.getFullYear(), today.getMonth() - (n - 1), 1);
    return { start_date: fmt(s), end_date };
  }
  // Unknown label — fall back to current-month window (matches default).
  return {
    start_date: fmt(new Date(today.getFullYear(), today.getMonth(), 1)),
    end_date,
  };
}

/* Color palette — dynamic via chart token palette. Income/spend nodes
   cycle through the 8-hue --chart-cN slots so they flex with the Ember
   palette. Semantic accents (hub, mortgage, bypass) map to specific
   slots that preserve the Monarch-money inspired tone relationships. */
const INCOME_COLORS = [
  chartColor(1),  // teal — disability / main income
  chartColor(3),  // amber — other income
  chartColor(5),  // pink — retirement
  chartColor(6),  // burgundy — education benefits
  chartColor(7),  // steel — misc
];
const SPEND_COLORS = [
  chartColor(5),  // burgundy / sentiment-adjacent — housing / mortgage
  chartColor(2),  // amber — food
  chartColor(3),  // copper — financial
  chartColor(4),  // plum — shopping
  chartColor(1),  // teal — auto
  chartColor(0),  // emerald — children
  chartColor(8),  // rust — personal
  chartColor(6),  // burgundy — entertainment
  chartColor(9),  // sage — utilities
  chartColor(10), // mauve — gifts
  chartColor(11), // ochre — health
  chartColor(7),  // neutral — other
];
const HUB_COLOR     = "var(--chart-c1)"; // teal — income hub bar

/* Phase 14 Phase B — terminal bucket palette. */
const BUCKET_FILL: Record<string, string> = {
  CONSUMED:        "var(--color-loss)",
  STORED_LIQUID:   "var(--chart-c2)",
  STORED_ILLIQUID: "var(--color-gain)",
};
const BUCKET_INK: Record<string, string> = {
  CONSUMED:        "var(--color-loss)",
  STORED_LIQUID:   "var(--chart-c2)",
  STORED_ILLIQUID: "var(--color-gain)",
};
const BUCKET_LABEL: Record<string, string> = {
  CONSUMED:        "Spent",
  STORED_LIQUID:   "Kept liquid",
  STORED_ILLIQUID: "Kept illiquid",
};
const MORTGAGE_COLOR = "var(--chart-c6)";   // burgundy — mortgage mid-node
const BYPASS_COLOR   = "var(--chart-c5)";   // plum — bypass synthetic sources

/* Phase 14 Phase D — accountability scorecard thresholds. */
const SCORECARD_GREEN = 0.95;
const SCORECARD_YELLOW = 0.85;

/* ── Helpers ───────────────────────────────────────────────────────────────── */

const fmt = (v: number) => formatCurrency(v);

const pct = (v: number, total: number) =>
  total > 0 ? ((v / total) * 100).toFixed(2) + "%" : "0%";

const testIdPart = (value: unknown) =>
  String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";

/* Phase 14 Phase D — signed cents → "$+123.45" / "$-123.45" string. */
function fmtSignedCents(cents: number): string {
  const sign = cents < 0 ? "-" : (cents > 0 ? "+" : "");
  return sign + formatCurrency(Math.abs(cents) / 100);
}

/* ── Sankey helpers ───────────────────────────────────────────────────────── */

/* Identity pass-through for SVG gradient stop colors. Kept as a seam
   so future substitutions (e.g. theme-reactive color-mix rewrites) can
   hook here without rewriting every call site. */
function toSvgColor(c: string): string {
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
  side: "income" | "hub" | "spending" | "bypass" | "mid" | "bucket";
  pctLabel: string;
}

interface BypassSource {
  id: string;
  label: string;
  value: number;           // dollars
}

interface MortgageSplit {
  totalCents: number;
  principalCents: number;
  interestCents: number;
  escrowCents: number;
  splitCount: number;
  unsplitCount: number;
}

interface IlliquidTransferAgg {
  peerType: string;
  value: number;           // dollars
}

interface ReinvestmentAgg {
  ticker: string;
  value: number;           // dollars — sum of reinvested dividend amounts for this ticker in window
  count: number;
}

interface WithholdingAgg {
  kind: string;
  label: string;
  color: string;
  value: number;           // dollars — aggregated across all payroll rows in the window
}

interface BucketTotals {
  CONSUMED: number;
  STORED_LIQUID: number;
  STORED_ILLIQUID: number;
}

function SankeyChart({
  incomeNodes,
  spendNodes,
  totalIncome,
  totalSpending: _ts,
  bucketTotals,
  bypassSources,
  mortgage,
  illiquidTransferAggs,
  reinvestmentAggs,
  withholdings,
  activeNode,
  onNodeClick,
  containerWidth,
}: {
  incomeNodes: SankeyNodeData[];
  spendNodes: SankeyNodeData[];
  totalIncome: number;
  totalSpending: number;
  bucketTotals: BucketTotals;
  bypassSources: BypassSource[];
  mortgage: MortgageSplit | null;
  illiquidTransferAggs: IlliquidTransferAgg[];
  reinvestmentAggs: ReinvestmentAgg[];
  withholdings: WithholdingAgg[];
  activeNode: string | null;
  onNodeClick: (name: string, side: string) => void;
  containerWidth: number;
}) {
  /* ── Layout constants ─────────────────────────────────────────────────── */
  const NODE_W  = 18;
  const NODE_PAD = 10;
  const MIN_NODE_H = 18;
  const LABEL_W  = 210;
  const LABEL_PAD = 60;

  const svgW = Math.max(1000, containerWidth);

  // 4-column layout — income | hub | mid | buckets.
  const col0x = LABEL_W;
  const col3x = svgW - LABEL_W - NODE_W;
  const chartW = col3x - col0x - NODE_W;
  const col1x = col0x + NODE_W + Math.round(chartW * 0.30);       // hub
  const col2x = col0x + NODE_W + Math.round(chartW * 0.65);       // mid

  /* ── Aggregates ───────────────────────────────────────────────────────── */
  const totalInflow =
    bucketTotals.CONSUMED + bucketTotals.STORED_LIQUID + bucketTotals.STORED_ILLIQUID;
  const liquidBulkThroughHub = Math.max(
    0,
    bucketTotals.STORED_LIQUID,  // liquid flows directly from hub (no mid node)
  );

  // Hub inflow = net (gross minus total withheld). Bypass skips hub;
  // withholdings skip hub too — they fly from the primary paycheck bar
  // directly to CONSUMED (see withholdingLinks below). For windows with
  // no matched payroll, totalWithheld === 0 and hubInflow === totalIncome.
  const totalWithheld = withholdings.reduce((s, w) => s + w.value, 0);
  const hubInflow = Math.max(0, totalIncome - totalWithheld);
  const mortgageTotal = mortgage ? mortgage.totalCents / 100 : 0;

  /* ── Heights ──────────────────────────────────────────────────────────── */
  const PAD_Y = 44;

  // Nodes stacked per column, used to size chart.
  const leftCount = incomeNodes.length + bypassSources.length;
  const midCount = spendNodes.length
    + (mortgage ? 1 : 0)
    + illiquidTransferAggs.length
    + reinvestmentAggs.length;
  const nodesCount = Math.max(leftCount, midCount, 3);  // buckets always 3

  const chartH  = Math.max(480, Math.min(780, nodesCount * 56 + 140));
  const innerH  = chartH - PAD_Y * 2;

  const maxVal  = Math.max(totalInflow, hubInflow, 1);
  const scaleH  = (v: number) =>
    Math.max(MIN_NODE_H, (v / maxVal) * (innerH - NODE_PAD * Math.max(nodesCount, 1)));

  /* ── Column layouts ──────────────────────────────────────────────────── */

  // Left column: income nodes (top) then bypass sources (bottom).
  let incY = PAD_Y;
  const incomeLayout = incomeNodes.map(n => {
    const h = scaleH(n.value);
    const y = incY;
    incY += h + NODE_PAD;
    return { ...n, x: col0x, y, h };
  });
  let bypassY = incY + (incomeLayout.length ? NODE_PAD : 0);
  const bypassLayout = bypassSources.map(b => {
    const h = scaleH(b.value);
    const y = bypassY;
    bypassY += h + NODE_PAD;
    return {
      ...b,
      x: col0x,
      y,
      h,
      color: BYPASS_COLOR,
      name: b.label,
      side: "bypass" as const,
      pctLabel: pct(b.value, totalInflow),
    };
  });

  // Hub — height = hub inflow (not totalInflow, since bypass skips hub).
  const hubH = scaleH(hubInflow);
  const hubY = PAD_Y + (innerH - hubH) / 2;

  // Mid column: spending cats stacked, then mortgage, then illiquid-transfer aggs.
  let midY = PAD_Y;
  const spendMidLayout = spendNodes.map(n => {
    const h = scaleH(n.value);
    const y = midY;
    midY += h + NODE_PAD;
    return {
      ...n,
      x: col2x,
      y,
      h,
      side: "mid" as const,
      pctLabel: pct(n.value, totalInflow),
    };
  });

  const mortgageMidLayout = mortgage
    ? (() => {
        const h = scaleH(mortgageTotal);
        const y = midY;
        midY += h + NODE_PAD;
        return {
          name: "Mortgage payment",
          value: mortgageTotal,
          color: MORTGAGE_COLOR,
          side: "mid" as const,
          pctLabel: pct(mortgageTotal, totalInflow),
          x: col2x,
          y,
          h,
          principalCents: mortgage.principalCents,
          interestCents: mortgage.interestCents,
          escrowCents: mortgage.escrowCents,
          unsplitCount: mortgage.unsplitCount,
        };
      })()
    : null;

  const illiquidTransferLayout = illiquidTransferAggs.map(a => {
    const h = scaleH(a.value);
    const y = midY;
    midY += h + NODE_PAD;
    const name = `Transfer → ${a.peerType}`;
    return {
      name,
      value: a.value,
      color: BUCKET_INK.STORED_ILLIQUID,
      side: "mid" as const,
      pctLabel: pct(a.value, totalInflow),
      x: col2x,
      y,
      h,
      peerType: a.peerType,
    };
  });

  // Phase 14 Phase C — dividend reinvestment mid-nodes (one per ticker
  // that reinvested in the window). The color family matches illiquid
  // transfers since the terminal bucket is the same, but we use the
  // dividend-source blue for the inner node so the two-leg pairing is
  // visually traceable from the left-edge "Investment Income" bar.
  const reinvestmentLayout = reinvestmentAggs.map(a => {
    const h = scaleH(a.value);
    const y = midY;
    midY += h + NODE_PAD;
    return {
      name: `Reinvest · ${a.ticker}`,
      value: a.value,
      color: BUCKET_INK.STORED_ILLIQUID,
      side: "mid" as const,
      pctLabel: pct(a.value, totalInflow),
      x: col2x,
      y,
      h,
      ticker: a.ticker,
      count: a.count,
    };
  });

  // Right column: three terminal buckets (stacked top-to-bottom).
  const bucketOrder: Array<keyof BucketTotals> = [
    "CONSUMED",
    "STORED_LIQUID",
    "STORED_ILLIQUID",
  ];
  let bucketY = PAD_Y;
  const bucketLayout = bucketOrder.map(k => {
    const v = bucketTotals[k];
    const h = scaleH(Math.max(v, 0));
    const y = bucketY;
    bucketY += h + NODE_PAD;
    return {
      key: k,
      name: BUCKET_LABEL[k],
      value: v,
      color: BUCKET_INK[k],
      fill: BUCKET_FILL[k],
      side: "bucket" as const,
      pctLabel: pct(v, totalInflow),
      x: col3x,
      y,
      h,
    };
  });

  const svgH = Math.max(
    chartH,
    bypassY + LABEL_PAD,
    midY + LABEL_PAD,
    bucketY + LABEL_PAD,
  );

  /* ── Build links ──────────────────────────────────────────────────────
   *
   * Flow graph for Phase B:
   *   income[i]            → hub (slice)
   *   bypass[i]            → Kept-illiquid bucket (direct, no hub)
   *   hub → spendMid[i]    → Spent bucket
   *   hub → mortgage mid   → { interest+escrow → Spent, principal → Kept-illiquid }
   *   hub → illiquidMid[i] → Kept-illiquid bucket
   *   hub → Kept-liquid bucket (direct bulk residual)
   */

  type SLink = {
    sx: number; sy: number; sh: number;
    tx: number; ty: number; th: number;
    srcColor: string; dstColor: string;
    name: string; side: string;
  };

  // Bucket y-cursors — each bucket column packs inflows from top.
  // Initialized here (before link building) so withholdings can stack
  // into CONSUMED *first*, landing at the top of the bucket above
  // spending categories and mortgage interest/escrow.
  const bucketInflowY: Record<string, number> = {
    CONSUMED:        bucketLayout[0].y,
    STORED_LIQUID:   bucketLayout[1].y,
    STORED_ILLIQUID: bucketLayout[2].y,
  };
  const bucketAt = (k: string) => bucketLayout.find(b => b.key === k)!;

  // ── Primary paycheck bar + withholdings ────────────────────────────
  // The primary bar is the largest income bar whose gross value can
  // absorb the aggregate withheld amount. All withholding ribbons
  // are peeled off its top edge and fly directly to CONSUMED,
  // skipping the hub. If no bar can absorb them (defensive fallback
  // for unusual data), we fall through to the pre-Phase-B-followup
  // render — the debug panel still shows the breakdown.
  const primaryIdx = (incomeLayout.length > 0 && totalWithheld > 0)
    ? incomeLayout.reduce(
        (bestI, n, i, arr) => (n.value > arr[bestI].value ? i : bestI),
        0,
      )
    : -1;
  const canDrawWithholdings =
    primaryIdx >= 0 && incomeLayout[primaryIdx].value >= totalWithheld;

  let primaryWithheldBottomY = canDrawWithholdings
    ? incomeLayout[primaryIdx].y
    : 0;
  const withholdingLinks: SLink[] = [];
  if (canDrawWithholdings) {
    const primary = incomeLayout[primaryIdx];
    let wy = primary.y;
    for (const w of withholdings) {
      const sh = (w.value / primary.value) * primary.h;
      const bucketH = totalInflow > 0
        ? (w.value / totalInflow) * bucketAt("CONSUMED").h
        : sh;
      withholdingLinks.push({
        sx: primary.x + NODE_W, sy: wy, sh: sh,
        tx: col3x,              ty: bucketInflowY.CONSUMED, th: bucketH,
        srcColor: w.color, dstColor: BUCKET_FILL.CONSUMED,
        name: `${w.label} · withheld`, side: "withhold",
      });
      bucketInflowY.CONSUMED += bucketH;
      wy += sh;
    }
    primaryWithheldBottomY = wy;
  }

  // hub has two y-cursors: one for inflow packing (left side), one for outflow.
  let hubInY = hubY;
  const incomeLinks: SLink[] = incomeLayout.map((n, i) => {
    const isPrimary = i === primaryIdx && canDrawWithholdings;
    const netVal = isPrimary ? (n.value - totalWithheld) : n.value;
    const linkH = hubInflow > 0 ? (netVal / hubInflow) * hubH : 0;
    const sy = isPrimary ? primaryWithheldBottomY : n.y;
    const sh = isPrimary ? (n.h - (primaryWithheldBottomY - n.y)) : n.h;
    const link: SLink = {
      sx: n.x + NODE_W, sy: sy, sh: sh,
      tx: col1x,        ty: hubInY, th: linkH,
      srcColor: n.color, dstColor: HUB_COLOR,
      name: n.name, side: "income",
    };
    hubInY += linkH;
    return link;
  });

  // Bypass → illiquid bucket (direct).
  const bypassLinks: SLink[] = bypassLayout.map(b => {
    const targetBucket = bucketAt("STORED_ILLIQUID");
    const linkH = totalInflow > 0
      ? (b.value / totalInflow) * targetBucket.h
      : b.h;
    const link: SLink = {
      sx: b.x + NODE_W, sy: b.y, sh: b.h,
      tx: col3x,        ty: bucketInflowY.STORED_ILLIQUID, th: linkH,
      srcColor: BYPASS_COLOR, dstColor: BUCKET_FILL.STORED_ILLIQUID,
      name: b.name, side: "bypass",
    };
    bucketInflowY.STORED_ILLIQUID += linkH;
    return link;
  });

  // Hub → mid column (spending categories, mortgage, illiquid-transfer aggs).
  let hubOutY = hubY;
  const hubToMidLinks: SLink[] = [];
  const midToBucketLinks: SLink[] = [];

  // Spending categories.
  spendMidLayout.forEach(n => {
    const linkH = hubInflow > 0 ? (n.value / hubInflow) * hubH : n.h;
    hubToMidLinks.push({
      sx: col1x + NODE_W, sy: hubOutY, sh: linkH,
      tx: n.x,            ty: n.y,     th: n.h,
      srcColor: HUB_COLOR, dstColor: n.color,
      name: n.name, side: n.side,
    });
    hubOutY += linkH;
    // mid → Spent bucket
    const bucketH = totalInflow > 0
      ? (n.value / totalInflow) * bucketAt("CONSUMED").h
      : n.h;
    midToBucketLinks.push({
      sx: n.x + NODE_W, sy: n.y, sh: n.h,
      tx: col3x,        ty: bucketInflowY.CONSUMED, th: bucketH,
      srcColor: n.color, dstColor: BUCKET_FILL.CONSUMED,
      name: n.name, side: n.side,
    });
    bucketInflowY.CONSUMED += bucketH;
  });

  // Mortgage mid-node + its 2-or-3-way split.
  if (mortgageMidLayout) {
    const m = mortgageMidLayout;
    const linkH = hubInflow > 0 ? (m.value / hubInflow) * hubH : m.h;
    hubToMidLinks.push({
      sx: col1x + NODE_W, sy: hubOutY, sh: linkH,
      tx: m.x,            ty: m.y,     th: m.h,
      srcColor: HUB_COLOR, dstColor: m.color,
      name: m.name, side: m.side,
    });
    hubOutY += linkH;

    // Sub-edges: interest + escrow → Spent, principal → Kept illiquid.
    const mortSum = m.principalCents + m.interestCents + m.escrowCents;
    const sliceH = (partCents: number) => mortSum > 0 ? (partCents / mortSum) * m.h : 0;

    // Stack sub-slices on the mortgage bar from top: interest, escrow, principal.
    let subY = m.y;
    const interestH = sliceH(m.interestCents);
    const escrowH   = sliceH(m.escrowCents);
    const principalH = sliceH(m.principalCents);

    if (m.interestCents > 0) {
      const bucketH = totalInflow > 0
        ? (m.interestCents / 100 / totalInflow) * bucketAt("CONSUMED").h
        : interestH;
      midToBucketLinks.push({
        sx: m.x + NODE_W, sy: subY, sh: interestH,
        tx: col3x,        ty: bucketInflowY.CONSUMED, th: bucketH,
        srcColor: m.color, dstColor: BUCKET_FILL.CONSUMED,
        name: `${m.name} · interest`, side: "mid",
      });
      bucketInflowY.CONSUMED += bucketH;
      subY += interestH;
    }
    if (m.escrowCents > 0) {
      const bucketH = totalInflow > 0
        ? (m.escrowCents / 100 / totalInflow) * bucketAt("CONSUMED").h
        : escrowH;
      midToBucketLinks.push({
        sx: m.x + NODE_W, sy: subY, sh: escrowH,
        tx: col3x,        ty: bucketInflowY.CONSUMED, th: bucketH,
        srcColor: m.color, dstColor: BUCKET_FILL.CONSUMED,
        name: `${m.name} · escrow`, side: "mid",
      });
      bucketInflowY.CONSUMED += bucketH;
      subY += escrowH;
    }
    if (m.principalCents > 0) {
      const bucketH = totalInflow > 0
        ? (m.principalCents / 100 / totalInflow) * bucketAt("STORED_ILLIQUID").h
        : principalH;
      midToBucketLinks.push({
        sx: m.x + NODE_W, sy: subY, sh: principalH,
        tx: col3x,        ty: bucketInflowY.STORED_ILLIQUID, th: bucketH,
        srcColor: m.color, dstColor: BUCKET_FILL.STORED_ILLIQUID,
        name: `${m.name} · principal`, side: "mid",
      });
      bucketInflowY.STORED_ILLIQUID += bucketH;
    }
  }

  // Illiquid transfer aggregators.
  illiquidTransferLayout.forEach(n => {
    const linkH = hubInflow > 0 ? (n.value / hubInflow) * hubH : n.h;
    hubToMidLinks.push({
      sx: col1x + NODE_W, sy: hubOutY, sh: linkH,
      tx: n.x,            ty: n.y,     th: n.h,
      srcColor: HUB_COLOR, dstColor: n.color,
      name: n.name, side: n.side,
    });
    hubOutY += linkH;

    const bucketH = totalInflow > 0
      ? (n.value / totalInflow) * bucketAt("STORED_ILLIQUID").h
      : n.h;
    midToBucketLinks.push({
      sx: n.x + NODE_W, sy: n.y, sh: n.h,
      tx: col3x,        ty: bucketInflowY.STORED_ILLIQUID, th: bucketH,
      srcColor: n.color, dstColor: BUCKET_FILL.STORED_ILLIQUID,
      name: n.name, side: n.side,
    });
    bucketInflowY.STORED_ILLIQUID += bucketH;
  });

  // Phase 14 Phase C — dividend reinvestment aggregators.
  // Two-leg flow: hub → Reinvest · TICKER mid node → STORED_ILLIQUID.
  // The income leg (dividend → hub) is already drawn by the
  // `income_categories` pipeline; this just peels the same dollars off
  // the hub and routes them to illiquid so the reinvestment is visible.
  reinvestmentLayout.forEach(n => {
    const linkH = hubInflow > 0 ? (n.value / hubInflow) * hubH : n.h;
    hubToMidLinks.push({
      sx: col1x + NODE_W, sy: hubOutY, sh: linkH,
      tx: n.x,            ty: n.y,     th: n.h,
      srcColor: HUB_COLOR, dstColor: n.color,
      name: n.name, side: n.side,
    });
    hubOutY += linkH;

    const bucketH = totalInflow > 0
      ? (n.value / totalInflow) * bucketAt("STORED_ILLIQUID").h
      : n.h;
    midToBucketLinks.push({
      sx: n.x + NODE_W, sy: n.y, sh: n.h,
      tx: col3x,        ty: bucketInflowY.STORED_ILLIQUID, th: bucketH,
      srcColor: n.color, dstColor: BUCKET_FILL.STORED_ILLIQUID,
      name: n.name, side: n.side,
    });
    bucketInflowY.STORED_ILLIQUID += bucketH;
  });

  // Hub → Kept-liquid bulk residual (direct edge, no mid node).
  const liquidBulkLink: SLink | null = liquidBulkThroughHub > 0 ? (() => {
    const linkH = hubInflow > 0
      ? Math.max(0, (liquidBulkThroughHub / hubInflow) * hubH)
      : Math.max(0, hubH - (hubOutY - hubY));
    const bucketH = totalInflow > 0
      ? (liquidBulkThroughHub / totalInflow) * bucketAt("STORED_LIQUID").h
      : linkH;
    const link: SLink = {
      sx: col1x + NODE_W, sy: hubOutY, sh: linkH,
      tx: col3x,          ty: bucketInflowY.STORED_LIQUID, th: bucketH,
      srcColor: HUB_COLOR, dstColor: BUCKET_FILL.STORED_LIQUID,
      name: "Kept liquid · residual", side: "bucket",
    };
    bucketInflowY.STORED_LIQUID += bucketH;
    return link;
  })() : null;

  const allLinks: SLink[] = [
    ...incomeLinks,
    ...bypassLinks,
    ...withholdingLinks,
    ...hubToMidLinks,
    ...midToBucketLinks,
    ...(liquidBulkLink ? [liquidBulkLink] : []),
  ];

  /* ── Render ───────────────────────────────────────────────────────────── */
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);

  const isActive  = (name: string) => activeNode === name;
  const dimmed    = (name: string) => !!(activeNode && !isActive(name));
  const lit       = (name: string) => hoveredNode === null || hoveredNode === name;

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
    const midYLocal = yTop + Math.min(nodeH / 2, 16);
    const labelOpacity = faded ? 0.15 : lit(name) ? 1 : 0.5;
    return (
      <g style={{ opacity: labelOpacity, transition: "opacity 0.2s ease" }}>
        <circle cx={dotCx} cy={midYLocal} r={4.5} fill={nodeColor} />
        <text x={textX} y={midYLocal - 1} textAnchor={anchor} dominantBaseline="auto"
          style={{ fontSize: 12.5, fontWeight: 700,
            fill: active ? nodeColor : "var(--foreground)",
            fontFamily: "var(--font-sans)",
          }}>
          {name}
        </text>
        <text x={textX} y={midYLocal + 15} textAnchor={anchor} dominantBaseline="auto"
          style={{ fontSize: 10.5, fontWeight: 500, fill: "var(--muted-foreground)",
            fontFamily: "var(--font-sans)",
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

      {/* ── Ribbons ───────────────────────────────────────────────────── */}
      {allLinks.map((l, i) => {
        const isBypass = l.side === "bypass";
        return (
          <path
            key={`lnk${i}`}
            d={sankeyLinkPath(l.sx, l.sy, l.sh, l.tx, l.ty, l.th)}
            fill={`url(#g${i})`}
            stroke={toSvgColor(l.srcColor)}
            strokeWidth={isBypass ? 1.0 : 0.6}
            strokeDasharray={isBypass ? "5 3" : undefined}
            strokeOpacity={dimmed(l.name) ? 0.05 : lit(l.name) ? (isBypass ? 0.55 : 0.18) : 0.09}
            style={{
              cursor: "pointer",
              opacity: dimmed(l.name) ? 0.10 : lit(l.name) ? 1 : 0.5,
              transition: "opacity 0.2s ease",
            }}
            onClick={() => onNodeClick(l.name, l.side)}
            onMouseEnter={() => setHoveredNode(l.name)}
            onMouseLeave={() => setHoveredNode(null)}
          >
            <title>{l.name}</title>
          </path>
        );
      })}

      {/* ── Income node bars (left column) ───────────────────────────── */}
      {incomeLayout.map((n, i) => {
        const paintsStripes = i === primaryIdx && canDrawWithholdings;
        return (
        <g key={`in${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(n.name, "income")}
          onMouseEnter={() => setHoveredNode(n.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            fill={isActive(n.name) ? "var(--card)" : n.color}
            stroke={isActive(n.name) ? n.color : "none"}
            strokeWidth={2}
            style={{
              opacity: dimmed(n.name) ? 0.15 : lit(n.name) ? 1 : 0.5,
              filter: isActive(n.name) ? `drop-shadow(0 0 6px ${n.color}90)` : "none",
              transition: "all 0.2s ease",
            }}
          />
          {/* Withholding stripes on the primary paycheck bar — visual
              hint that the top slice of gross is never cash to the hub. */}
          {paintsStripes && (() => {
            let sy = n.y;
            return withholdings.map(w => {
              const sh = (w.value / n.value) * n.h;
              const el = (
                <rect
                  key={w.kind}
                  x={n.x} y={sy} width={NODE_W} height={sh}
                  fill={w.color} opacity={0.80}
                  style={{
                    opacity: dimmed(n.name) ? 0.15 : 0.80,
                    transition: "opacity 0.2s ease",
                  }}
                >
                  <title>{w.label} — {fmt(w.value)} withheld</title>
                </rect>
              );
              sy += sh;
              return el;
            });
          })()}
          <NodeLabel
            nodeColor={n.color} name={n.name} value={n.value} pctLbl={n.pctLabel}
            x={n.x} anchor="end" yTop={n.y} nodeH={n.h}
            active={isActive(n.name)} faded={dimmed(n.name)}
          />
        </g>
        );
      })}

      {/* ── Bypass synthetic source bars (left column, below income) ── */}
      {bypassLayout.map((b, i) => (
        <g key={`by${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(b.name, "bypass")}
          onMouseEnter={() => setHoveredNode(b.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={b.x} y={b.y} width={NODE_W} height={b.h}
            fill={BYPASS_COLOR}
            stroke={BYPASS_COLOR}
            strokeDasharray="3 2"
            style={{
              opacity: dimmed(b.name) ? 0.15 : lit(b.name) ? 1 : 0.5,
              transition: "all 0.2s ease",
            }}
          />
          <NodeLabel
            nodeColor={BYPASS_COLOR} name={b.name} value={b.value} pctLbl={b.pctLabel}
            x={b.x} anchor="end" yTop={b.y} nodeH={b.h}
            active={isActive(b.name)} faded={dimmed(b.name)}
          />
        </g>
      ))}

      {/* ── Hub (col1) ───────────────────────────────────────────────── */}
      <g>
        <rect
          x={col1x} y={hubY} width={NODE_W} height={hubH}
          fill={HUB_COLOR}
        />
        {(() => {
          const labelX = col0x + NODE_W + (col1x - col0x - NODE_W) * 0.75;
          const labelY = hubY + hubH / 2;
          return (
            <>
              <text
                x={labelX} y={labelY - 9}
                textAnchor="middle" dominantBaseline="central"
                style={{
                  fontSize: 11, fontWeight: 800,
                  fill: "var(--foreground)", letterSpacing: "0.03em",
                  fontFamily: "var(--font-sans)",
                }}
              >
                Hub
              </text>
              <text
                x={labelX} y={labelY + 9}
                textAnchor="middle" dominantBaseline="central"
                style={{
                  fontSize: 9.5, fontWeight: 600, fill: "var(--muted-foreground)",
                  fontFamily: "var(--font-sans)",
                }}
              >
                {fmt(hubInflow)}
              </text>
            </>
          );
        })()}
      </g>

      {/* ── Mid-column nodes (col2): spending cats + mortgage + illiquid agg ── */}
      {spendMidLayout.map((n, i) => (
        <g key={`smid${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(n.name, "spending")}
          onMouseEnter={() => setHoveredNode(n.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            fill={isActive(n.name) ? "var(--card)" : n.color}
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
      ))}

      {/* Mortgage mid-node: the bar itself + inner split stripes */}
      {mortgageMidLayout && (() => {
        const m = mortgageMidLayout;
        const mortSum = m.principalCents + m.interestCents + m.escrowCents;
        const stripe = (cents: number) => mortSum > 0 ? (cents / mortSum) * m.h : 0;
        let sy = m.y;
        return (
          <g key="mortmid" style={{ cursor: "pointer" }}
            onClick={() => onNodeClick(m.name, "mid")}
            onMouseEnter={() => setHoveredNode(m.name)}
            onMouseLeave={() => setHoveredNode(null)}>
            {/* Base bar */}
            <rect x={m.x} y={m.y} width={NODE_W} height={m.h} fill={m.color} />
            {/* Interest stripe (red) */}
            {m.interestCents > 0 && (() => {
              const sh = stripe(m.interestCents);
              const el = <rect key="i" x={m.x} y={sy} width={NODE_W} height={sh}
                fill={BUCKET_FILL.CONSUMED} opacity={0.75} />;
              sy += sh;
              return el;
            })()}
            {m.escrowCents > 0 && (() => {
              const sh = stripe(m.escrowCents);
              const el = <rect key="e" x={m.x} y={sy} width={NODE_W} height={sh}
                fill={BUCKET_FILL.CONSUMED} opacity={0.55} />;
              sy += sh;
              return el;
            })()}
            {m.principalCents > 0 && (() => {
              const sh = stripe(m.principalCents);
              return <rect key="p" x={m.x} y={sy} width={NODE_W} height={sh}
                fill={BUCKET_FILL.STORED_ILLIQUID} opacity={0.85} />;
            })()}
            <NodeLabel
              nodeColor={m.color} name={m.name} value={m.value} pctLbl={m.pctLabel}
              x={m.x} anchor="start" yTop={m.y} nodeH={m.h}
              active={isActive(m.name)} faded={dimmed(m.name)}
            />
            {m.unsplitCount > 0 && (
              <text x={m.x + NODE_W + 24} y={m.y + Math.min(m.h / 2, 16) + 30}
                textAnchor="start"
                style={{ fontSize: 9.5, fontWeight: 600, fill: "var(--color-warning)",
                  fontFamily: "var(--font-sans)" }}>
                {m.unsplitCount} split{m.unsplitCount !== 1 ? "s" : ""} pending
              </text>
            )}
          </g>
        );
      })()}

      {/* Illiquid-transfer aggregator bars */}
      {illiquidTransferLayout.map((n, i) => (
        <g key={`ilq${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(n.name, "mid")}
          onMouseEnter={() => setHoveredNode(n.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            fill={n.color}
            style={{
              opacity: dimmed(n.name) ? 0.15 : lit(n.name) ? 0.85 : 0.5,
              transition: "all 0.2s ease",
            }}
          />
          <NodeLabel
            nodeColor={n.color} name={n.name} value={n.value} pctLbl={n.pctLabel}
            x={n.x} anchor="start" yTop={n.y} nodeH={n.h}
            active={isActive(n.name)} faded={dimmed(n.name)}
          />
        </g>
      ))}

      {/* Phase 14 Phase C — Dividend reinvestment mid-nodes */}
      {reinvestmentLayout.map((n, i) => (
        <g key={`rinv${i}`} style={{ cursor: "pointer" }}
          onClick={() => onNodeClick(n.name, "mid")}
          onMouseEnter={() => setHoveredNode(n.name)}
          onMouseLeave={() => setHoveredNode(null)}>
          <rect
            x={n.x} y={n.y} width={NODE_W} height={n.h}
            fill={n.color}
            stroke={INCOME_COLORS[0]}
            strokeDasharray="3 2"
            strokeWidth={1.2}
            style={{
              opacity: dimmed(n.name) ? 0.15 : lit(n.name) ? 0.95 : 0.5,
              transition: "all 0.2s ease",
            }}
          >
            <title>
              {`${n.name} — ${n.count} reinvested ${n.count === 1 ? "dividend" : "dividends"} in window`}
            </title>
          </rect>
          <NodeLabel
            nodeColor={n.color} name={n.name} value={n.value} pctLbl={n.pctLabel}
            x={n.x} anchor="start" yTop={n.y} nodeH={n.h}
            active={isActive(n.name)} faded={dimmed(n.name)}
          />
        </g>
      ))}

      {/* ── Three terminal buckets (col3) ────────────────────────────── */}
      {bucketLayout.map((b, i) => {
        const contributors: string[] = [];
        if (b.key === "CONSUMED") {
          withholdings.forEach(w =>
            contributors.push(`${w.label} (withheld): ${fmt(w.value)}`),
          );
          spendMidLayout.forEach(n => contributors.push(`${n.name}: ${fmt(n.value)}`));
          if (mortgageMidLayout) {
            const interestD = mortgageMidLayout.interestCents / 100;
            const escrowD   = mortgageMidLayout.escrowCents / 100;
            if (interestD > 0) contributors.push(`Mortgage interest: ${fmt(interestD)}`);
            if (escrowD > 0)   contributors.push(`Mortgage escrow: ${fmt(escrowD)}`);
          }
        } else if (b.key === "STORED_ILLIQUID") {
          if (mortgageMidLayout && mortgageMidLayout.principalCents > 0) {
            contributors.push(
              `Mortgage principal: ${fmt(mortgageMidLayout.principalCents / 100)}`,
            );
          }
          illiquidTransferLayout.forEach(n => contributors.push(`${n.name}: ${fmt(n.value)}`));
          reinvestmentLayout.forEach(n =>
            contributors.push(`${n.name} (dividend reinvest): ${fmt(n.value)}`),
          );
          bypassLayout.forEach(b => contributors.push(`${b.name} (bypass): ${fmt(b.value)}`));
        } else if (b.key === "STORED_LIQUID") {
          if (liquidBulkThroughHub > 0) {
            contributors.push(`Residual (HYSA / brokerage cash / checking): ${fmt(liquidBulkThroughHub)}`);
          }
        }
        const tipLines = contributors.length ? contributors.join("\n") : "(no flows)";
        return (
          <g key={`bk${i}`} style={{ cursor: "pointer" }}
            onClick={() => onNodeClick(b.name, "bucket")}
            onMouseEnter={() => setHoveredNode(b.name)}
            onMouseLeave={() => setHoveredNode(null)}>
            <rect
              x={b.x} y={b.y} width={NODE_W} height={b.h}
              fill={b.fill}
              style={{
                opacity: dimmed(b.name) ? 0.20 : lit(b.name) ? 1 : 0.55,
                transition: "all 0.2s ease",
              }}
            />
            {/* Outer bucket label — Phase B uses muted-colour ink + big label */}
            <text x={b.x + NODE_W + 14} y={b.y + 14}
              style={{ fontSize: 13.5, fontWeight: 800, fill: b.color,
                fontFamily: "var(--font-sans)",
                opacity: lit(b.name) ? 1 : 0.55, transition: "opacity 0.2s ease" }}>
              {b.name}
            </text>
            <text x={b.x + NODE_W + 14} y={b.y + 29}
              style={{ fontSize: 11.5, fontWeight: 600, fill: "var(--muted-foreground)",
                fontFamily: "var(--font-sans)",
                fontVariantNumeric: "tabular-nums",
                opacity: lit(b.name) ? 1 : 0.55, transition: "opacity 0.2s ease" }}>
              {fmt(b.value)} ({b.pctLabel})
            </text>
            <title>{b.name} — {fmt(b.value)}\n\n{tipLines}</title>
          </g>
        );
      })}

      {/* ── Column captions ──────────────────────────────────────────── */}
      <text x={col0x + NODE_W / 2} y={svgH - 12} textAnchor="middle"
        style={{ fontSize: 10, fontWeight: 700, fill: "var(--muted-foreground)",
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "var(--font-sans)" }}>SOURCE</text>
      <text x={col1x + NODE_W / 2} y={svgH - 12} textAnchor="middle"
        style={{ fontSize: 10, fontWeight: 700, fill: "var(--muted-foreground)",
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "var(--font-sans)" }}>HUB</text>
      <text x={col2x + NODE_W / 2} y={svgH - 12} textAnchor="middle"
        style={{ fontSize: 10, fontWeight: 700, fill: "var(--muted-foreground)",
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "var(--font-sans)" }}>CATEGORIES · MORTGAGE</text>
      <text x={col3x + NODE_W / 2} y={svgH - 12} textAnchor="middle"
        style={{ fontSize: 10, fontWeight: 700, fill: "var(--foreground)",
          letterSpacing: "0.08em", textTransform: "uppercase",
          fontFamily: "var(--font-sans)" }}>TERMINAL BUCKETS</text>
    </svg>
  );
}

/* ── Phase 14 Phase A debug panel ─────────────────────────────────────────── */

// Renders the `payroll_decomposition` block from `/api/reports/flow`.
// This is a *debug* view — the visible Sankey SVG is unchanged in Phase A.
// The real SVG redesign lands in Phase B behind the mockup gate.

const WITHHOLDING_LABEL: Record<string, string> = {
  federal_tax:   "Federal Tax",
  state_tax:     "State Tax",
  sbp_premium:   "SBP Premium",
  health:        "Health",
  dental_vision: "Dental / Vision",
  other:         "Other",
};

const WITHHOLDING_COLOR: Record<string, string> = {
  federal_tax:   "var(--color-loss)",   // dominant deduction = sentiment loss
  state_tax:     "var(--chart-c3)",     // amber secondary tax
  sbp_premium:   "var(--chart-c6)",     // burgundy military benefit
  health:        "var(--chart-c4)",     // plum
  dental_vision: "var(--chart-c5)",     // pink/olive
  other:         "var(--color-neutral)", // warm neutral
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
    <div className="card-l1 border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5">
      <div className="px-6 py-3 flex items-center justify-between border-b border-[var(--color-warning)]/30">
        <div>
          <span className="text-label text-[var(--color-warning)]">
            PAYROLL DECOMPOSITION
          </span>
          <span className="text-[11px] text-muted-foreground ml-3 font-semibold">
            Phase 14 · per-snapshot breakdown — Sankey paints the roll-up as stripes + ribbons
          </span>
        </div>
        <span className="text-[11px] font-bold text-muted-foreground">
          {matched}/{total} matched to a deposit
        </span>
      </div>

      <div className="px-6 py-4 grid grid-cols-1 lg:grid-cols-4 gap-3 border-b border-[var(--color-warning)]/20">
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
            <tr className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">
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
                  className="border-t border-border hover:bg-[var(--color-warning)]/10"
                >
                  <td className="py-2 pr-3 font-bold">{r.pay_period}</td>
                  <td className="py-2 pr-3 text-muted-foreground truncate max-w-[160px]">
                    {r.source_label}
                  </td>
                  <td className="py-2 pr-3 text-muted-foreground">{r.owner_id ?? "—"}</td>
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
                          className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border border-border"
                          title={`${w.kind} → ${w.bucket}`}
                        >
                          <span
                            className="inline-block size-2 rounded-full"
                            style={{ background: WITHHOLDING_COLOR[w.kind] ?? "var(--muted-foreground)" }}
                          />
                          <span className="font-semibold">
                            {WITHHOLDING_LABEL[w.kind] ?? w.kind}
                          </span>
                          <span className="text-muted-foreground font-numeric">
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
                      <span className="inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-full bg-[var(--color-warning)]/10 text-[var(--color-warning)]">
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
          <p className="text-[11px] text-muted-foreground mt-3 italic">
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

/* ── Phase 14 Phase B — Three-bucket terminal panel ─────────────────────────── */

// Renders the bucket_totals + mortgage_splits + transfer_flows + bypass_flows
// blocks from `/api/reports/flow`. Until the cosmetic Sankey rework lands
// (scoped separately), this panel is the user-facing home for Phase B data.
// Colors mirror the mockup at ~/.claude/plans/phase14-phase-b-sankey-mockup.html.

const _BUCKET_COLOR: Record<string, string> = {
  CONSUMED:        "var(--color-loss)",
  STORED_LIQUID:   "var(--chart-c2)",
  STORED_ILLIQUID: "var(--color-gain)",
};
const _BUCKET_INK: Record<string, string> = {
  CONSUMED:        "var(--color-loss)",
  STORED_LIQUID:   "var(--chart-c2)",
  STORED_ILLIQUID: "var(--color-gain)",
};
const _BUCKET_LABEL: Record<string, string> = {
  CONSUMED:        "Spent",
  STORED_LIQUID:   "Kept liquid",
  STORED_ILLIQUID: "Kept illiquid",
};

interface TerminalBucketsPayload {
  bucket_totals: { CONSUMED: number; STORED_LIQUID: number; STORED_ILLIQUID: number };
  bucket_totals_cents: { CONSUMED: number; STORED_LIQUID: number; STORED_ILLIQUID: number };
  total_inflow_cents: number;
  bucket_invariant_drift_cents: number;
  mortgage_splits: Array<{
    transaction_id: string;
    posting_date: string;
    principal_cents: number;
    interest_cents: number;
    escrow_cents: number;
    method: string;
  }>;
  transfer_flows: Array<{
    transaction_id: string;
    posting_date: string;
    amount_cents: number;
    peer_account_id: string;
    peer_account_type: string;
    shape: "A" | "B";  // v43: A=paired transactions, B=bank_txn_id-linked brokerage
    bucket: string;
  }>;
  bypass_flows: Array<{
    source_id: string;
    display_label: string;
    owner_id: string;
    tax_treatment: string;
    amount_cents: number;
    monthly_amount_cents: number;
    months: number;
    bucket: string;
  }>;
}

function TerminalBucketsPanel({ data }: { data: TerminalBucketsPayload }) {
  const total =
    data.bucket_totals.CONSUMED +
    data.bucket_totals.STORED_LIQUID +
    data.bucket_totals.STORED_ILLIQUID;
  const inflow = data.total_inflow_cents / 100;
  const drift = data.bucket_invariant_drift_cents;
  const driftPass = Math.abs(drift) <= 100;  // $1 tolerance

  const fmtPct = (v: number) =>
    total > 0 ? `${((v / total) * 100).toFixed(1)}%` : "—";

  const unsplitCount = data.mortgage_splits.filter(m => m.method === "unsplit").length;

  return (
    <div className="card-l1 border border-[var(--color-gain)]/30 bg-gain-subtle">
      <div className="px-6 py-3 flex items-center justify-between border-b border-[var(--color-gain)]/30">
        <div>
          <span className="text-label text-gain">
            TERMINAL BUCKETS
          </span>
          <span className="text-[11px] text-muted-foreground ml-3 font-semibold">
            Phase 14 · Phase B — every dollar in the window lands in one of three buckets
          </span>
        </div>
        <span
          className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${
            driftPass
              ? "bg-[var(--color-gain)]/10 text-[var(--color-gain)]"
              : "bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
          }`}
          title={`buckets − inflow = ${drift >= 0 ? "+" : ""}${drift}¢ (tolerance ±100¢)`}
        >
          {driftPass ? "invariant ✓" : "drift warning"}
        </span>
      </div>

      <div className="px-6 py-4 grid grid-cols-1 lg:grid-cols-3 gap-3">
        {(["CONSUMED", "STORED_LIQUID", "STORED_ILLIQUID"] as const).map(b => (
          <div
            key={b}
            className="rounded-lg p-4 border"
            style={{
              background: `${_BUCKET_COLOR[b]}15`,
              borderColor: `${_BUCKET_COLOR[b]}55`,
            }}
          >
            <div className="text-label" style={{ color: _BUCKET_INK[b] }}>
              {_BUCKET_LABEL[b]}
            </div>
            <div
              className="text-2xl font-extrabold text-numeric mt-1"
              style={{ color: _BUCKET_INK[b] }}
              data-testid={`reports-bucket-total-${testIdPart(b)}`}
            >
              {fmt(data.bucket_totals[b])}
            </div>
            <div className="text-[11px] text-muted-foreground mt-1">
              <span data-testid={`reports-bucket-percent-${testIdPart(b)}`}>{fmtPct(data.bucket_totals[b])}</span> of ${total.toLocaleString()}
            </div>
          </div>
        ))}
      </div>

      {/* Mortgage decomposition rows */}
      {data.mortgage_splits.length > 0 && (
        <div className="px-6 py-3 border-t border-[var(--color-gain)]/20">
          <div className="text-label mb-2">
            Mortgage decomposition
            {unsplitCount > 0 && (
              <span className="ml-2 text-[11px] text-[var(--color-warning)]">
                ({unsplitCount} pending next refresh)
              </span>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {data.mortgage_splits.map(m => (
              <div
                key={m.transaction_id}
                className="flex items-center justify-between text-[12px] rounded bg-card/60 px-3 py-1.5"
                title={m.method}
              >
                <span className="font-semibold text-foreground">
                  {m.posting_date}
                </span>
                <span className="flex gap-3 text-[11.5px] font-numeric">
                  <span style={{ color: _BUCKET_INK.STORED_ILLIQUID }}>
                    P {fmt(m.principal_cents / 100)}
                  </span>
                  <span style={{ color: _BUCKET_INK.CONSUMED }}>
                    I {fmt(m.interest_cents / 100)}
                  </span>
                  <span style={{ color: _BUCKET_INK.CONSUMED }}>
                    E {fmt(m.escrow_cents / 100)}
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transfer flows rollup (by bucket) */}
      {data.transfer_flows.length > 0 && (
        <div className="px-6 py-3 border-t border-[var(--color-gain)]/20">
          <div className="text-label mb-2">
            Transfer flows ({data.transfer_flows.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {data.transfer_flows.map(t => (
              <span
                key={t.transaction_id}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border"
                style={{
                  borderColor: `${_BUCKET_COLOR[t.bucket]}55`,
                  background: `${_BUCKET_COLOR[t.bucket]}15`,
                  color: _BUCKET_INK[t.bucket],
                }}
                title={`${t.peer_account_type || "unknown peer"} · ${t.posting_date} · shape ${t.shape}`}
              >
                <span className="font-semibold">{t.peer_account_type || "peer?"}</span>
                <span className="font-numeric">{fmt(t.amount_cents / 100)}</span>
                <span className="opacity-60">→ {_BUCKET_LABEL[t.bucket]}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Bypass pseudo-flows */}
      {data.bypass_flows.length > 0 && (
        <div className="px-6 py-3 border-t border-[var(--color-gain)]/20">
          <div className="text-label mb-2">Bypass pseudo-flows (no cash leg)</div>
          <div className="flex flex-wrap gap-2">
            {data.bypass_flows.map(b => (
              <span
                key={b.source_id}
                className="inline-flex items-center gap-1.5 text-[11.5px] px-2 py-1 rounded border border-dashed"
                style={{
                  borderColor: `${_BUCKET_INK.STORED_ILLIQUID}aa`,
                  color: _BUCKET_INK.STORED_ILLIQUID,
                  background: `${_BUCKET_COLOR.STORED_ILLIQUID}12`,
                }}
                title={`${b.tax_treatment} · ${b.months}mo × ${fmt(b.monthly_amount_cents / 100)}`}
              >
                <span className="font-semibold">{b.display_label}</span>
                <span className="font-numeric">{fmt(b.amount_cents / 100)}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="px-6 py-2 text-[10.5px] text-muted-foreground border-t border-[var(--color-gain)]/15">
        <span className="font-semibold">Invariant:</span>{" "}
        buckets sum = ${total.toLocaleString()} · inflow = ${inflow.toLocaleString()} ·
        drift = {drift >= 0 ? "+" : ""}{drift}¢
      </div>
    </div>
  );
}

/* ── Phase 14 Phase D — Accountability Scorecard ──────────────────────────── */

type DriftSource = {
  id: string;
  label: string;
  severity: "warning" | "info";
  fix_action: "recategorize" | "refresh_portfolio" | "upload_ras"
    | "update_valuation" | "update_vehicle_value" | null;
  fix_payload: Record<string, unknown>;
  magnitude_cents: number;
};

type Accountability = {
  start_date: string;
  end_date: string;
  net_worth_start_cents: number;
  net_worth_end_cents: number;
  net_worth_delta_cents: number;
  identity_terms: {
    dollars_in_cents: number;
    dollars_spent_cents: number;
    market_value_delta_cents: number;
    real_estate_delta_cents: number;
    vehicle_delta_cents: number;
  };
  unexplained_cents: number;
  accounted_for_pct: number;
  drift_sources: DriftSource[];
};

function scorecardTone(pct: number): "green" | "yellow" | "red" {
  if (pct >= SCORECARD_GREEN) return "green";
  if (pct >= SCORECARD_YELLOW) return "yellow";
  return "red";
}

function AccountabilityScorecard({
  data,
  timeLabel,
  onOpen,
}: {
  data: Accountability | null;
  timeLabel: string;
  onOpen: () => void;
}) {
  // Defensive guard: the fetch may land a 404 / error shape before the
  // backend restart picks up the new endpoint — don't crash the page.
  if (!data || typeof data.net_worth_delta_cents !== "number" || !Array.isArray(data.drift_sources)) {
    return (
      <div className="card-l1 px-6 py-4 flex items-center text-xs text-muted-foreground italic">
        Loading dollar-accountability scorecard…
      </div>
    );
  }
  // Empty-state windows (no NW change) — render a neutral line rather than
  // a fake "100% accounted" so the scorecard never celebrates nothing.
  if (data.net_worth_delta_cents === 0) {
    return (
      <div className="card-l1 px-6 py-4 flex items-center gap-4">
        <div className="text-xl font-extrabold text-muted-foreground">—</div>
        <div>
          <div className="text-sm font-semibold">
            No net-worth change recorded for this window.
          </div>
          <div className="text-[11.5px] text-muted-foreground mt-0.5">
            {timeLabel}
          </div>
          <div className="sr-only">
            <span data-testid="reports-accountability-accounted-for-percent">{(data.accounted_for_pct * 100).toFixed(1)}%</span>
            <span data-testid="reports-accountability-net-worth-delta">{fmtSignedCents(data.net_worth_delta_cents)}</span>
            <span data-testid="reports-accountability-unexplained-amount">{fmtSignedCents(data.unexplained_cents)}</span>
            <span data-testid="reports-accountability-drift-source-count">{data.drift_sources.length}</span>
          </div>
        </div>
      </div>
    );
  }

  const tone = scorecardTone(data.accounted_for_pct);
  const pctStr = (data.accounted_for_pct * 100).toFixed(1);
  const deltaStr = fmtSignedCents(data.net_worth_delta_cents);
  const unexplainedStr = fmtSignedCents(data.unexplained_cents);
  const driftCount = data.drift_sources.length;

  const toneBar: Record<string, string> = {
    green:  "border-l-[var(--color-gain)]",
    yellow: "border-l-[var(--color-warning)]",
    red:    "border-l-[var(--color-loss)]",
  };
  const toneText: Record<string, string> = {
    green:  "text-gain",
    yellow: "text-[var(--color-warning)]",
    red:    "text-loss",
  };
  const title =
    tone === "green"
      ? "We've accounted for every dollar of your net-worth change."
      : tone === "yellow"
      ? `${(100 - data.accounted_for_pct * 100).toFixed(1)}% of your net-worth change is unexplained.`
      : `${(100 - data.accounted_for_pct * 100).toFixed(1)}% of your net-worth change is unaccounted for.`;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}
      className={`card-l1 px-6 py-4 flex items-center gap-5 cursor-pointer hover:shadow-md transition-shadow border-l-4 ${toneBar[tone]}`}
    >
      <div className="flex items-baseline gap-0.5 shrink-0">
        <span className={`text-4xl font-extrabold text-numeric leading-none ${toneText[tone]}`} data-testid="reports-accountability-accounted-for-percent">
          {pctStr}<span className={`text-lg font-semibold ${toneText[tone]} opacity-70`}>%</span>
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold leading-tight">{title}</div>
        <div className="text-[11.5px] text-muted-foreground mt-1 truncate">
          {timeLabel} · Δ <span data-testid="reports-accountability-net-worth-delta">{deltaStr}</span>
          {data.unexplained_cents !== 0 && <> · <span data-testid="reports-accountability-unexplained-amount">{unexplainedStr}</span> unexplained</>}
          {driftCount > 0 && <> · <span data-testid="reports-accountability-drift-source-count">{driftCount}</span> drift source{driftCount === 1 ? "" : "s"}</>}
          {driftCount === 0 && <span className="sr-only" data-testid="reports-accountability-drift-source-count">0</span>}
        </div>
      </div>
      <div className="hidden md:flex items-center gap-1 px-3 py-1.5 text-[11.5px] font-semibold text-muted-foreground bg-surface-raised border border-border rounded-md shrink-0">
        Show breakdown →
      </div>
    </div>
  );
}

function AccountabilityModal({
  data,
  onClose,
}: {
  data: Accountability;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const t = data.identity_terms;
  const tone = scorecardTone(data.accounted_for_pct);
  const toneTxt: Record<string, string> = {
    green:  "text-gain",
    yellow: "text-[var(--color-warning)]",
    red:    "text-loss",
  };

  // Route a fix action to the appropriate page. The backend payload keeps
  // routing policy on the client side (URLs can change without a DAL rev).
  const fixClick = (d: DriftSource) => {
    switch (d.fix_action) {
      case "recategorize": {
        const ids = (d.fix_payload?.transaction_ids as string[] | undefined) || [];
        navigate(`/transactions${ids.length ? `?txn_ids=${encodeURIComponent(ids.join(","))}` : ""}`);
        onClose();
        break;
      }
      case "refresh_portfolio":
      case "update_vehicle_value":
      case "update_valuation":
        navigate("/accounts");
        onClose();
        break;
      case "upload_ras":
        navigate("/documents");
        onClose();
        break;
      default:
        break;
    }
  };

  // Close on Escape.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/48 flex items-start justify-center overflow-y-auto p-8"
      onClick={onClose}
    >
      <div
        className="card-l1 bg-card max-w-4xl w-full p-8 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Head */}
        <div className="flex justify-between items-start pb-5 mb-5 border-b border-border">
          <div>
            <div className="text-lg font-bold tracking-tight">
              Dollar accountability · {data.start_date} → {data.end_date}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              NW {fmt(data.net_worth_start_cents / 100)} → {fmt(data.net_worth_end_cents / 100)}
              {"  · "}
              <span className="font-semibold">Δ {fmtSignedCents(data.net_worth_delta_cents)}</span>
              {"  · "}
              <span className={toneTxt[tone] + " font-semibold"}>
                {(data.accounted_for_pct * 100).toFixed(1)}% accounted for
              </span>
            </div>
          </div>
          <button
            aria-label="Close"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground text-xl px-2 py-0.5 rounded hover:bg-surface-raised"
          >
            ×
          </button>
        </div>

        {/* Identity tiles: + − ± ± ± + = */}
        <div className="grid grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] gap-2 mb-2">
          <TermTile label="Dollars in" cents={t.dollars_in_cents} tone="in" />
          <Op char="−" />
          <TermTile label="Dollars spent" cents={t.dollars_spent_cents} tone="out" />
          <Op char="+" />
          <TermTile label="Market Δ" cents={t.market_value_delta_cents} tone="mv" signed />
          <Op char="+" />
          <TermTile label="Real estate Δ" cents={t.real_estate_delta_cents} tone="re" signed />
        </div>
        <div className="grid grid-cols-[1fr_auto_1fr_auto_2fr] gap-2 mb-6">
          <TermTile label="Vehicle Δ" cents={t.vehicle_delta_cents} tone="veh" signed />
          <Op char="+" />
          <TermTile label="Unexplained" cents={data.unexplained_cents} tone="unex" signed />
          <Op char="=" />
          <TermTile label="Δ Net worth" cents={data.net_worth_delta_cents} tone="nw" signed />
        </div>

        {/* Unexplained summary strip */}
        <div className="bg-surface-raised border border-border rounded-lg px-5 py-3 flex justify-between items-baseline mb-6">
          <div className="text-xs text-muted-foreground font-medium">
            Unexplained residual (sum of drift sources)
          </div>
          <div className={"text-lg font-extrabold text-numeric " + toneTxt[tone]}>
            {fmtSignedCents(data.unexplained_cents)}
            {data.net_worth_delta_cents !== 0 && (
              <> {" "}
                <span className="text-xs font-semibold opacity-70">
                  ({(Math.abs(data.unexplained_cents) / Math.abs(data.net_worth_delta_cents) * 100).toFixed(1)}% of Δ NW)
                </span>
              </>
            )}
          </div>
        </div>

        {/* Drift source list */}
        {data.drift_sources.length === 0 ? (
          <div className="text-sm text-muted-foreground italic py-6 text-center">
            No drift sources detected — the full net-worth change is covered by the identity.
          </div>
        ) : (
          <>
            <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-3">
              Drift sources (sorted by magnitude)
            </div>
            <div className="flex flex-col gap-2">
              {data.drift_sources.map((d) => (
                <DriftRow key={d.id} d={d} onFix={() => fixClick(d)} />
              ))}
            </div>
          </>
        )}

        <div className="mt-6 pt-4 border-t border-border text-[11px] text-muted-foreground italic">
          Identity · Δ NetWorth = (Dollars in) − (Dollars spent) ± (Market Δ) ± (RE Δ) ± (Vehicle Δ) + unexplained.
          Targets: ≥95% green · 85–95% yellow · &lt;85% red.
        </div>
      </div>
    </div>
  );
}

function Op({ char }: { char: string }) {
  return (
    <div className="self-center text-center text-lg font-semibold text-muted-foreground">
      {char}
    </div>
  );
}

function TermTile({
  label, cents, tone, signed,
}: {
  label: string;
  cents: number;
  tone: "in" | "out" | "mv" | "re" | "veh" | "unex" | "nw";
  signed?: boolean;
}) {
  const toneClass: Record<string, string> = {
    in:   "bg-[var(--chart-c2)]/10 text-[var(--chart-c2)]",
    out:  "bg-loss-subtle text-loss",
    mv:   "bg-[var(--chart-c2)]/10 text-[var(--chart-c2)]",
    re:   "bg-gain-subtle text-gain",
    veh:  "bg-[var(--color-warning)]/10 text-[var(--color-warning)]",
    unex: "bg-surface-raised text-foreground",
    nw:   "bg-muted text-foreground",
  };
  const val = signed ? fmtSignedCents(cents) : fmt(cents / 100);
  return (
    <div className={`rounded-lg px-3 py-3 text-center ${toneClass[tone]}`}>
      <div className="text-[10px] font-bold uppercase tracking-wider opacity-80 mb-1">
        {label}
      </div>
      <div className="text-base font-extrabold text-numeric leading-none">
        {val}
      </div>
    </div>
  );
}

function DriftRow({ d, onFix }: { d: DriftSource; onFix: () => void }) {
  const barColor =
    d.severity === "warning" ? "bg-[var(--color-warning)]" : "bg-[var(--chart-c2)]";
  return (
    <div className="grid grid-cols-[4px_1fr_auto_auto] items-center gap-4 px-3 py-2.5 bg-card border border-border rounded-lg">
      <div className={`self-stretch rounded-full ${barColor}`} />
      <div className="min-w-0">
        <div className="text-sm font-semibold truncate">{d.label}</div>
      </div>
      <div className="text-xs font-bold text-numeric text-muted-foreground shrink-0">
        {d.magnitude_cents > 0 ? `~${fmt(d.magnitude_cents / 100)}` : "—"}
      </div>
      {d.fix_action ? (
        <button
          onClick={onFix}
          className="px-3 py-1.5 text-[11.5px] font-semibold rounded-md border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-colors shrink-0"
        >
          {d.fix_action === "recategorize" ? "Categorize" : null}
          {d.fix_action === "refresh_portfolio" ? "Refresh" : null}
          {d.fix_action === "upload_ras" ? "Upload RAS" : null}
          {d.fix_action === "update_valuation" ? "Update value" : null}
          {d.fix_action === "update_vehicle_value" ? "Update value" : null}
          {" →"}
        </button>
      ) : (
        <span className="px-3 py-1.5 text-[11.5px] font-medium text-muted-foreground border border-dashed border-border rounded-md shrink-0">
          Informational
        </span>
      )}
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
  const { referenceDate, ready: runtimeReady } = useRuntimeContext();

  const [timeframeRaw, setTimeframe] = useSessionState("reports:timeframe", TF_DEFAULT);
  // Migrate legacy values forward (e.g. a user with a saved "Last 30 Days"
  // selection from before PR3 silently lands on "Current Month").
  const timeframe = migrateTimeframe(timeframeRaw);
  const [accountIdFilter, setAccountIdFilter] = useSessionState<string>("reports:accountIdFilter", "");
  const [categoryFilter, setCategoryFilter] = useSessionState<string>("reports:categoryFilter", "");
  const [merchantFilter, setMerchantFilter] = useSessionState<string>("reports:merchantFilter", "");
  const [tagFilter, setTagFilter] = useSessionState<string>("reports:tagFilter", "");

  // Response shape for /api/reports/flow.
  //
  // Deliberately forgiving: top-level keys typed so backend renames
  // trip the compiler (the audit P0), but array elements and deep
  // payloads like payroll_decomposition stay ``any`` to avoid
  // over-coupling the frontend to every nested field. The value this
  // buys us is catching "income_categorys" / "total_incomes" typos
  // and "bucket_totals" → "totals_by_bucket" renames before they
  // silently break the Sankey chart.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  type FlowResponse = {
    income_categories?: Array<{ category: string; total: number }>;
    spending_categories?: Array<{ category: string; total: number }>;
    total_income?: number;
    total_spending?: number;
    bucket_totals?: {
      CONSUMED?: number;
      STORED_LIQUID?: number;
      STORED_ILLIQUID?: number;
    };
    bypass_flows?: Array<{
      source_id: string;
      display_label: string;
      amount_cents: number;
    }>;
    // Remaining payloads: top-level presence is typed, per-element
    // shapes stay permissive until the individual sections get their
    // own typed interfaces in follow-up work.
    mortgage_splits?: any[];
    transfer_flows?: any[];
    reinvestment_flows?: any[];
    payroll_decomposition?: any;
    [key: string]: any;
  };

  const [flowData, setFlowData] = useState<FlowResponse | null>(null);
  const [transactions, setTransactions] = useState<any[]>([]);

  /* Phase 14 Phase D — accountability scorecard state. */
  const [accountability, setAccountability] = useState<Accountability | null>(null);
  const [accountabilityModalOpen, setAccountabilityModalOpen] = useState(false);
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
  const window_ = useMemo(
    () => resolveTimeframe(timeframe, referenceDate),
    [referenceDate, timeframe],
  );

  // Fetch flow data
  const fetchFlow = useCallback(() => {
    if (!runtimeReady) return;
    const params = new URLSearchParams();
    if (window_.start_date) params.set("start_date", window_.start_date);
    params.set("end_date", window_.end_date);
    if (accountIdFilter) params.set("account_id", accountIdFilter);
    if (ownerParam) params.set("owner_id", ownerParam);
    fetch(`http://127.0.0.1:8000/api/reports/flow?${params}`)
      .then(r => r.json())
      .then(setFlowData)
      .catch(console.error);
  }, [runtimeReady, window_, accountIdFilter, ownerParam]);
  useEffect(() => { fetchFlow(); }, [fetchFlow]);

  // Phase 14 Phase D — fetch the accountability scorecard in parallel
  // with the Sankey. The identity relies on the same window as the flow
  // card, so the two are always consistent.
  const fetchAccountability = useCallback(() => {
    if (!runtimeReady) return;
    // Accountability identity requires an explicit start; "All Time"
    // isn't meaningful for NW-delta accounting.
    if (!window_.start_date) {
      setAccountability(null);
      return;
    }
    const params = new URLSearchParams();
    params.set("start_date", window_.start_date);
    params.set("end_date", window_.end_date);
    if (ownerParam) params.set("owner_id", ownerParam);
    fetch(`http://127.0.0.1:8000/api/reports/accountability?${params}`)
      .then(r => r.json())
      .then(setAccountability)
      .catch(console.error);
  }, [runtimeReady, window_, ownerParam]);
  useEffect(() => { fetchAccountability(); }, [fetchAccountability]);

  // Fetch transactions for the same window — keeps the side panel
  // and Sankey in lockstep so totals reconcile.
  const fetchTransactions = useCallback(() => {
    if (!runtimeReady) return;
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
  }, [runtimeReady, window_, accountIdFilter, ownerParam]);
  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

  /* ── Build Sankey node data ─────────────────────────────────────────────── */
  const sankeyData = useMemo(() => {
    if (!flowData) return null;
    const incCats = flowData.income_categories || [];
    const spdCats = flowData.spending_categories || [];
    const totalIncome = flowData.total_income || 0;
    const totalSpending = flowData.total_spending || 0;

    // Phase 14 Phase B payload.
    const bt = flowData.bucket_totals || { CONSUMED: 0, STORED_LIQUID: 0, STORED_ILLIQUID: 0 };
    const bucketTotals: BucketTotals = {
      CONSUMED:        Number(bt.CONSUMED || 0),
      STORED_LIQUID:   Number(bt.STORED_LIQUID || 0),
      STORED_ILLIQUID: Number(bt.STORED_ILLIQUID || 0),
    };
    const totalInflow =
      bucketTotals.CONSUMED + bucketTotals.STORED_LIQUID + bucketTotals.STORED_ILLIQUID;

    const incomeNodes: SankeyNodeData[] = incCats.map((c: any, i: number) => ({
      name: c.category,
      value: c.total,
      color: INCOME_COLORS[i % INCOME_COLORS.length],
      side: "income" as const,
      pctLabel: pct(c.total, totalInflow || totalIncome),
    }));

    const spendNodes: SankeyNodeData[] = spdCats.map((c: any, i: number) => ({
      name: c.category,
      value: c.total,
      color: SPEND_COLORS[i % SPEND_COLORS.length],
      side: "spending" as const,
      pctLabel: pct(c.total, totalInflow || totalIncome),
    }));

    // Bypass synthetic sources — one visual bar per registry entry with a
    // nonzero amount in the window.
    const bypassFlowsRaw = flowData.bypass_flows || [];
    const bypassSources: BypassSource[] = bypassFlowsRaw
      .filter(b => b.amount_cents > 0)
      .map(b => ({
        id: b.source_id,
        label: b.display_label,
        value: b.amount_cents / 100,
      }));

    // Mortgage decomposition aggregated across all splits in the window.
    const mortgageSplits = flowData.mortgage_splits || [];
    let mortgage: MortgageSplit | null = null;
    if (mortgageSplits.length > 0) {
      let pC = 0, iC = 0, eC = 0, tC = 0, unsplit = 0;
      for (const m of mortgageSplits) {
        pC += m.principal_cents || 0;
        iC += m.interest_cents || 0;
        eC += m.escrow_cents || 0;
        tC += (m.principal_cents || 0) + (m.interest_cents || 0) + (m.escrow_cents || 0);
        if (m.method === "unsplit") unsplit += 1;
      }
      mortgage = {
        totalCents: tC,
        principalCents: pC,
        interestCents: iC,
        escrowCents: eC,
        splitCount: mortgageSplits.length,
        unsplitCount: unsplit,
      };
    }

    // Illiquid transfer flows aggregated by peer account type.
    const transferFlows = flowData.transfer_flows || [];
    const illiquidByPeer = new Map<string, number>();
    for (const t of transferFlows) {
      if (t.bucket === "STORED_ILLIQUID") {
        const peer = t.peer_account_type || "unknown";
        illiquidByPeer.set(peer, (illiquidByPeer.get(peer) || 0) + (t.amount_cents || 0));
      }
    }
    const illiquidTransferAggs: IlliquidTransferAgg[] = Array.from(illiquidByPeer.entries())
      .map(([peerType, cents]) => ({ peerType, value: cents / 100 }))
      .sort((a, b) => b.value - a.value);

    // Phase 14 Phase C — reinvestment flows aggregated by ticker. Each
    // entry in `reinvestment_flows` is one matched dividend-txn / ledger-
    // row pair; we collapse to one bar per ticker so the mid column stays
    // readable even if a ticker pays quarterly reinvested dividends.
    const reinvestFlows = flowData.reinvestment_flows || [];
    const reinvestByTicker = new Map<string, { cents: number; count: number }>();
    for (const r of reinvestFlows) {
      const key = (r.ticker || "?").toUpperCase();
      const prev = reinvestByTicker.get(key) || { cents: 0, count: 0 };
      reinvestByTicker.set(key, {
        cents: prev.cents + (r.amount_cents || 0),
        count: prev.count + 1,
      });
    }
    const reinvestmentAggs: ReinvestmentAgg[] = Array.from(reinvestByTicker.entries())
      .map(([ticker, v]) => ({ ticker, value: v.cents / 100, count: v.count }))
      .sort((a, b) => b.value - a.value);

    // Phase 14 Phase B follow-up — aggregate payroll withholdings by
    // kind across the window. Each kind becomes a distinct ribbon
    // peeling off the primary paycheck bar straight into CONSUMED.
    const payrollRows = flowData.payroll_decomposition?.payroll_rows || [];
    const withhByKind = new Map<string, number>();
    for (const r of payrollRows) {
      for (const w of (r.withholdings || []) as any[]) {
        if (w.bucket === "CONSUMED") {
          withhByKind.set(w.kind, (withhByKind.get(w.kind) || 0) + (w.cents || 0));
        }
      }
    }
    const withholdings: WithholdingAgg[] = Array.from(withhByKind.entries())
      .map(([kind, cents]) => ({
        kind,
        label: WITHHOLDING_LABEL[kind] ?? kind,
        color: WITHHOLDING_COLOR[kind] ?? "var(--color-neutral)",
        value: cents / 100,
      }))
      .filter(w => w.value > 0)
      .sort((a, b) => b.value - a.value);

    return {
      incomeNodes,
      spendNodes,
      totalIncome,
      totalSpending,
      bucketTotals,
      bypassSources,
      mortgage,
      illiquidTransferAggs,
      reinvestmentAggs,
      withholdings,
    };
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
  const hasActiveFilters = accountIdFilter || categoryFilter || merchantFilter || tagFilter || timeframe !== TF_DEFAULT;

  return (
    <PageShell>

      {/* ── Sticky Toolbar — page title lives in global Header ─────────── */}
      <div className="px-12 py-3 flex items-center gap-3 flex-wrap border-b border-border sticky top-0 bg-background z-10">
        <Select value={timeframe} onValueChange={(val: string | null) => { if (val) { setTimeframe(val); setActiveFilter(null); } }}>
          <SelectTrigger className="w-[160px] h-9 text-xs font-semibold">
            <SelectValue placeholder="Timeframe" />
          </SelectTrigger>
          <SelectContent>
            {TF_OPTIONS.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
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
          { label: "Total Income",     value: flowData?.total_income,   color: "text-gain", testId: "reports-summary-total-income" },
          { label: "Total Expenses",   value: flowData?.total_spending, color: "text-loss", testId: "reports-summary-total-expenses" },
          { label: "Total Net Income", value: flowData?.net,            color: (flowData?.net ?? 0) >= 0 ? "text-gain" : "text-loss", signed: true, testId: "reports-summary-net-income" },
          { label: "Savings Rate",     value: flowData?.savings_rate,   isPct: true, color: "text-[var(--chart-c2)]", testId: "reports-summary-savings-rate" },
        ].map((card, i) => (
          <div key={i} className="card-l1 px-5 py-4 text-center">
            <p className={`text-xl lg:text-2xl font-extrabold text-numeric ${card.color} mb-0.5`} data-testid={card.testId}>
              {card.isPct
                ? `${(card.value ?? 0).toFixed(1)}%`
                : card.signed && (card.value ?? 0) >= 0
                ? `+${fmt(card.value ?? 0)}`
                : fmt(card.value ?? 0)
              }
            </p>
            <p className="text-label">{card.label}</p>
          </div>
        ))}
      </div>

      {/* ── Phase 14 Phase D — Accountability Scorecard ─────────────────────── */}
      <div className="px-12 pb-3">
        <AccountabilityScorecard
          data={accountability}
          timeLabel={timeLabel}
          onOpen={() => setAccountabilityModalOpen(true)}
        />
      </div>

      {/* ── Sankey Chart — DOMINATES THE PAGE ──────────────────────────────── */}
      <div className="px-12 pb-4" ref={chartContainerRef}>
        <div className="card-l1 overflow-visible flex flex-col">
          {/* Chart header */}
          <div className="px-6 py-3 flex items-center justify-between border-b border-border">
            <div>
              <span className="text-label">CASH FLOW</span>
              <span className="text-[11px] text-muted-foreground ml-3">{timeLabel}</span>
            </div>
            <select
              className="bg-surface-raised border border-border rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
              value={timeframe}
              onChange={e => { setTimeframe(e.target.value); setActiveFilter(null); }}
            >
              {TF_OPTIONS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* Chart body — overflow visible so SVG labels can bleed outside */}
          <div className="py-4 overflow-visible">
            {sankeyData ? (
              sankeyData.totalIncome === 0 && sankeyData.totalSpending === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
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
                    bucketTotals={sankeyData.bucketTotals}
                    bypassSources={sankeyData.bypassSources}
                    mortgage={sankeyData.mortgage}
                    illiquidTransferAggs={sankeyData.illiquidTransferAggs}
                    reinvestmentAggs={sankeyData.reinvestmentAggs}
                    withholdings={sankeyData.withholdings}
                    activeNode={activeFilter?.name ?? null}
                    onNodeClick={onNodeClick}
                    containerWidth={containerWidth - 80}
                  />
                </div>
              )
            ) : (
              <div className="flex flex-col items-center gap-2 text-muted-foreground">
                <span className="material-symbols-outlined text-4xl animate-spin" style={{ animationDuration: "2s" }}>hourglass_top</span>
                <p className="text-sm font-semibold">Loading flow data...</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Phase 14 Phase A debug panel: payroll decomposition ──────────── */}
      {flowData && flowData.payroll_decomposition?.payroll_rows?.length > 0 && (
        <div className="px-12 pb-4">
          <PayrollDecompositionDebugPanel
            decomposition={flowData.payroll_decomposition}
          />
        </div>
      )}

      {/* ── Phase 14 Phase B panel: three terminal buckets ───────────────── */}
      {flowData?.bucket_totals && (
        <div className="px-12 pb-4">
          {/* FlowResponse is a superset of TerminalBucketsPayload — we've
              guarded on bucket_totals above so the panel's required
              fields are present at runtime. Cast narrows the type. */}
          <TerminalBucketsPanel data={flowData as unknown as TerminalBucketsPayload} />
        </div>
      )}

      {/* ── Filtered Transactions + Summary ────────────────────────────────── */}
      <div ref={txListRef} className="px-12 pb-12 flex flex-col lg:flex-row gap-4">
        {/* Transaction List */}
        <div className="flex-1 card-l1 flex flex-col overflow-hidden">
          {/* Header */}
          <div className="px-5 py-3 border-b border-border flex items-center justify-between">
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
            <span className="text-xs text-muted-foreground font-semibold shrink-0">
              {filteredTx.length} transaction{filteredTx.length !== 1 ? "s" : ""}
            </span>
          </div>

          {/* List */}
          <div className="flex-1 overflow-y-auto max-h-[400px] custom-scrollbar divide-y divide-border">
            {filteredTx.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <span className="material-symbols-outlined text-3xl mb-2">filter_list_off</span>
                <p className="font-semibold text-sm" data-testid="reports-transactions-empty">No matching transactions</p>
                <p className="text-xs">Try selecting a different category or timeframe</p>
              </div>
            ) : (
              filteredTx.map((tx, index) => (
                <div key={tx.id} className="px-5 py-2.5 flex items-center gap-3 hover:bg-surface-raised/60 transition-colors group">
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
                    <p className="text-[10px] text-muted-foreground">{tx.posting_date}</p>
                  </div>

                  {/* Category badge */}
                  <div className="relative">
                    {editingTxId === tx.id ? (
                      <select
                        autoFocus
                        className="text-xs font-bold bg-card border border-primary/30 rounded-lg px-2 py-1 outline-none shadow-lg z-20"
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
                  <span className="text-[10px] text-muted-foreground font-semibold hidden xl:block w-28 truncate text-right">
                    {ACCOUNT_NAMES[tx.account_id] || tx.account_id}
                  </span>

                  {/* Amount */}
                  <span className={`text-sm font-bold w-24 text-right shrink-0 text-numeric ${
                    (tx.signed_amount ?? tx.amount) < 0 ? "text-loss" : "text-gain"
                  }`} data-testid={`reports-transaction-amount-${index + 1}`}>
                    {(tx.signed_amount ?? tx.amount) >= 0 ? "+" : ""}{formatCurrency(tx.signed_amount ?? tx.amount)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Summary Panel */}
        <div className="w-full lg:w-[260px] shrink-0">
          <Card className="p-5 sticky top-24">
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-sm">Summary</h3>
              <span className="material-symbols-outlined text-sm text-muted-foreground">tune</span>
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
                    <span className="text-[11px] text-muted-foreground">{item.label}</span>
                    <span className={`text-[11px] font-bold ${item.color || "text-foreground"}`}>{item.value}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-6 text-muted-foreground">
                <span className="material-symbols-outlined text-xl mb-2">insights</span>
                <p className="text-xs text-center">Select a category from the chart to see a summary</p>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Phase 14 Phase D — drilldown modal (portaled inline). */}
      {accountabilityModalOpen && accountability && (
        <AccountabilityModal
          data={accountability}
          onClose={() => setAccountabilityModalOpen(false)}
        />
      )}
    </PageShell>
  );
}
