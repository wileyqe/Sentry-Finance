import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { motion } from "framer-motion";
import AccountsSummaryCard from "../components/AccountsSummaryCard";
import ManualAssetEditModal, { type ManualAssetKind } from "../components/ManualAssetEditModal";
import { AccountDetailsPanel } from "../components/accounts/AccountDetailsPanel";
import { ManualAssetDetailsPanel } from "../components/accounts/ManualAssetDetailsPanel";
import { useOwnerApi } from "../lib/useOwnerApi";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR } from "@/lib/dateUtils";
import SyntheticBadge from "@/components/ui/SyntheticBadge";
import {
  rechartsTooltipStyle,
  rechartsTooltipLabelStyle,
  rechartsTooltipItemStyle,
  rechartsAxisTickStyle,
  rechartsGridStyle,
} from "@/lib/chartStyle";

interface VehicleRow {
  id: string;
  make: string;
  model: string;
  year: number;
  purchase_price?: number | null;
  purchase_date?: string | null;
  latest_value?: number | null;
  latest_value_as_of?: string | null;
  latest_value_source?: string | null;
}

interface RealEstateRow {
  id: number;
  name: string;
  estimated_value: number;
  as_of: string;
  source: string;
  linked_loan_id?: string | null;
  owner_id?: string | null;
}

interface AccountsResponse {
  accounts: any[];
  manual_assets?: {
    real_estate: RealEstateRow[];
    vehicles: VehicleRow[];
  };
}

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

const TIMEFRAME_MAP: Record<string, number> = {
  '1 month': 1,
  '3 months': 3,
  '6 months': 6,
  '1 year': 12,
  'All time': 120,
};

const testIdPart = (value: unknown) =>
  String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";

