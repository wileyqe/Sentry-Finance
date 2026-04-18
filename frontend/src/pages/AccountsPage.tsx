import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { motion } from "framer-motion";
import AccountsSummaryCard from "../components/AccountsSummaryCard";
import { useOwnerApi } from "../lib/useOwnerApi";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR } from "@/lib/dateUtils";
import SyntheticBadge from "@/components/ui/SyntheticBadge";

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
  const [expandedGroups, setExpandedGroups] = useSessionState<Record<string, boolean>>('accounts:expandedGroups', {
    'Credit cards': true,
    'Loans': true,
    'Cash': true,
    'Real Estate': true,
    'Investments': true,
  });

  const { data: accountsData } = useOwnerApi<{ accounts: any[] }>(`/api/accounts`);
  const accounts = accountsData?.accounts || [];

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
      const cashPortion = (acct.balance || 0) - acct.holdings_value;
      
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

  // Compute actual trend percentages from net worth data
  // --- Derive chart display config from filterMode ---
  const FILTER_CONFIG = {
    net_worth:   { label: 'Net Worth',   dataKey: 'net_worth',   color: 'oklch(0.52 0.12 240)', gradientId: 'chartGradBlue',   totalFn: (d: any[]) => d.length ? d[d.length-1].net_worth : 0 },
    assets:      { label: 'Cash Assets', dataKey: 'assets',      color: 'oklch(0.52 0.13 155)', gradientId: 'chartGradGreen',  totalFn: (d: any[]) => d.length ? d[d.length-1].assets : 0 },
    liabilities: { label: 'Liabilities', dataKey: 'liabilities', color: 'oklch(0.48 0.13 20)',  gradientId: 'chartGradRed',    totalFn: (d: any[]) => d.length ? d[d.length-1].liabilities : 0 },
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
  const ASSET_GROUPS  = new Set(['Cash', 'Real Estate', 'Investments']);
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
  const BASE_GROUPS = [
    { name: 'Credit cards', accounts: displayAccounts.filter(a => ['credit_card', 'credit'].includes(a.type)), icon: 'credit_card', color: 'text-rose-500', bg: 'bg-rose-500/10' },
    { name: 'Loans', accounts: displayAccounts.filter(a => ['loan', 'bnpl', 'mortgage'].includes(a.type)), icon: 'account_balance', color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { name: 'Cash', accounts: displayAccounts.filter(a => ['checking', 'savings'].includes(a.type)), icon: 'payments', color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
    { name: 'Real Estate', accounts: displayAccounts.filter(a => ['real_estate', 'property'].includes(a.type)), icon: 'home', color: 'text-purple-500', bg: 'bg-purple-500/10' },
    { name: 'Investments', accounts: displayAccounts.filter(a => ['investment', 'retirement'].includes(a.type)), icon: 'trending_up', color: 'text-sky-500', bg: 'bg-sky-500/10' },
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
            <div className="flex items-center gap-0.5 mb-3 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5 w-fit">
              {(['net_worth', 'assets', 'liabilities'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => switchFilter(mode)}
                  className={`px-4 py-1.5 rounded-full text-[12.5px] font-semibold transition-all duration-150 ${
                    filterMode === mode
                      ? 'bg-white dark:bg-slate-700 text-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {mode === 'net_worth' ? 'Net Worth' : mode === 'assets' ? 'Assets' : 'Liabilities'}
                </button>
              ))}
            </div>
            <h1 className="text-3xl font-bold tracking-tight mb-1 text-numeric" style={{ color: filterMode === 'liabilities' ? 'var(--color-loss)' : filterMode === 'assets' ? 'var(--color-gain)' : undefined }}>
              {formatCurrency(displayTotal)}
            </h1>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="text-label">{cfg.label} · as of last refresh</p>
              {networthData.length >= 2 && (
                <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                  nwTrend.startsWith('+') ? 'text-gain bg-[var(--color-gain)]/10' : 
                  nwTrend.startsWith('-') ? 'text-loss bg-[var(--color-loss)]/10' : 
                  'text-neutral bg-slate-100'
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
                  <span className="text-[10px] text-slate-400 flex items-center gap-1">
                    <span className="material-symbols-outlined text-[12px]">info</span>
                    Data through {formattedDate}
                  </span>
                );
              })()}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5">
              {(['Line', 'Bar'] as const).map(t => (
                <button
                  key={t}
                  className={`px-3 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                    chartType === t
                      ? 'bg-white dark:bg-slate-700 text-foreground shadow-sm'
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
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={(filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']) as any} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [formatCurrency(Number(value)), cfg.label]}
                />
                <Area type="monotone" dataKey={cfg.dataKey} stroke={cfg.color} strokeWidth={2.5} fillOpacity={1} fill={`url(#${cfg.gradientId})`} />
              </AreaChart>
            ) : (
              <BarChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.15} />
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={(filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']) as any} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [formatCurrency(Number(value)), cfg.label]}
                />
                <Bar dataKey={cfg.dataKey} fill={cfg.color} radius={[4, 4, 0, 0]} />
              </BarChart>
            )}
          </ResponsiveContainer>
          ) : (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">Loading chart data...</div>
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
                    <div className="flex-1 h-px bg-slate-200 dark:bg-slate-700" />
                    <span className="text-label text-[10px]">Other accounts</span>
                    <div className="flex-1 h-px bg-slate-200 dark:bg-slate-700" />
                  </div>
                )}
              <div className={`card-l1 transition-all duration-300 ${isDismissed ? 'opacity-50' : 'opacity-100'}`}>
                <button 
                  onClick={() => toggleGroup(group.name)}
                  className={`w-full px-6 py-4 bg-slate-50 dark:bg-primary/5 hover:bg-slate-100 dark:hover:bg-primary/10 transition-colors flex items-center justify-between rounded-t-xl ${isExpanded ? 'border-b border-slate-200 dark:border-primary/10' : 'rounded-b-xl'}`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`material-symbols-outlined transition-transform duration-200 text-slate-400 ${isExpanded ? 'rotate-90' : ''}`}>
                      chevron_right
                    </span>
                    <div className={`size-8 ${group.bg} rounded-md flex items-center justify-center ${group.color}`}>
                      <span className="material-symbols-outlined text-sm font-bold">{group.icon}</span>
                    </div>
                    <h3 className="font-bold uppercase tracking-wider text-sm">{group.name}</h3>
                  </div>
                  <div className="flex items-center gap-6">
                    <span className={`font-bold ${groupTotal < 0 ? 'text-loss' : 'text-slate-900 dark:text-white'}`}>
                      {formatCurrency(groupTotal)}
                    </span>
                  </div>
                </button>
                
                {isExpanded && (
                  <div className="divide-y divide-slate-100 dark:divide-primary/5 animate-in slide-in-from-top-2 duration-200">
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

                        return (
                          <div
                            key={account.id}
                            className="px-6 py-4 flex flex-col gap-2 hover:bg-slate-50/50 dark:hover:bg-primary/5 transition-colors cursor-pointer group/item last:rounded-b-xl"
                            onClick={() => handleAccountClick(account)}
                            title={`View transactions for ${account.name}`}
                          >
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-4">
                                <div className="size-8 bg-slate-100 dark:bg-primary/10 rounded-full flex items-center justify-center text-slate-500 group-hover/item:text-primary transition-colors">
                                  <span className="material-symbols-outlined text-[14px] font-bold">{getInstitutionLogo(account.institution_id)}</span>
                                </div>
                                <div>
                                  <h4 className="font-semibold text-slate-900 dark:text-slate-100 group-hover/item:text-primary transition-colors">{account.name}</h4>
                                    <p className="text-xs text-slate-500 flex items-center gap-2">
                                      <span className="uppercase text-[10px] font-bold">{institutionDisplayName(account.institution_id)}</span>
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'fresh' && (
                                        <span className="w-2 h-2 rounded-full bg-emerald-500" title="Data is fresh (> 24 hrs)" />
                                      )}
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'stale' && (
                                        <span className="w-2 h-2 rounded-full bg-yellow-400" title="Data is getting stale (1-3 days)" />
                                      )}
                                      {freshnessMap[account.institution_id] && freshnessMap[account.institution_id].staleness === 'critical' && (
                                        <span className="w-2 h-2 rounded-full bg-red-500" title="Data is critically stale" />
                                      )}
                                      <span>•</span>
                                      <span>...{account.last4 || '****'}</span>
                                      {account.interest_rate && (
                                        <><span>•</span><span>{account.interest_rate}% APR</span></>
                                      )}
                                      {account.is_synthetic === 1 && <SyntheticBadge compact />}
                                    </p>
                                </div>
                              </div>
                              <div className="flex items-center gap-3">
                                <div className="text-right">
                                  <p className={`font-bold text-numeric ${account.balance < 0 ? 'text-loss' : 'text-slate-900 dark:text-slate-100'}`}>
                                    {formatCurrency(account.balance || 0)}
                                  </p>
                                  <p className="text-[10px] text-slate-400">
                                    {account.balance_as_of ? new Date(account.balance_as_of).toLocaleDateString() : 'Pending'}
                                  </p>
                                </div>
                                <span className="material-symbols-outlined text-slate-300 text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                              </div>
                            </div>

                            {/* Payoff progress bar — installment debts (loans/mortgage/BNPL) */}
                            {hasPurchasePrice && (
                              <div className="ml-12 flex flex-col gap-1">
                                <div className="flex items-center justify-between text-[10px] text-slate-400">
                                  <span className="font-semibold text-gain" style={{ color: 'var(--color-gain)' }}>{paidPct}% paid off</span>
                                  <span>{formatCurrency(Math.abs(account.balance))} remaining of {formatCurrency(account.purchase_price)}</span>
                                </div>
                                <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
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
                                <div className="flex items-center justify-between text-[10px] text-slate-400">
                                  <span className="font-semibold" style={{ color: utilizationPct > 70 ? 'var(--color-loss)' : utilizationPct > 30 ? 'oklch(0.75 0.15 75)' : 'var(--color-gain)' }}>
                                    {utilizationPct}% utilized
                                  </span>
                                  <span>{formatCurrency(Math.abs(account.balance || 0))} of {formatCurrency(account.credit_limit)} limit</span>
                                </div>
                                <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                                  <div
                                    className="h-full rounded-full transition-all duration-500"
                                    style={{
                                      width: `${utilizationPct}%`,
                                      backgroundColor: utilizationPct > 70 ? 'var(--color-loss)' : utilizationPct > 30 ? 'oklch(0.75 0.15 75)' : 'var(--color-gain)',
                                    }}
                                  />
                                </div>
                              </div>
                            )}

                            {/* Document Drop Nudge (Inline) */}
                            {nudges.find((n: any) => n.institution === account.institution_id) && (
                              <div className="ml-12 mt-2 px-3 py-2 rounded-md bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 flex gap-2 items-center">
                                <span className="material-symbols-outlined text-rose-500 text-sm">warning</span>
                                <span className="text-xs text-rose-600 dark:text-rose-400">{nudges.find((n: any) => n.institution === account.institution_id).message}</span>
                              </div>
                            )}
                          </div>
                        );
                    })}

                    {/* Closed & Paid Off — collapsible toggle */}
                    {closedAccounts.length > 0 && (
                      <div className="border-t border-slate-100 dark:border-primary/5">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setExpandedClosed(prev => ({ ...prev, [group.name]: !prev[group.name] }));
                          }}
                          className="w-full px-6 py-2.5 flex items-center justify-center gap-2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors group/closed"
                        >
                          <span className="material-symbols-outlined text-[14px] transition-transform duration-200" style={{ transform: expandedClosed[group.name] ? 'rotate(90deg)' : 'rotate(0deg)' }}>chevron_right</span>
                          <span className="text-[10px] font-bold uppercase tracking-wider">
                            {closedAccounts.length} Paid Off
                          </span>
                        </button>

                        {expandedClosed[group.name] && (
                          <div className="animate-in slide-in-from-top-1 duration-150">
                            {closedAccounts.map((account: any) => (
                              <div
                                key={account.id}
                                className="px-6 py-3 flex items-center justify-between hover:bg-slate-50/50 dark:hover:bg-primary/5 transition-colors cursor-pointer group/item"
                                onClick={() => handleAccountClick(account)}
                                title={`View transactions for ${account.name}`}
                              >
                                <div className="flex items-center gap-4">
                                  <div className="size-8 bg-emerald-50 dark:bg-emerald-900/20 rounded-full flex items-center justify-center text-emerald-500">
                                    <span className="material-symbols-outlined text-[14px]">check_circle</span>
                                  </div>
                                  <div>
                                    <h4 className="font-medium text-slate-500 dark:text-slate-400 text-sm">{account.name}</h4>
                                    <p className="text-xs text-slate-400 flex items-center gap-2">
                                      <span className="uppercase text-[10px] font-bold">{institutionDisplayName(account.institution_id)}</span>
                                      <span>•</span>
                                      <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
                                        {account.status === 'paid_off' ? 'PAID OFF' : 'CLOSED'}
                                      </span>
                                    </p>
                                  </div>
                                </div>
                                <div className="flex items-center gap-3">
                                  <p className="font-bold text-numeric text-slate-400 text-sm">{formatCurrency(account.balance || 0)}</p>
                                  <span className="material-symbols-outlined text-slate-300 text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                                </div>
                              </div>
                            ))}
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

    </motion.div>
  );
}
