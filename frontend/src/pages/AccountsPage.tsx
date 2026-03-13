import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import AccountsSummaryCard from "../components/AccountsSummaryCard";

const TIMEFRAME_MAP: Record<string, number> = {
  '1 month': 1,
  '3 months': 3,
  '6 months': 6,
  '1 year': 12,
  'All time': 120,
};

export default function AccountsPage() {
  const navigate = useNavigate();
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

  // Fetch net worth data when timeframe changes
  useEffect(() => {
    const months = TIMEFRAME_MAP[timeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/net-worth-history?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.history) {
          setNetworthData(data.history.map((h: any) => ({
            date: h.month,
            value: h.net_worth,
          })));
        }
      })
      .catch(console.error);
  }, [timeframe]);

  const totalBalance = accounts.reduce((acc, curr) => acc + (curr.balance || 0), 0);

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
  const computeGroupTrend = (): string => {
    if (networthData.length < 2) return '0.0%';
    const first = networthData[0];
    const last = networthData[networthData.length - 1];
    if (!first || !last) return '0.0%';
    
    const firstVal = first.value || 0;
    const lastVal = last.value || 0;
    if (firstVal === 0) return '0.0%';
    
    const change = ((lastVal - firstVal) / Math.abs(firstVal) * 100);
    const sign = change >= 0 ? '+' : '';
    return `${sign}${change.toFixed(1)}%`;
  };

  const nwTrend = computeGroupTrend();

  const groupedByType = [
    { name: 'Credit cards', accounts: displayAccounts.filter(a => ['credit_card'].includes(a.type)), icon: 'credit_card', color: 'text-rose-500', bg: 'bg-rose-500/10' },
    { name: 'Loans', accounts: displayAccounts.filter(a => ['loan', 'bnpl'].includes(a.type)), icon: 'account_balance', color: 'text-amber-500', bg: 'bg-amber-500/10' },
    { name: 'Cash', accounts: displayAccounts.filter(a => ['checking', 'savings'].includes(a.type)), icon: 'payments', color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
    { name: 'Real Estate', accounts: displayAccounts.filter(a => ['real_estate', 'property'].includes(a.type)), icon: 'home', color: 'text-purple-500', bg: 'bg-purple-500/10' },
    { name: 'Investments', accounts: displayAccounts.filter(a => ['investment', 'retirement'].includes(a.type)), icon: 'trending_up', color: 'text-sky-500', bg: 'bg-sky-500/10' },
  ].filter(group => group.accounts.length > 0);

  const toggleGroup = (groupName: string) => {
    setExpandedGroups(prev => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  const handleAccountClick = (account: any) => {
    // Navigate to transactions filtered by this account
    const accountId = account._originalId || account.id;
    navigate(`/transactions?account_id=${encodeURIComponent(accountId)}`);
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar relative p-8">
      
      {/* Net Worth Chart Header Section */}
      <div className="mb-8 bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm flex flex-col h-[400px]">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight mb-2">Net Worth</h1>
            <h3 className="font-bold text-lg mb-1">${totalBalance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h3>
            <div className="flex items-center gap-2">
              <p className="text-xs text-slate-500">Values as of last refresh</p>
              {networthData.length >= 2 && (
                <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                  nwTrend.startsWith('+') ? 'text-green-500 bg-green-500/10' : 
                  nwTrend.startsWith('-') ? 'text-red-500 bg-red-500/10' : 
                  'text-slate-500 bg-slate-500/10'
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
                  <linearGradient id="colorValueAcct" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={['dataMin - 1000', 'dataMax + 1000']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Net Worth']}
                />
                <Area type="monotone" dataKey="value" stroke="#0ea5e9" strokeWidth={3} fillOpacity={1} fill="url(#colorValueAcct)" />
              </AreaChart>
            ) : (
              <BarChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.15} />
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={['dataMin - 1000', 'dataMax + 1000']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [`$${Number(value).toLocaleString()}`, 'Net Worth']}
                />
                <Bar dataKey="value" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
              </BarChart>
            )}
          </ResponsiveContainer>
          ) : (
            <div className="flex-1 flex items-center justify-center text-slate-400 text-sm">Loading chart data...</div>
          )}
        </div>
      </div>

      <div className="flex flex-col xl:flex-row gap-8 items-start">
        {/* Feeder Sections */}
        <div className="flex-1 w-full space-y-6">
          {groupedByType.map((group) => {
            const groupTotal = group.accounts.reduce((sum, a) => sum + (a.balance || 0), 0);
            const isExpanded = expandedGroups[group.name];
            
            return (
              <div key={group.name} className="bg-white dark:bg-background-dark/50 border border-slate-200 dark:border-primary/10 rounded-xl shadow-sm">
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
                    <span className={`font-bold ${groupTotal < 0 ? 'text-red-500' : 'text-slate-900 dark:text-white'}`}>
                      {groupTotal < 0 ? "-" : ""}${Math.abs(groupTotal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                  </div>
                </button>
                
                {isExpanded && (
                  <div className="divide-y divide-slate-100 dark:divide-primary/5 animate-in slide-in-from-top-2 duration-200">
                    {group.accounts.map((account) => (
                      <div 
                        key={account.id} 
                        className="px-6 py-4 flex items-center justify-between hover:bg-slate-50/50 dark:hover:bg-primary/5 transition-colors cursor-pointer group/item last:rounded-b-xl"
                        onClick={() => handleAccountClick(account)}
                        title={`View transactions for ${account.name}`}
                      >
                        <div className="flex items-center gap-4">
                          {/* Institution icon next to account */}
                          <div className="size-8 bg-slate-100 dark:bg-primary/10 rounded-full flex items-center justify-center text-slate-500 group-hover/item:text-primary transition-colors">
                            <span className="material-symbols-outlined text-[14px] font-bold">{getInstitutionLogo(account.institution_id)}</span>
                          </div>
                          <div>
                            <h4 className="font-semibold text-slate-900 dark:text-slate-100 group-hover/item:text-primary transition-colors">{account.name}</h4>
                            <p className="text-xs text-slate-500 flex items-center gap-2">
                              <span className="uppercase text-[10px] font-bold">{account.institution_id}</span>
                              <span>•</span>
                              <span>...{account.last4 || '****'}</span>
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="text-right">
                            <p className={`font-bold ${account.balance < 0 ? 'text-red-500' : 'text-slate-900 dark:text-slate-100'}`}>
                              {account.balance < 0 ? "-" : ""}${Math.abs(account.balance || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                            </p>
                            <p className="text-[10px] text-slate-400">
                              {account.balance_as_of ? new Date(account.balance_as_of).toLocaleDateString() : 'Pending'}
                            </p>
                          </div>
                          <span className="material-symbols-outlined text-slate-300 text-sm group-hover/item:text-primary transition-colors">chevron_right</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Sidebar Summary Card */}
        <div className="w-full xl:w-[400px] flex-shrink-0 sticky top-0">
          <AccountsSummaryCard accounts={displayAccounts} />
        </div>
      </div>

    </div>
  );
}