export default function AccountsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  // Filter mode — driven by URL param or local tab click
  type FilterMode = 'net_worth' | 'assets' | 'liabilities';
  const paramFilter = searchParams.get('filter');
  const initialFilter: FilterMode =
    paramFilter === 'assets' ? 'assets' :
    paramFilter === 'liabilities' ? 'liabilities' :
    'net_worth';
  const [filterMode, setFilterMode] = useState<FilterMode>(initialFilter);

  // Sync filterMode when URL param changes (e.g. fresh navigation from Dashboard)
  useEffect(() => {
    const f = searchParams.get('filter');
    if (f === 'assets') setFilterMode('assets');
    else if (f === 'liabilities') setFilterMode('liabilities');
    else setFilterMode('net_worth');
  }, [searchParams]);

  const switchFilter = (mode: FilterMode) => {
    setFilterMode(mode);
    if (mode === 'net_worth') setSearchParams({});
    else setSearchParams({ filter: mode });
  };

  // removed accounts state redeclaration
  const [networthData, setNetworthData] = useState<any[]>([]);
  const [chartType, setChartType] = useSessionState<'Line' | 'Bar'>('accounts:chartType', 'Line');
  const [timeframe, setTimeframe] = useSessionState('accounts:timeframe', '6 months');
  const [expandedClosed, setExpandedClosed] = useSessionState<Record<string, boolean>>('accounts:expandedClosed', {});
  const [expandedDetails, setExpandedDetails] = useSessionState<Record<string, boolean>>('accounts:expandedDetails', {});
  const [expandedGroups, setExpandedGroups] = useSessionState<Record<string, boolean>>('accounts:expandedGroups', {
    'Credit cards': true,
    'Loans': true,
    'Cash': true,
    'Real Estate': true,
    'Vehicles': true,
    'Investments': true,
  });

  const { data: accountsData, refetch: refetchAccounts } =
    useOwnerApi<AccountsResponse>(`/api/accounts`);
  const accounts = accountsData?.accounts || [];
  const manualRealEstate = accountsData?.manual_assets?.real_estate || [];
  const manualVehicles = accountsData?.manual_assets?.vehicles || [];

  // Modal state for editing manual asset valuations.
  const [editingAsset, setEditingAsset] = useState<
    { kind: ManualAssetKind; row: VehicleRow | RealEstateRow } | null
  >(null);

  const { data: freshnessData } = useOwnerApi<any[]>("/api/freshness");
  const freshnessMap = (freshnessData || []).reduce((acc: any, f: any) => ({ ...acc, [f.institution_id]: f }), {});

  const { data: nudgesData } = useOwnerApi<{ nudges: any[] }>("/api/documents/pending-nudges");
  const nudges = nudgesData?.nudges || [];

  // Fetch full history when timeframe changes
  const months = TIMEFRAME_MAP[timeframe] || 6;
  const { data: networthHistory } = useOwnerApi<{ history: any[] }>(`/api/reports/net-worth-history?months=${months}`);
  useEffect(() => {
    if (networthHistory?.history) {
      setNetworthData(networthHistory.history.map((h: any) => ({
        date: h.month,
        net_worth:   h.net_worth,
        assets:      h.assets,
        liabilities: h.liabilities,
      })));
    }
  }, [networthHistory]);



  const getInstitutionLogo = (instId: string) => {
    const iconMap: Record<string, string> = {
      nfcu: "account_balance",
      chase: "assured_workload",
      acorns: "spa",
      fidelity: "trending_up",
      tsp: "account_balance",
      affirm: "shopping_bag"
    };
    return iconMap[instId] || "account_balance";
  };

  // Pre-process accounts: if an investment account has `holdings_value` but its balance is greater 
  // than holdings_value by a margin, split the cash out into a distinct 'savings' account object
  let displayAccounts: any[] = [];
  accounts.forEach(acct => {
    if (acct.type === 'investment' && acct.holdings_value != null) {
      const margin = 1.0; // small threshold
      const holdings = acct.holdings_value || 0;
      const cashPortion = (acct.balance || 0) - holdings;
      
      if (cashPortion > margin) {
        // Push the investment portion
        displayAccounts.push({
          ...acct,
          id: acct.id + '_inv',
          _originalId: acct.id,
          name: acct.name + ' (Investments)',
          balance: acct.holdings_value
        });
        
        // Push the cash portion
        displayAccounts.push({
          ...acct,
          id: acct.id + '_cash',
          _originalId: acct.id,
          name: acct.name + ' (Cash)',
          type: 'savings', // Treat it as cash
          balance: cashPortion
        });
        return;
      }
    }
    // Default fallback
    displayAccounts.push(acct);
  });

  // ── Inject manual assets (real_estate + vehicles) as synthetic account rows ──
  // These live in their own tables server-side; we synthesize Account-shaped
  // rows so the existing grouping / summary logic just works. The `manual:`
  // prefix prevents ID collisions with real accounts and lets the click
  // handler branch to the edit modal.
  manualRealEstate.forEach((re) => {
    displayAccounts.push({
      id: `manual:re:${re.id}`,
      _manualKind: 'real_estate' as const,
      _manualRow: re,
      institution_id: 'manual',
      name: re.name,
      type: 'real_estate',
      balance: re.estimated_value ?? 0,
      balance_as_of: re.as_of,
      status: 'active',
    });
  });
  manualVehicles.forEach((v) => {
    displayAccounts.push({
      id: `manual:veh:${v.id}`,
      _manualKind: 'vehicle' as const,
      _manualRow: v,
      institution_id: 'manual',
      name: `${v.year} ${v.make} ${v.model}`,
      type: 'vehicle',
      balance: v.latest_value ?? 0,
      balance_as_of: v.latest_value_as_of ?? null,
      status: 'active',
    });
  });

  // Compute actual trend percentages from net worth data
  // --- Derive chart display config from filterMode ---
  const FILTER_CONFIG = {
    net_worth:   { label: 'Net Worth',   dataKey: 'net_worth',   color: 'var(--chart-c2)',    gradientId: 'chartGradBlue',   totalFn: (d: any[]) => d.length ? d[d.length-1].net_worth : 0 },
    assets:      { label: 'Cash Assets', dataKey: 'assets',      color: 'var(--color-gain)',  gradientId: 'chartGradGreen',  totalFn: (d: any[]) => d.length ? d[d.length-1].assets : 0 },
    liabilities: { label: 'Liabilities', dataKey: 'liabilities', color: 'var(--color-loss)',  gradientId: 'chartGradRed',    totalFn: (d: any[]) => d.length ? d[d.length-1].liabilities : 0 },
  };
  const cfg = FILTER_CONFIG[filterMode];

  const computeGroupTrend = (): string => {
    if (networthData.length < 2) return '0.0%';
    const first = networthData[0];
    const last = networthData[networthData.length - 1];
    if (!first || !last) return '0.0%';
    const firstVal = first[cfg.dataKey] || 0;
    const lastVal = last[cfg.dataKey] || 0;
    if (firstVal === 0) return '0.0%';
    const change = ((lastVal - firstVal) / Math.abs(firstVal) * 100);
    const sign = change >= 0 ? '+' : '';
    return `${sign}${change.toFixed(1)}%`;
  };

  const nwTrend = computeGroupTrend();
  const displayTotal = cfg.totalFn(networthData);

  // Which account groups belong to which filter bucket
  const ASSET_GROUPS  = new Set(['Cash', 'Real Estate', 'Vehicles', 'Investments']);
  const LIAB_GROUPS   = new Set(['Credit cards', 'Loans']);

  // When filterMode changes: reorder + expand/collapse accordingly
  useEffect(() => {
    setExpandedGroups(prev => {
      const next = { ...prev };
      if (filterMode === 'net_worth') {
        // Expand everything
        [...ASSET_GROUPS, ...LIAB_GROUPS].forEach(g => { next[g] = true; });
      } else {
        const relevant  = filterMode === 'assets' ? ASSET_GROUPS : LIAB_GROUPS;
        const dismissed = filterMode === 'assets' ? LIAB_GROUPS  : ASSET_GROUPS;
        relevant.forEach(g  => { next[g] = true;  });
        dismissed.forEach(g => { next[g] = false; });
      }
      return next;
    });
  }, [filterMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Base group definitions (stable)
  // Sentiment mapping: Cash = gain (positive NW), Credit Cards = loss (debt),
  // Loans = warning (long-term debt), everything else rotates through chart slots.
  const BASE_GROUPS = [
    { name: 'Credit cards', accounts: displayAccounts.filter(a => ['credit_card', 'credit'].includes(a.type)), icon: 'credit_card', color: 'text-loss', bg: 'bg-loss-subtle' },
    { name: 'Loans', accounts: displayAccounts.filter(a => ['loan', 'bnpl', 'mortgage'].includes(a.type)), icon: 'account_balance', color: 'text-[var(--color-warning)]', bg: 'bg-[var(--color-warning)]/10' },
    { name: 'Cash', accounts: displayAccounts.filter(a => ['checking', 'savings'].includes(a.type)), icon: 'payments', color: 'text-gain', bg: 'bg-gain-subtle' },
    { name: 'Real Estate', accounts: displayAccounts.filter(a => ['real_estate', 'property'].includes(a.type)), icon: 'home', color: 'text-[var(--chart-c4)]', bg: 'bg-[var(--chart-c4)]/10' },
    { name: 'Vehicles', accounts: displayAccounts.filter(a => a.type === 'vehicle'), icon: 'directions_car', color: 'text-[var(--chart-c7)]', bg: 'bg-[var(--chart-c7)]/10' },
    { name: 'Investments', accounts: displayAccounts.filter(a => ['investment', 'retirement'].includes(a.type)), icon: 'trending_up', color: 'text-[var(--chart-c2)]', bg: 'bg-[var(--chart-c2)]/10' },
  ].filter(group => group.accounts.length > 0);

  // Sort: relevant groups first, dismissed last
  const groupedByType = filterMode === 'net_worth'
    ? BASE_GROUPS
    : [
        ...BASE_GROUPS.filter(g => (filterMode === 'assets' ? ASSET_GROUPS : LIAB_GROUPS).has(g.name)),
        ...BASE_GROUPS.filter(g => (filterMode === 'assets' ? LIAB_GROUPS : ASSET_GROUPS).has(g.name)),
      ];

  const toggleGroup = (groupName: string) => {
    setExpandedGroups(prev => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  const handleAccountClick = (account: any) => {
    // Manual assets (home, vehicle) open the valuation-edit modal instead of
    // navigating to transactions — they have no transaction history.
    if (account._manualKind) {
      setEditingAsset({ kind: account._manualKind, row: account._manualRow });
      return;
    }
    const accountId = account._originalId || account.id;
    // Investment/retirement accounts have no transactions — open Investments page
    if (account.type === 'investment' || account.type === 'retirement') {
      navigate('/investments');
      return;
    }
    navigate(`/transactions?account_id=${encodeURIComponent(accountId)}`);
  };

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar relative px-12 py-8"
    >
      
      {/* Contextual Chart Header Section */}
      <motion.div variants={itemVariants} className="mb-8 card-l1 p-6 flex flex-col h-[400px]">
        <div className="flex items-start justify-between mb-4">
          <div>
            {/* 3-tab mode switcher */}
            <div className="flex items-center gap-0.5 mb-3 bg-surface-raised rounded-full p-0.5 w-fit">
              {(['net_worth', 'assets', 'liabilities'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => switchFilter(mode)}
                  className={`px-4 py-1.5 rounded-full text-[12.5px] font-semibold transition-all duration-150 ${
                    filterMode === mode
                      ? 'bg-card text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {mode === 'net_worth' ? 'Net Worth' : mode === 'assets' ? 'Assets' : 'Liabilities'}
                </button>
              ))}
            </div>
            <h1 className="text-3xl font-bold tracking-tight mb-1 text-numeric" style={{ color: filterMode === 'liabilities' ? 'var(--color-loss)' : filterMode === 'assets' ? 'var(--color-gain)' : undefined }} data-testid="accounts-display-total">
              {formatCurrency(displayTotal)}
            </h1>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-label">{cfg.label} · as of last refresh</p>
              {networthData.length >= 2 && (
                <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                  nwTrend.startsWith('+') ? 'text-gain bg-[var(--color-gain)]/10' :
                  nwTrend.startsWith('-') ? 'text-loss bg-[var(--color-loss)]/10' :
                  'text-neutral bg-surface-raised'
                }`}>
                  {nwTrend} over {timeframe}
                </span>
              )}
              {/* Data freshness annotation — derive last real snapshot from balance history */}
              {(() => {
                if (networthData.length < 2) return null;
                // Find the last month where the net_worth actually changed
                let lastRealIdx = networthData.length - 1;
                for (let i = networthData.length - 1; i > 0; i--) {
                  if (networthData[i].net_worth !== networthData[i - 1].net_worth) {
                    lastRealIdx = i;
                    break;
                  }
                }
                const lastDate = networthData[lastRealIdx]?.date;
                if (!lastDate || lastRealIdx === networthData.length - 1) return null;
                // Format "2025-12" → "Dec 2025"
                const [yr, mo] = lastDate.split('-');
                const formattedDate = mo ? `${MONTH_ABBR[parseInt(mo, 10) - 1]} ${yr}` : lastDate;
                return (
                  <span className="text-[10px] text-muted-foreground flex items-center gap-1">
                    <span className="material-symbols-outlined text-[12px]">info</span>
                    Data through {formattedDate}
                  </span>
                );
              })()}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-0.5 bg-surface-raised rounded-full p-0.5">
              {(['Line', 'Bar'] as const).map(t => (
                <button
                  key={t}
                  className={`px-3 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                    chartType === t
                      ? 'bg-card text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                  onClick={() => setChartType(t)}
                >{t}</button>
              ))}
            </div>
            <select
              className="bg-card border border-border rounded-lg px-3 h-9 text-xs font-semibold outline-none cursor-pointer"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              {Object.keys(TIMEFRAME_MAP).map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="w-full mt-4 h-[250px]">
          {networthData.length > 0 ? (
          <ResponsiveContainer width="100%" height={250}>
            {chartType === 'Line' ? (
              <AreaChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id={cfg.gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={cfg.color} stopOpacity={0.25}/>
                    <stop offset="95%" stopColor={cfg.color} stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={rechartsAxisTickStyle()} dy={10} minTickGap={20} />
                <YAxis hide domain={(filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']) as any} />
                <Tooltip
                  contentStyle={rechartsTooltipStyle()}
                  labelStyle={rechartsTooltipLabelStyle()}
                  itemStyle={rechartsTooltipItemStyle()}
                  formatter={(value: any) => [formatCurrency(Number(value)), cfg.label]}
                />
                <Area type="monotone" dataKey={cfg.dataKey} stroke={cfg.color} strokeWidth={2.5} fillOpacity={1} fill={`url(#${cfg.gradientId})`} />
              </AreaChart>
            ) : (
              <BarChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid {...rechartsGridStyle()} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={rechartsAxisTickStyle()} dy={10} minTickGap={20} />
                <YAxis hide domain={(filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']) as any} />
                <Tooltip
                  contentStyle={rechartsTooltipStyle()}
                  labelStyle={rechartsTooltipLabelStyle()}
                  itemStyle={rechartsTooltipItemStyle()}
                  formatter={(value: any) => [formatCurrency(Number(value)), cfg.label]}
                />
                <Bar dataKey={cfg.dataKey} fill={cfg.color} radius={[4, 4, 0, 0]} />
              </BarChart>
            )}
          </ResponsiveContainer>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">Loading chart data...</div>
          )}
        </div>
      </motion.div>

      <div className="flex flex-col xl:flex-row gap-8 items-start">
        {/* Feeder Sections */}
        <div className="flex-1 w-full space-y-6">
          {groupedByType.map((group, idx) => {
            const activeAccounts = group.accounts.filter((a: any) => a.status === 'active');
            const closedAccounts = group.accounts.filter((a: any) => a.status === 'paid_off' || a.status === 'closed');
            const groupTotal = activeAccounts.reduce((sum: number, a: any) => sum + (a.balance || 0), 0);
            const isExpanded = expandedGroups[group.name];

            const relevantSet = filterMode === 'assets' ? ASSET_GROUPS : LIAB_GROUPS;
            const isDismissed = filterMode !== 'net_worth' && !relevantSet.has(group.name);

            // Insert a divider before the first dismissed group
            const prevGroup = groupedByType[idx - 1];
            const showDivider = filterMode !== 'net_worth' && isDismissed && prevGroup && relevantSet.has(prevGroup.name);

            return (
              <div key={group.name}>
                {showDivider && (
                  <div className="flex items-center gap-3 py-2">
                    <div className="flex-1 h-px bg-border" />
                    <span className="text-label text-[10px]">Other accounts</span>
                    <div className="flex-1 h-px bg-border" />
                  </div>
                )}
              <div className={`card-l1 transition-all duration-300 ${isDismissed ? 'opacity-50' : 'opacity-100'}`}>
                <button 
                  onClick={() => toggleGroup(group.name)}
                  className={`w-full px-6 py-4 bg-surface-raised hover:bg-surface-raised/80 transition-colors flex items-center justify-between rounded-t-xl ${isExpanded ? 'border-b border-border' : 'rounded-b-xl'}`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`material-symbols-outlined transition-transform duration-200 text-muted-foreground ${isExpanded ? 'rotate-90' : ''}`}>
                      chevron_right
                    </span>
                    <div className={`size-8 ${group.bg} rounded-md flex items-center justify-center ${group.color}`}>
                      <span className="material-symbols-outlined text-sm font-bold">{group.icon}</span>
                    </div>
                    <h3 className="font-bold uppercase tracking-wider text-sm">{group.name}</h3>
                  </div>
                  <div className="flex items-center gap-6">
                    <span
                      className={`font-bold ${groupTotal < 0 ? 'text-loss' : 'text-foreground'}`}
                      data-testid={`accounts-group-total-${testIdPart(group.name)}`}
                    >
                      {formatCurrency(groupTotal)}
                    </span>
                  </div>
                </button>
                
                {isExpanded && (
                  <div className="divide-y divide-border animate-in slide-in-from-top-2 duration-200">
                    {activeAccounts.map((account: any) => {
                        const hasPurchasePrice = account.purchase_price && account.purchase_price > 0;
                        const hasCreditLimit = account.credit_limit && account.credit_limit > 0;
                        // hasProgressBar purposely unused but logical

                        // Installment debt: paid = (original + balance) / original  [balance is negative]
                        const paidPct = hasPurchasePrice
                          ? Math.max(0, Math.min(100, Math.round(((account.purchase_price + account.balance) / account.purchase_price) * 100)))
                          : 0;

                        // Credit card: utilization = abs(balance) / credit_limit
                        const utilizationPct = hasCreditLimit
                          ? Math.max(0, Math.min(100, Math.round((Math.abs(account.balance || 0) / account.credit_limit) * 100)))
                          : 0;

                        // P15-T09: investment / retirement accounts now
                        // surface scraped fund details (per-fund YTD, SPAXX
                        // SEC yield, Acorns round-ups), so the Details
                        // toggle is enabled across all account types.
                        const hasDetailsToggle = true;
                        const detailsOpen = !!expandedDetails[account.id];
                        const toggleDetails = (e: React.MouseEvent | React.KeyboardEvent) => {
                          e.stopPropagation();
                          setExpandedDetails(prev => ({ ...prev, [account.id]: !prev[account.id] }));
                        };

                        return (
                          <div
                            key={account.id}
                            className="flex flex-col hover:bg-surface-raised/50 transition-colors group/item last:rounded-b-xl"
                          >
                          <div
                            className="px-6 py-4 flex flex-col gap-2 cursor-pointer"
                            onClick={() => handleAccountClick(account)}
                            title={`View transactions for ${account.name}`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-4">
                                <div className="size-8 bg-surface-raised rounded-full flex items-center justify-center text-muted-foreground group-hover/item:text-primary transition-colors">
                                  <span className="material-symbols-outlined text-[14px] font-bold">{getInstitutionLogo(account.institution_id)}</span>
                                </div>
                                <div>
                                  <h4 className="font-semibold text-foreground group-hover/item:text-primary transition-colors">{account.name}</h4>
                                    <p className="text-xs text-muted-foreground flex items-center gap-2">
                                      <span className="uppercase text-[10px] font-bold">{institutionDisplayName(account.institution_id)}</span>
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'fresh' && (
                                        <span className="w-2 h-2 rounded-full bg-[var(--color-gain)]" title="Data is fresh (> 24 hrs)" />
                                      )}
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'stale' && (
                                        <span className="w-2 h-2 rounded-full bg-[var(--color-warning)]" title="Data is getting stale (1-3 days)" />
                                      )}
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'critical' && (
                                        <span className="w-2 h-2 rounded-full bg-[var(--color-loss)]" title="Data is critically stale" />
                                      )}
                                      <span>•</span>
                                      <span>...{account.last4 || '****'}</span>
                                      {account.interest_rate && (
                                        <><span>•</span><span>{account.interest_rate}% APR</span></>
                                      )}
                                      {(() => {
                                        const raw = account.rewards_points;
                                        if (!raw) return null;
                                        const pts = parseInt(String(raw).replace(/,/g, ''), 10);
                                        if (!Number.isFinite(pts)) return null;
                                        return (
                                          <>
                                            <span>•</span>
                                            <span
                                              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[var(--color-warning)]/10 text-[var(--color-warning)] text-[10px] font-semibold"
                                              title="Rewards points balance"
                                            >
                                              <span className="material-symbols-outlined text-[11px]">redeem</span>
                                              {pts.toLocaleString()} pts
                                            </span>
                                          </>
                                        );
                                      })()}
                                      {!!account.is_synthetic && <SyntheticBadge compact />}
                                    </p>
                                </div>
                              </div>
                              <div className="flex items-center gap-3">
                                <div className="text-right">
                                  <p className={`font-bold text-numeric ${account.balance < 0 ? 'text-loss' : 'text-foreground'}`}>
                                    {formatCurrency(account.balance || 0)}
                                  </p>
                                  <p className="text-[10px] text-muted-foreground">
                                    {account.balance_as_of ? new Date(account.balance_as_of).toLocaleDateString() : 'Pending'}
                                  </p>
                                </div>
                                {hasDetailsToggle && (
                                  <button
                                    type="button"
                                    onClick={toggleDetails}
                                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation(); }}
                                    aria-expanded={detailsOpen}
                                    aria-label={detailsOpen ? 'Hide details' : 'Show details'}
                                    title={detailsOpen ? 'Hide details' : 'Show details'}
                                    className="focus-ring flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium text-muted-foreground hover:text-foreground bg-surface-raised/60 hover:bg-surface-raised transition-colors"
                                  >
                                    <span aria-hidden="true" className="material-symbols-outlined text-[16px]">
                                      {detailsOpen ? 'unfold_less' : 'unfold_more'}
                                    </span>
                                    Details
                                  </button>
                                )}
                                <span className="material-symbols-outlined text-muted-foreground text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                              </div>
                            </div>

                            {/* Payoff progress bar — installment debts (loans/mortgage/BNPL) */}
                            {hasPurchasePrice && (
                              <div className="ml-12 flex flex-col gap-1">
                                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                                  <span className="font-semibold text-gain" style={{ color: 'var(--color-gain)' }}>{paidPct}% paid off</span>
                                  <span>{formatCurrency(Math.abs(account.balance))} remaining of {formatCurrency(account.purchase_price)}</span>
                                </div>
                                <div className="h-1.5 rounded-full bg-surface-raised overflow-hidden">
                                  <div
                                    className="h-full rounded-full transition-all duration-500"
                                    style={{
                                      width: `${paidPct}%`,
                                      backgroundColor: 'var(--color-gain)',
                                    }}
                                  />
                                </div>
                              </div>
                            )}

                            {/* Utilization bar — credit cards */}
                            {hasCreditLimit && !hasPurchasePrice && (
                              <div className="ml-12 flex flex-col gap-1">
                                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                                  <span className="font-semibold" style={{ color: utilizationPct > 70 ? 'var(--color-loss)' : utilizationPct > 30 ? 'var(--color-warning)' : 'var(--color-gain)' }}>
                                    {utilizationPct}% utilized
                                  </span>
                                  <span>{formatCurrency(Math.abs(account.balance || 0))} of {formatCurrency(account.credit_limit)} limit</span>
                                </div>
                                <div className="h-1.5 rounded-full bg-surface-raised overflow-hidden">
                                  <div
                                    className="h-full rounded-full transition-all duration-500"
                                    style={{
                                      width: `${utilizationPct}%`,
                                      backgroundColor: utilizationPct > 70 ? 'var(--color-loss)' : utilizationPct > 30 ? 'var(--color-warning)' : 'var(--color-gain)',
                                    }}
                                  />
                                </div>
                              </div>
                            )}

                            {/* Document Drop Nudge (Inline) */}
                            {nudges.find((n: any) => n.institution === account.institution_id) && (
                              <div className="ml-12 mt-2 px-3 py-2 rounded-md bg-loss-subtle border border-[var(--color-loss)]/20 flex gap-2 items-center">
                                <span className="material-symbols-outlined text-loss text-sm">warning</span>
                                <span className="text-xs text-loss">{nudges.find((n: any) => n.institution === account.institution_id).message}</span>
                              </div>
                            )}
                          </div>
                          {hasDetailsToggle && account._manualKind && (
                            <ManualAssetDetailsPanel
                              assetKind={account._manualKind}
                              assetId={account._manualRow?.id ?? account.id}
                              open={detailsOpen}
                            />
                          )}
                          {hasDetailsToggle && !account._manualKind && (
                            <AccountDetailsPanel
                              accountId={account._originalId || account.id}
                              accountType={account.type}
                              open={detailsOpen}
                            />
                          )}
                          </div>
                        );
                    })}

                    {/* Closed & Paid Off — collapsible toggle */}
                    {closedAccounts.length > 0 && (
                      <div className="border-t border-border">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setExpandedClosed(prev => ({ ...prev, [group.name]: !prev[group.name] }));
                          }}
                          className="w-full px-6 py-2.5 flex items-center justify-center gap-2 text-muted-foreground hover:text-foreground transition-colors group/closed"
                        >
                          <span className="material-symbols-outlined text-[14px] transition-transform duration-200" style={{ transform: expandedClosed[group.name] ? 'rotate(90deg)' : 'rotate(0deg)' }}>chevron_right</span>
                          <span className="text-[10px] font-bold uppercase tracking-wider">
                            {closedAccounts.length} Paid Off
                          </span>
                        </button>

                        {expandedClosed[group.name] && (
                          <div className="animate-in slide-in-from-top-1 duration-150">
                            {closedAccounts.map((account: any) => {
                              const closedHasToggle =
                                !account._manualKind &&
                                account.type !== 'investment' &&
                                account.type !== 'retirement';
                              const closedDetailsOpen = !!expandedDetails[account.id];
                              const toggleClosedDetails = (e: React.MouseEvent | React.KeyboardEvent) => {
                                e.stopPropagation();
                                setExpandedDetails(prev => ({ ...prev, [account.id]: !prev[account.id] }));
                              };
                              return (
                              <div key={account.id} className="flex flex-col hover:bg-surface-raised/50 transition-colors group/item">
                                <div
                                  className="px-6 py-3 flex items-center justify-between cursor-pointer"
                                  onClick={() => handleAccountClick(account)}
                                  title={`View transactions for ${account.name}`}
                                >
                                  <div className="flex items-center gap-4">
                                    <div className="size-8 bg-gain-subtle rounded-full flex items-center justify-center text-gain">
                                      <span className="material-symbols-outlined text-[14px]">check_circle</span>
                                    </div>
                                    <div>
                                      <h4 className="font-medium text-muted-foreground text-sm">{account.name}</h4>
                                      <p className="text-xs text-muted-foreground flex items-center gap-2">
                                        <span className="uppercase text-[10px] font-bold">{institutionDisplayName(account.institution_id)}</span>
                                        <span>•</span>
                                        <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-gain-subtle text-gain">
                                          {account.status === 'paid_off' ? 'PAID OFF' : 'CLOSED'}
                                        </span>
                                      </p>
                                    </div>
                                  </div>
                                  <div className="flex items-center gap-3">
                                    <p className="font-bold text-numeric text-muted-foreground text-sm">{formatCurrency(account.balance || 0)}</p>
                                    {closedHasToggle && (
                                      <button
                                        type="button"
                                        onClick={toggleClosedDetails}
                                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') e.stopPropagation(); }}
                                        aria-expanded={closedDetailsOpen}
                                        aria-label={closedDetailsOpen ? 'Hide details' : 'Show details'}
                                        title={closedDetailsOpen ? 'Hide details' : 'Show details'}
                                        className="focus-ring flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium text-muted-foreground hover:text-foreground bg-surface-raised/60 hover:bg-surface-raised transition-colors"
                                      >
                                        <span aria-hidden="true" className="material-symbols-outlined text-[16px]">
                                          {closedDetailsOpen ? 'unfold_less' : 'unfold_more'}
                                        </span>
                                        Details
                                      </button>
                                    )}
                                    <span className="material-symbols-outlined text-muted-foreground text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                                  </div>
                                </div>
                                {closedHasToggle && (
                                  <AccountDetailsPanel
                                    accountId={account._originalId || account.id}
                                    accountType={account.type}
                                    open={closedDetailsOpen}
                                  />
                                )}
                              </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
              </div>
            );
          })}
        </div>

        {/* Sidebar Summary Card */}
        <div className="w-full xl:w-[400px] flex-shrink-0 sticky top-0">
          <AccountsSummaryCard accounts={displayAccounts} />
        </div>
      </div>

      <ManualAssetEditModal
        kind={editingAsset?.kind ?? 'vehicle'}
        asset={editingAsset?.row ?? null}
        onClose={() => setEditingAsset(null)}
        onSaved={() => refetchAccounts()}
      />
    </motion.div>
  );
}
