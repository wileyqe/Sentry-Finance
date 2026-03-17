import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { motion } from "framer-motion";
import AccountsSummaryCard from "../components/AccountsSummaryCard";

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

  const [accounts, setAccounts] = useState<any[]>([]);
  const [networthData, setNetworthData] = useState<any[]>([]);
  const [chartType, setChartType] = useState<'Line' | 'Bar'>('Line');
  const [timeframe, setTimeframe] = useState('6 months');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    'Credit cards': true,
    'Loans': true,
    'Cash': true,
    'Real Estate': true,
    'Investments': true,
  });

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/accounts")
      .then(res => res.json())
      .then(data => {
        if (data.accounts && data.accounts.length > 0) {
          setAccounts(data.accounts);
        }
        setExpandedGroups({
          'Credit cards': true,
          'Loans': true,
          'Cash': true,
          'Real Estate': true,
          'Investments': true,
        });
      })
      .catch(err => {
        console.error("Error fetching accounts: ", err);
      });
  }, []);

  // Fetch full history when timeframe changes — API already returns assets/liabilities/net_worth
  useEffect(() => {
    const months = TIMEFRAME_MAP[timeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/net-worth-history?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.history) {
          setNetworthData(data.history.map((h: any) => ({
            date: h.month,
            net_worth:   h.net_worth,
            assets:      h.assets,
            liabilities: h.liabilities,
          })));
        }
      })
      .catch(console.error);
  }, [timeframe]);



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
    { name: 'Credit cards', accounts: displayAccounts.filter(a => ['credit_card'].includes(a.type)), icon: 'credit_card', color: 'text-rose-500', bg: 'bg-rose-500/10' },
    { name: 'Loans', accounts: displayAccounts.filter(a => ['loan', 'bnpl'].includes(a.type)), icon: 'account_balance', color: 'text-amber-500', bg: 'bg-amber-500/10' },
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
    // Navigate to transactions filtered by this account
    const accountId = account._originalId || account.id;
    navigate(`/transactions?account_id=${encodeURIComponent(accountId)}`);
  };

  return (
    <motion.div 
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar relative p-12"
    >
      
      {/* Contextual Chart Header Section */}
      <motion.div variants={itemVariants} className="mb-8 card-l1 p-6 flex flex-col h-[400px]">
        <div className="flex items-start justify-between mb-4">
          <div>
            {/* 3-tab mode switcher */}
            <div className="flex items-center gap-1 mb-3 bg-slate-100 dark:bg-slate-800 rounded-lg p-1 w-fit">
              {(['net_worth', 'assets', 'liabilities'] as const).map(mode => (
                <button
                  key={mode}
                  onClick={() => switchFilter(mode)}
                  className={`px-3 py-1.5 rounded-md text-xs font-bold transition-all duration-200 ${
                    filterMode === mode
                      ? 'bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                  }`}
                >
                  {mode === 'net_worth' ? 'Net Worth' : mode === 'assets' ? 'Assets' : 'Liabilities'}
                </button>
              ))}
            </div>
            <h1 className="text-3xl font-bold tracking-tight mb-1 text-numeric" style={{ color: filterMode === 'liabilities' ? 'var(--color-loss)' : filterMode === 'assets' ? 'var(--color-gain)' : undefined }}>
              ${Math.abs(displayTotal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </h1>
            <div className="flex items-center gap-2">
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
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center bg-slate-100 dark:bg-primary/5 rounded-full p-1 border border-slate-200 dark:border-primary/10">
              <button 
                className={`px-3 py-1 rounded-full text-xs font-bold transition-colors ${
                  chartType === 'Line' 
                    ? 'bg-white dark:bg-primary/20 text-slate-900 dark:text-white shadow-sm' 
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                }`}
                onClick={() => setChartType('Line')}
              >Line</button>
              <button 
                className={`px-3 py-1 rounded-full text-xs font-bold transition-colors ${
                  chartType === 'Bar' 
                    ? 'bg-white dark:bg-primary/20 text-slate-900 dark:text-white shadow-sm' 
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
                }`}
                onClick={() => setChartType('Bar')}
              >Bar</button>
            </div>
            <select 
              className="bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
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
                <YAxis hide domain={filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [`$${Math.abs(Number(value)).toLocaleString()}`, cfg.label]}
                />
                <Area type="monotone" dataKey={cfg.dataKey} stroke={cfg.color} strokeWidth={2.5} fillOpacity={1} fill={`url(#${cfg.gradientId})`} />
              </AreaChart>
            ) : (
              <BarChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.15} />
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={filterMode === 'liabilities' ? ['auto', 0] : [0, 'auto']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [`$${Math.abs(Number(value)).toLocaleString()}`, cfg.label]}
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
            const groupTotal = group.accounts.reduce((sum, a) => sum + (a.balance || 0), 0);
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
                      {groupTotal < 0 ? "-" : ""}${Math.abs(groupTotal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                </button>
                
                {isExpanded && (
                  <div className="divide-y divide-slate-100 dark:divide-primary/5 animate-in slide-in-from-top-2 duration-200">
                    {group.accounts.map((account) => {
                        const hasPurchasePrice = account.purchase_price && account.purchase_price > 0;
                        const paidPct = hasPurchasePrice
                          ? Math.round(((account.purchase_price + account.balance) / account.purchase_price) * 100)
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
                                    <span className="uppercase text-[10px] font-bold">{account.institution_id}</span>
                                    <span>•</span>
                                    <span>...{account.last4 || '****'}</span>
                                    {account.interest_rate && (
                                      <><span>•</span><span>{account.interest_rate}% APR</span></>
                                    )}
                                  </p>
                                </div>
                              </div>
                              <div className="flex items-center gap-3">
                                <div className="text-right">
                                  <p className={`font-bold text-numeric ${account.balance < 0 ? 'text-loss' : 'text-slate-900 dark:text-slate-100'}`}>
                                    {account.balance < 0 ? "-" : ""}${Math.abs(account.balance || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                                  </p>
                                  <p className="text-[10px] text-slate-400">
                                    {account.balance_as_of ? new Date(account.balance_as_of).toLocaleDateString() : 'Pending'}
                                  </p>
                                </div>
                                <span className="material-symbols-outlined text-slate-300 text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                              </div>
                            </div>

                            {/* Payoff progress bar — only for loans with purchase_price */}
                            {hasPurchasePrice && (
                              <div className="ml-12 flex flex-col gap-1">
                                <div className="flex items-center justify-between text-[10px] text-slate-400">
                                  <span className="font-semibold text-gain" style={{ color: 'var(--color-gain)' }}>{paidPct}% paid off</span>
                                  <span>${Math.abs(account.balance).toLocaleString(undefined, { maximumFractionDigits: 0 })} remaining of ${account.purchase_price.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
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
                          </div>
                        );
                    })}
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
