/**
 * InvestmentsAllocation — Allocation tab for the Investments page.
 *
 * Four sections:
 *   1. Asset allocation donut (large) with dollar-value legend
 *   2. Portfolio treemap + Sector exposure (side by side)
 *   3. Geographic + Market Cap distribution (side by side)
 *
 * Wired to /api/investments/allocation.
 */

import { useMemo } from "react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  Treemap,
} from "recharts";
import { formatCurrency } from "@/lib/formatCurrency";
import { useOwnerApi } from "@/lib/useOwnerApi";

/* ── Types ────────────────────────────────────────────────────────────────── */

type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

interface InvestmentsTabProps {
  timeframe: Timeframe;
  accountFilter: string;
}

/* ── Sector color palette ─────────────────────────────────────────────────── */

const CHART_COLORS = [
  "var(--chart-c1)", "var(--chart-c2)", "var(--chart-c3)", "var(--chart-c4)",
  "var(--chart-c5)", "var(--chart-c6)", "var(--chart-c7)", "var(--chart-c8)",
  "oklch(0.55 0.06 210)", "oklch(0.50 0.08 130)", "oklch(0.52 0.06 60)", "oklch(0.48 0.04 0)",
];

/* ── Treemap Custom Content ───────────────────────────────────────────────── */

function TreemapCell(props: any) {
  const { x, y, width, height, ticker, pct, fill } = props;
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
          {ticker}
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
}: {
  name: string;
  pct: number;
  amount?: number;
  color: string;
  maxPct: number;
}) {
  const barWidth = maxPct > 0 ? (pct / maxPct) * 100 : 0;

  return (
    <div className="flex items-center gap-3 py-1.5 group">
      <span className="text-xs text-muted-foreground w-[120px] shrink-0 truncate group-hover:text-foreground transition-colors">
        {name}
      </span>
      <div className="flex-1 h-5 bg-slate-100 dark:bg-slate-800/40 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500 ease-out"
          style={{ width: `${barWidth}%`, backgroundColor: color, opacity: 0.8 }}
        />
      </div>
      <span className="text-xs font-semibold text-foreground text-numeric w-[44px] text-right">
        {pct.toFixed(1)}%
      </span>
      {amount !== undefined && (
        <span className="text-xs text-muted-foreground text-numeric w-[72px] text-right">
          {formatCurrency(amount)}
        </span>
      )}
    </div>
  );
}

/* ── Component ────────────────────────────────────────────────────────────── */

export default function InvestmentsAllocation({ timeframe: _tf, accountFilter }: InvestmentsTabProps) {
  const allocUrl = accountFilter === "all"
    ? "/api/investments/allocation"
    : `/api/investments/allocation?account_id=${encodeURIComponent(accountFilter)}`;
  const { data: allocData, loading } = useOwnerApi<any>(allocUrl);

  const totalValue = allocData?.total_value || 0;
  const bySector = allocData?.by_sector || [];
  const byAssetClass = allocData?.by_asset_class || [];
  const byGeography = allocData?.by_geography || [];
  const byMarketCap = allocData?.by_market_cap || [];
  const treemapRaw = allocData?.treemap || [];

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

  const treemapData = useMemo(() =>
    treemapRaw.map((t: any, i: number) => ({
      name: t.ticker,
      ticker: t.ticker,
      size: t.size,
      pct: t.pct,
      assetClass: t.asset_class,
      fill: CHART_COLORS[i % CHART_COLORS.length],
    })),
    [treemapRaw]
  );

  const maxSectorPct = Math.max(...bySector.map((s: any) => s.pct), 1);
  const maxGeoPct = Math.max(...byGeography.map((g: any) => g.pct), 1);
  const maxCapPct = Math.max(...byMarketCap.map((m: any) => m.pct), 1);

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

      {/* ── Section 1: Asset Allocation Donut ──────────────────────────── */}
      <div className="card-l1 p-6">
        <p className="text-label mb-4">Asset Allocation</p>
        <div className="flex flex-col lg:flex-row items-center gap-8">
          <div className="relative w-[260px] h-[260px] shrink-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '12px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)' }}
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
              <span className="text-xl font-bold text-foreground">{formatCurrency(totalValue)}</span>
              <span className="text-label mt-0.5">Total Value</span>
            </div>
          </div>

          <div className="flex-1 space-y-2 w-full">
            {allocation.map((cls: any) => (
              <div key={cls.name} className="flex items-center justify-between py-2.5 px-4 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                <div className="flex items-center gap-3">
                  <div className="size-3 rounded-full" style={{ backgroundColor: cls.color }} />
                  <span className="text-sm font-medium text-foreground">{cls.name}</span>
                </div>
                <div className="flex items-center gap-5">
                  <span className="text-sm font-semibold text-numeric text-foreground">{formatCurrency(cls.amount)}</span>
                  <span className="text-xs text-muted-foreground text-numeric w-12 text-right">{cls.value}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Section 2 + 3: Portfolio Composition + Sector Exposure (side by side) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Portfolio Treemap */}
        <div className="card-l1 flex flex-col">
          <div className="px-6 pt-5 pb-3">
            <p className="text-label">Portfolio Composition</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Box size proportional to portfolio weight
            </p>
          </div>
          <div className="px-4 pb-4 flex-1">
            {treemapData.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <Treemap
                  data={treemapData}
                  dataKey="size"
                  aspectRatio={3 / 2}
                  content={<TreemapCell />}
                >
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '12px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)' }}
                    formatter={(_value: any, name: any, props: any) => {
                      const item = props?.payload;
                      const pctStr = item?.pct != null ? ` (${item.pct.toFixed(1)}%)` : "";
                      return [
                        `${formatCurrency(item?.size)}${pctStr}`,
                        item?.assetClass || name || "",
                      ];
                    }}
                  />
                </Treemap>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-[280px] text-muted-foreground text-sm">
                No allocation data available
              </div>
            )}
          </div>
        </div>

        {/* Sector Exposure */}
        <div className="card-l1 p-6 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-label">Sector Exposure</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                Breakdown across all holdings
              </p>
            </div>
            <span className="text-[10px] font-medium text-muted-foreground bg-slate-100 dark:bg-slate-800/50 px-2 py-0.5 rounded-full">
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
              />
            ))}
          </div>
        </div>
      </div>

      {/* ── Section 4: Geographic + Market Cap (side by side) ─────────── */}
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
              />
            ))}
          </div>
        </div>

        {/* Market Cap */}
        <div className="card-l1 p-6">
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
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
