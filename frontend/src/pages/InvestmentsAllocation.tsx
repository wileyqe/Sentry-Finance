/**
 * InvestmentsAllocation — Allocation tab for the Investments page.
 *
 * Sections:
 *   1. Asset allocation donut (large) with dollar-value legend
 *   2. Portfolio treemap / Sunburst toggle + Sector exposure (side by side)
 *   3. Geographic + Market Cap distribution (side by side)
 *
 * Supports X-Ray mode (look-through fund decomposition) via ?lookthrough=true.
 * Treemap supports drill-down by account.
 */

import { useMemo, useState } from "react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  Treemap,
  BarChart, Bar, XAxis, YAxis, Legend,
} from "recharts";
import { formatCurrency } from "@/lib/formatCurrency";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { useAccounts } from "@/lib/accounts";
import SyntheticBadge from "@/components/ui/SyntheticBadge";
import {
  rechartsTooltipStyle,
  rechartsTooltipLabelStyle,
  rechartsTooltipItemStyle,
} from "@/lib/chartStyle";

/* ── Types ────────────────────────────────────────────────────────────────── */

type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

interface InvestmentsTabProps {
  timeframe: Timeframe;
  accountFilter: string;
  xrayMode?: boolean;
}

/* ── Sector color palette ─────────────────────────────────────────────────── */

const CHART_COLORS = [
  "var(--chart-c1)", "var(--chart-c2)", "var(--chart-c3)", "var(--chart-c4)",
  "var(--chart-c5)", "var(--chart-c6)", "var(--chart-c7)", "var(--chart-c8)",
];

function testIdPart(value: unknown): string {
  return String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "unknown";
}

/* ── Treemap Custom Content ───────────────────────────────────────────────── */

function TreemapCell(props: any) {
  const { x, y, width, height, name, pct, fill } = props;
  if (width < 4 || height < 4) return null;

  const showLabel = width > 60 && height > 40;
  const showPct = width > 50 && height > 55;

  return (
    <g>
      <rect
        x={x} y={y} width={width} height={height}
        rx={6} ry={6}
        fill={fill}
        fillOpacity={0.85}
        stroke="var(--background)"
        strokeWidth={3}
      />
      {showLabel && (
        <text
          x={x + width / 2} y={y + height / 2 - (showPct ? 6 : 0)}
          textAnchor="middle" dominantBaseline="central"
          fill="white" fontWeight={700} fontSize={width > 120 ? 18 : 14}
        >
          {name}
        </text>
      )}
      {showPct && pct != null && (
        <text
          x={x + width / 2} y={y + height / 2 + 14}
          textAnchor="middle" dominantBaseline="central"
          fill="rgba(255,255,255,0.7)" fontWeight={600} fontSize={12}
        >
          {Number(pct).toFixed(1)}%
        </text>
      )}
    </g>
  );
}

/* ── Horizontal Bar Row ───────────────────────────────────────────────────── */

function ExposureBar({
  name,
  pct,
  amount,
  color,
  maxPct,
  testIdPrefix,
}: {
  name: string;
  pct: number;
  amount?: number;
  color: string;
  maxPct: number;
  testIdPrefix?: string;
}) {
  const barWidth = maxPct > 0 ? (pct / maxPct) * 100 : 0;
  const slug = testIdPart(name);

  return (
    <div className="flex items-center gap-3 py-1.5 group">
      <span className="text-xs text-muted-foreground w-[120px] shrink-0 truncate group-hover:text-foreground transition-colors">
        {name}
      </span>
      <div className="flex-1 h-5 bg-surface-raised rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${barWidth}%`, backgroundColor: color, opacity: 0.8 }}
        />
      </div>
      <span
        className="text-xs font-semibold text-foreground text-numeric w-[44px] text-right"
        data-testid={testIdPrefix ? `${testIdPrefix}-pct-${slug}` : undefined}
      >
        {pct.toFixed(1)}%
      </span>
      {amount !== undefined && (
        <span
          className="text-xs text-muted-foreground text-numeric w-[72px] text-right"
          data-testid={testIdPrefix ? `${testIdPrefix}-amount-${slug}` : undefined}
        >
          {formatCurrency(amount)}
        </span>
      )}
    </div>
  );
}

/* ── Stacked Bar Custom Tooltip ──────────────────────────────────────────── */

function StackedBarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card border border-border rounded-lg px-3 py-2 text-foreground text-xs shadow-xl">
      <p className="font-semibold mb-1">{label}</p>
      {payload
        .filter((p: any) => p.value > 0)
        .sort((a: any, b: any) => b.value - a.value)
        .map((p: any, i: number) => (
          <div key={i} className="flex items-center gap-2 py-0.5">
            <div className="size-2.5 rounded-full" style={{ backgroundColor: p.fill || p.color }} />
            <span className="text-muted-foreground">{p.dataKey}</span>
            <span className="ml-auto font-semibold">{p.value.toFixed(1)}%</span>
          </div>
        ))}
    </div>
  );
}

/* ── Component ────────────────────────────────────────────────────────────── */

export default function InvestmentsAllocation({ timeframe: _tf, accountFilter, xrayMode = false }: InvestmentsTabProps) {
  const ltParam = xrayMode ? "&lookthrough=true" : "";
  const allocUrl = accountFilter === "all"
    ? `/api/investments/allocation?_=1${ltParam}`
    : `/api/investments/allocation?account_id=${encodeURIComponent(accountFilter)}${ltParam}`;
  const { data: allocData, loading } = useOwnerApi<any>(allocUrl);
  const { data: taxData } = useOwnerApi<{ by_treatment: { name: string; amount: number; pct: number }[]; total: number }>(
    "/api/investments/tax-summary"
  );

  const [chartView, setChartView] = useState<"treemap" | "sunburst">("treemap");
  const [treemapDrilldown, setTreemapDrilldown] = useState<string | null>(null);

  const totalValue = allocData?.total_value || 0;
  const bySector = allocData?.by_sector || [];
  const byAssetClass = allocData?.by_asset_class || [];
  const byGeography = allocData?.by_geography || [];
  const byMarketCap = allocData?.by_market_cap || [];
  const treemapRaw = allocData?.treemap || [];
  const treemapLtRaw = allocData?.treemap_lookthrough || [];
  const sunburstRaw = allocData?.sunburst || [];
  const stackedBarsRaw = allocData?.stacked_bars || [];

  // Build display data with colors
  const allocation = useMemo(() =>
    byAssetClass.map((c: any, i: number) => ({
      name: c.name,
      value: c.pct,
      amount: c.amount,
      color: CHART_COLORS[i % CHART_COLORS.length],
    })),
    [byAssetClass]
  );

  // Tax treatment donut data (for X-Ray mode)
  const TAX_COLORS: Record<string, string> = {
    "Tax-Deferred": "var(--chart-c6)",
    "Tax-Free": "var(--chart-c3)",
    "Taxable": "var(--chart-c8)",
  };
  const taxAllocation = useMemo(() => {
    if (!taxData?.by_treatment) return [];
    return taxData.by_treatment.map((t) => ({
      name: t.name,
      value: t.pct,
      amount: t.amount,
      color: TAX_COLORS[t.name] || CHART_COLORS[0],
    }));
  }, [taxData]);

  // Standard treemap data (by ticker, grouped by account for drill-down)
  const treemapData = useMemo(() => {
    const items = treemapRaw.map((t: any, i: number) => ({
      name: t.ticker,
      ticker: t.ticker,
      size: t.size,
      pct: t.pct,
      assetClass: t.asset_class,
      account: t.account_name,
      fill: CHART_COLORS[i % CHART_COLORS.length],
    }));
    return items;
  }, [treemapRaw]);

  // Look-through treemap data (by asset class)
  const treemapLtData = useMemo(() =>
    treemapLtRaw.map((t: any, i: number) => ({
      name: t.asset_class,
      size: t.size,
      pct: t.pct,
      sources: t.sources,
      fill: CHART_COLORS[i % CHART_COLORS.length],
    })),
    [treemapLtRaw]
  );

  // Drill-down: group holdings by account for account-level treemap
  const accountTreemapData = useMemo(() => {
    if (accountFilter !== "all") return null; // No drill-down for single account
    const acctMap = new Map<string, number>();
    for (const item of treemapRaw) {
      const acct = item.account_name || "Unknown";
      acctMap.set(acct, (acctMap.get(acct) || 0) + (item.size || 0));
    }
    return Array.from(acctMap.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([name, size], i) => ({
        name,
        size,
        pct: totalValue > 0 ? (size / totalValue * 100) : 0,
        fill: CHART_COLORS[i % CHART_COLORS.length],
      }));
  }, [treemapRaw, accountFilter, totalValue]);

  // Filtered treemap for drill-down into a specific account
  const drilledTreemapData = useMemo(() => {
    if (!treemapDrilldown) return null;
    const items = treemapRaw
      .filter((t: any) => (t.account_name || "Unknown") === treemapDrilldown)
      .map((t: any, i: number) => ({
        name: t.ticker,
        size: t.size,
        pct: t.pct,
        assetClass: t.asset_class,
        fill: CHART_COLORS[i % CHART_COLORS.length],
      }));
    return items;
  }, [treemapRaw, treemapDrilldown]);

  // Multi-ring pie data — inner ring = accounts, outer ring = holdings/asset classes
  // Uses two flat arrays for Recharts multi-Pie rendering (proven, no crash risk)
  const { innerRing, outerRing } = useMemo(() => {
    type RingEntry = { name: string; value: number; fill: string };
    const inner: RingEntry[] = [];
    const outer: RingEntry[] = [];

    if (xrayMode && sunburstRaw.length) {
      // X-Ray: account → asset class
      sunburstRaw.forEach((acct: any, i: number) => {
        const acctTotal = (acct.children || []).reduce((s: number, c: any) => s + (c.value || 0), 0);
        inner.push({ name: acct.name, value: acctTotal, fill: CHART_COLORS[i % CHART_COLORS.length] });
        (acct.children || []).forEach((ac: any, j: number) => {
          outer.push({ name: ac.name, value: ac.value, fill: CHART_COLORS[(i * 3 + j) % CHART_COLORS.length] });
        });
      });
    } else if (treemapRaw.length) {
      // Holdings: account → ticker
      const acctGroups = new Map<string, { ticker: string; size: number }[]>();
      for (const t of treemapRaw) {
        const acct = t.account_name || "Unknown";
        if (!acctGroups.has(acct)) acctGroups.set(acct, []);
        acctGroups.get(acct)!.push({ ticker: t.ticker, size: t.size || 0 });
      }
      let i = 0;
      for (const [acctName, holdings] of acctGroups.entries()) {
        const total = holdings.reduce((s, h) => s + h.size, 0);
        inner.push({ name: acctName, value: total, fill: CHART_COLORS[i % CHART_COLORS.length] });
        holdings.sort((a, b) => b.size - a.size).forEach((h, j) => {
          outer.push({ name: h.ticker, value: h.size, fill: CHART_COLORS[(i * 4 + j) % CHART_COLORS.length] });
        });
        i++;
      }
    }
    return { innerRing: inner, outerRing: outer };
  }, [xrayMode, sunburstRaw, treemapRaw]);

  // Stacked bars: collect all unique asset classes for bar segments
  const { stackedBarData, stackedBarKeys } = useMemo(() => {
    const keys = new Set<string>();
    for (const bar of stackedBarsRaw) {
      for (const k of Object.keys(bar)) {
        if (k !== "account") keys.add(k);
      }
    }
    return { stackedBarData: stackedBarsRaw, stackedBarKeys: Array.from(keys) };
  }, [stackedBarsRaw]);

  const activeTreemapData = xrayMode
    ? treemapLtData
    : (treemapDrilldown && drilledTreemapData ? drilledTreemapData
       : (accountTreemapData && accountFilter === "all" && !treemapDrilldown ? accountTreemapData
         : treemapData));

  const maxSectorPct = Math.max(...bySector.map((s: any) => s.pct), 1);
  const maxGeoPct = Math.max(...byGeography.map((g: any) => g.pct), 1);
  const maxCapPct = Math.max(...byMarketCap.map((m: any) => m.pct), 1);

  const { accounts: globalAccounts } = useAccounts();
  const hasAnySynthetic = useMemo(
    () => globalAccounts.some((a) => !!a.is_synthetic),
    [globalAccounts],
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <span className="material-symbols-outlined animate-spin text-xl mr-2">progress_activity</span>
        Loading allocation...
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">

      {/* ── Section 1: Asset Allocation Donut (+ Tax Donut in X-Ray) ── */}
      <div className="card-l1 p-6">
        <div className="flex items-center gap-3 mb-4">
          <p className="text-label">Asset Allocation</p>
          {hasAnySynthetic && <SyntheticBadge compact />}
          {xrayMode && (
            <span className="text-[10px] font-medium text-[var(--chart-c2)] bg-[var(--chart-c2)]/10 px-2 py-0.5 rounded-full">
              X-Ray: Fund look-through active
            </span>
          )}
        </div>

        {xrayMode ? (
          /* X-Ray mode: two mirrored donut+legend pairs */
          <div className="flex flex-col lg:flex-row items-start gap-6 lg:gap-10">
            {/* Pair 1: Asset Class — donut LEFT, legend RIGHT */}
            <div className="flex-1 min-w-0 w-full flex flex-col sm:flex-row items-start gap-4">
              {/* Asset allocation donut */}
              <div className="relative w-[220px] h-[220px] shrink-0 self-center sm:self-start">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Tooltip
                      contentStyle={rechartsTooltipStyle()}
                      labelStyle={rechartsTooltipLabelStyle()}
                      itemStyle={rechartsTooltipItemStyle()}
                      formatter={(value: any, name: any) => [`${value}%`, name]}
                    />
                    <Pie
                      data={allocation}
                      cx="50%" cy="50%"
                      innerRadius={65} outerRadius={100}
                      paddingAngle={2} dataKey="value" stroke="none"
                    >
                      {allocation.map((entry: any, i: number) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                  <span
                    className="text-lg font-bold text-foreground"
                    data-testid="investments-allocation-total-value"
                  >
                    {formatCurrency(totalValue)}
                  </span>
                  <span className="text-label mt-0.5 text-[10px]">Total Value</span>
                </div>
              </div>

              {/* Asset class legend */}
              <div className="flex-1 min-w-0 w-full space-y-1">
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">By Asset Class</p>
                {allocation.map((cls: any) => (
                  <div key={cls.name} className="flex items-center gap-3 py-1.5 px-3 rounded-lg hover:bg-surface-raised/60 transition-colors">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div className="size-2.5 rounded-full shrink-0" style={{ backgroundColor: cls.color }} />
                      <span className="text-xs font-medium text-foreground truncate">{cls.name}</span>
                    </div>
                    <span
                      className="text-xs font-semibold text-numeric text-foreground tabular-nums"
                      data-testid={`investments-allocation-asset-class-amount-${testIdPart(cls.name)}`}
                    >
                      {formatCurrency(cls.amount)}
                    </span>
                    <span
                      className="text-[10px] text-muted-foreground text-numeric tabular-nums w-10 text-right"
                      data-testid={`investments-allocation-asset-class-pct-${testIdPart(cls.name)}`}
                    >
                      {cls.value}%
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Pair 2: Tax Treatment — legend LEFT, donut RIGHT (mirrored) */}
            {taxAllocation.length > 0 && (
              <div className="flex-1 min-w-0 w-full flex flex-col sm:flex-row items-start gap-4">
                {/* Tax treatment legend (inner side on desktop) */}
                <div className="flex-1 min-w-0 w-full space-y-1 order-2 sm:order-1">
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1 text-right">By Tax Treatment</p>
                  {taxAllocation.map((t) => (
                    <div key={t.name} className="flex flex-row-reverse items-center gap-3 py-1.5 px-3 rounded-lg hover:bg-surface-raised/60 transition-colors">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="size-2.5 rounded-full shrink-0" style={{ backgroundColor: t.color }} />
                        <span className="text-xs font-medium text-foreground truncate">{t.name}</span>
                      </div>
                      <span
                        className="text-xs font-semibold text-numeric text-foreground tabular-nums"
                        data-testid={`investments-allocation-tax-amount-${testIdPart(t.name)}`}
                      >
                        {formatCurrency(t.amount)}
                      </span>
                      <span
                        className="text-[10px] text-muted-foreground text-numeric tabular-nums w-10 text-right"
                        data-testid={`investments-allocation-tax-pct-${testIdPart(t.name)}`}
                      >
                        {t.value}%
                      </span>
                    </div>
                  ))}
                </div>

                {/* Tax treatment donut (outer side on desktop) */}
                <div className="relative w-[220px] h-[220px] shrink-0 self-center sm:self-start order-1 sm:order-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Tooltip
                        contentStyle={rechartsTooltipStyle()}
                        labelStyle={rechartsTooltipLabelStyle()}
                        itemStyle={rechartsTooltipItemStyle()}
                        formatter={(value: any, name: any) => [`${value}%`, name]}
                      />
                      <Pie
                        data={taxAllocation}
                        cx="50%" cy="50%"
                        innerRadius={65} outerRadius={100}
                        paddingAngle={2} dataKey="value" stroke="none"
                      >
                        {taxAllocation.map((entry, i: number) => (
                          <Cell key={i} fill={entry.color} />
                        ))}
                      </Pie>
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Tax</span>
                    <span className="text-label mt-0.5 text-[10px]">Treatment</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Holdings mode: centered donut + legend */
          <div className="flex flex-col items-center gap-6">
            <div className="relative w-[260px] h-[260px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip
                    contentStyle={rechartsTooltipStyle()}
                    labelStyle={rechartsTooltipLabelStyle()}
                    itemStyle={rechartsTooltipItemStyle()}
                    formatter={(value: any, name: any) => [`${value}%`, name]}
                  />
                  <Pie
                    data={allocation}
                    cx="50%" cy="50%"
                    innerRadius={80} outerRadius={120}
                    paddingAngle={2} dataKey="value" stroke="none"
                  >
                    {allocation.map((entry: any, i: number) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <span
                  className="text-xl font-bold text-foreground"
                  data-testid="investments-allocation-total-value"
                >
                  {formatCurrency(totalValue)}
                </span>
                <span className="text-label mt-0.5">Total Value</span>
              </div>
            </div>

            <div className="w-full max-w-lg space-y-2">
              {allocation.map((cls: any) => (
                <div key={cls.name} className="flex items-center justify-between py-2.5 px-4 rounded-lg hover:bg-surface-raised/60 transition-colors">
                  <div className="flex items-center gap-3">
                    <div className="size-3 rounded-full" style={{ backgroundColor: cls.color }} />
                    <span className="text-sm font-medium text-foreground">{cls.name}</span>
                  </div>
                  <div className="flex items-center gap-5">
                    <span
                      className="text-sm font-semibold text-numeric text-foreground"
                      data-testid={`investments-allocation-asset-class-amount-${testIdPart(cls.name)}`}
                    >
                      {formatCurrency(cls.amount)}
                    </span>
                    <span
                      className="text-xs text-muted-foreground text-numeric w-12 text-right"
                      data-testid={`investments-allocation-asset-class-pct-${testIdPart(cls.name)}`}
                    >
                      {cls.value}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Section 2: Portfolio Composition + Sector Exposure ────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Portfolio Treemap / Sunburst */}
        <div className="card-l1 flex flex-col">
          <div className="px-6 pt-5 pb-3 flex items-center justify-between">
            <div>
              <p className="text-label">Portfolio Composition</p>
              {treemapDrilldown && !xrayMode ? (
                <button
                  onClick={() => setTreemapDrilldown(null)}
                  className="text-xs text-primary hover:underline mt-0.5 flex items-center gap-1"
                >
                  <span className="material-symbols-outlined text-[14px]">arrow_back</span>
                  All Accounts
                </button>
              ) : (
                <p className="text-xs text-muted-foreground mt-0.5">
                  {xrayMode ? "Asset class exposure across all holdings" : "Click an account to drill down"}
                </p>
              )}
            </div>

            {/* View toggle: Treemap / Sunburst */}
            <div className="flex items-center gap-0.5 bg-surface-raised rounded-full p-0.5">
              <button
                onClick={() => setChartView("treemap")}
                className={`px-2.5 py-1 rounded-full text-[10px] font-semibold transition-all duration-150 ${
                  chartView === "treemap"
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Treemap
              </button>
              <button
                onClick={() => setChartView("sunburst")}
                className={`px-2.5 py-1 rounded-full text-[10px] font-semibold transition-all duration-150 ${
                  chartView === "sunburst"
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Sunburst
              </button>
            </div>
          </div>
          <div className="px-4 pb-4 flex-1">
            {chartView === "treemap" ? (
              activeTreemapData && activeTreemapData.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <Treemap
                    data={activeTreemapData}
                    dataKey="size"
                    aspectRatio={3 / 2}
                    content={<TreemapCell />}
                    onClick={(node: any) => {
                      if (!xrayMode && !treemapDrilldown && accountFilter === "all" && accountTreemapData) {
                        setTreemapDrilldown(node?.name || null);
                      }
                    }}
                  >
                    <Tooltip
                      contentStyle={rechartsTooltipStyle()}
                      labelStyle={rechartsTooltipLabelStyle()}
                      itemStyle={rechartsTooltipItemStyle()}
                      formatter={(_value: any, name: any, props: any) => {
                        const item = props?.payload;
                        const pctStr = item?.pct != null ? ` (${Number(item.pct).toFixed(1)}%)` : "";
                        return [
                          `${formatCurrency(item?.size)}${pctStr}`,
                          item?.assetClass || item?.asset_class || name || "",
                        ];
                      }}
                    />
                  </Treemap>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-[280px] text-muted-foreground text-sm">
                  <span data-testid="investments-allocation-empty">No allocation data available</span>
                </div>
              )
            ) : (
              /* Sunburst view — multi-ring PieChart (inner=accounts, outer=holdings) */
              innerRing.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Tooltip
                      contentStyle={rechartsTooltipStyle()}
                      labelStyle={rechartsTooltipLabelStyle()}
                      itemStyle={rechartsTooltipItemStyle()}
                      formatter={(value: any, name: any) => [formatCurrency(value), name]}
                    />
                    {/* Inner ring: Accounts */}
                    <Pie
                      data={innerRing}
                      cx="50%" cy="50%"
                      innerRadius={40} outerRadius={75}
                      paddingAngle={2} dataKey="value" stroke="none"
                    >
                      {innerRing.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                    {/* Outer ring: Holdings / Asset Classes */}
                    <Pie
                      data={outerRing}
                      cx="50%" cy="50%"
                      innerRadius={80} outerRadius={130}
                      paddingAngle={1} dataKey="value" stroke="none"
                    >
                      {outerRing.map((entry, i) => (
                        <Cell key={i} fill={entry.fill} />
                      ))}
                    </Pie>
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center h-[280px] text-muted-foreground text-sm">
                  No data available
                </div>
              )
            )}
          </div>
        </div>

        {/* Sector Exposure / Stacked Bars in X-Ray */}
        <div className="card-l1 p-6 flex flex-col">
          {xrayMode && stackedBarData.length > 0 ? (
            <>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-label">Account Strategy Comparison</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    100% stacked — compare allocation mix regardless of account size
                  </p>
                </div>
              </div>
              <div className="flex-1">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart
                    data={stackedBarData}
                    layout="vertical"
                    margin={{ top: 0, right: 20, bottom: 0, left: 10 }}
                  >
                    <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `${v}%`}
                      tick={{ fontSize: 10, fill: "var(--muted-foreground)" }}
                    />
                    <YAxis type="category" dataKey="account" width={80}
                      tick={{ fontSize: 11, fill: "var(--foreground)" }}
                    />
                    <Tooltip content={<StackedBarTooltip />} />
                    <Legend
                      wrapperStyle={{ fontSize: 10 }}
                      iconType="circle"
                      iconSize={8}
                    />
                    {stackedBarKeys.map((key, i) => (
                      <Bar
                        key={key}
                        dataKey={key}
                        stackId="a"
                        fill={CHART_COLORS[i % CHART_COLORS.length]}
                        radius={i === 0 ? [4, 0, 0, 4] : i === stackedBarKeys.length - 1 ? [0, 4, 4, 0] : [0, 0, 0, 0]}
                      />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <p className="text-label">Sector Exposure</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Breakdown across all holdings
                  </p>
                </div>
                <span className="text-[10px] font-medium text-muted-foreground bg-surface-raised px-2 py-0.5 rounded-full">
                  {bySector.length} sectors
                </span>
              </div>
              <div className="space-y-0.5 flex-1">
                {bySector.map((sector: any, i: number) => (
                  <ExposureBar
                    key={sector.name}
                    name={sector.name}
                    pct={sector.pct}
                    amount={sector.amount}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    maxPct={maxSectorPct}
                    testIdPrefix="investments-allocation-sector"
                  />
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Section 3: Geographic + Market Cap (side by side) ─────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Geographic */}
        <div className="card-l1 p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="material-symbols-outlined text-[18px] text-muted-foreground">public</span>
            <p className="text-label">Geographic Breakdown</p>
          </div>
          <div className="space-y-1">
            {byGeography.map((geo: any, i: number) => (
              <ExposureBar
                key={geo.name}
                name={geo.name}
                pct={geo.pct}
                amount={geo.amount}
                color={CHART_COLORS[i]}
                maxPct={maxGeoPct}
                testIdPrefix="investments-allocation-geography"
              />
            ))}
          </div>
        </div>

        {/* Market Cap (Holdings mode) / Sector Exposure (X-Ray mode) */}
        <div className="card-l1 p-6">
          {xrayMode ? (
            <>
              <div className="flex items-center gap-2 mb-4">
                <span className="material-symbols-outlined text-[18px] text-muted-foreground">donut_large</span>
                <p className="text-label">Sector Exposure</p>
                <span className="text-[10px] font-medium text-[var(--chart-c2)] bg-[var(--chart-c2)]/10 px-2 py-0.5 rounded-full">
                  Look-through
                </span>
              </div>
              <div className="space-y-0.5">
                {bySector.map((sector: any, i: number) => (
                  <ExposureBar
                    key={sector.name}
                    name={sector.name}
                    pct={sector.pct}
                    amount={sector.amount}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    maxPct={maxSectorPct}
                    testIdPrefix="investments-allocation-sector"
                  />
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 mb-4">
                <span className="material-symbols-outlined text-[18px] text-muted-foreground">bar_chart</span>
                <p className="text-label">Market Cap Distribution</p>
              </div>
              <div className="space-y-1">
                {byMarketCap.map((cap: any, i: number) => (
                  <ExposureBar
                    key={cap.name}
                    name={cap.name}
                    pct={cap.pct}
                  amount={cap.amount}
                  color={CHART_COLORS[i]}
                  maxPct={maxCapPct}
                  testIdPrefix="investments-allocation-market-cap"
                />
              ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
