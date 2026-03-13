import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from "recharts";

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

const TIMEFRAME_MAP: Record<string, number> = {
  '1 month': 1,
  '3 months': 3,
  '6 months': 6,
  '1 year': 12,
  'All time': 120,
};

const CASHFLOW_TF_MAP: Record<string, number> = {
  'Last 3 Months': 3,
  'Last 6 Months': 6,
  'Last 12 Months': 12,
  'All Time': 60,
};

const ACCOUNT_NAMES: Record<string, string> = {
  chase_chk_001: 'Chase Total Checking',
  nfcu_sav_001: 'NFCU Emergency Savings',
  chase_cc_001: 'Sapphire Reserve',
  amex_cc_001: 'Blue Cash Preferred',
  rocket_mtg_001: 'Home Mortgage',
  fidelity_inv_001: 'Individual Brokerage',
  acorns_inv_001: 'Acorns Invest',
};

const CATEGORY_ICONS: Record<string, { icon: string; color: string }> = {
  Mortgage: { icon: 'home', color: 'blue' },
  'Auto Insurance': { icon: 'directions_car', color: 'blue' },
  Insurance: { icon: 'shield', color: 'blue' },
  Utilities: { icon: 'bolt', color: 'purple' },
  Entertainment: { icon: 'movie', color: 'pink' },
  Transfer: { icon: 'sync_alt', color: 'green' },
  Health: { icon: 'fitness_center', color: 'orange' },
};

export default function DashboardPage() {
  const navigate = useNavigate();
  const [recentTransactions, setRecentTransactions] = useState<any[]>([]);
  const [networthData, setNetworthData] = useState<any[]>([]);
  const [spendingData, setSpendingData] = useState<any[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [nwTimeframe, setNwTimeframe] = useState('6 months');
  const [cfTimeframe, setCfTimeframe] = useState('Last 6 Months');
  const [budgetSummary, setBudgetSummary] = useState<any>(null);
  const [recurringItems, setRecurringItems] = useState<any[]>([]);

  // Fetch net worth data when timeframe changes
  useEffect(() => {
    const months = TIMEFRAME_MAP[nwTimeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/net-worth-history?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.history) {
          setNetworthData(data.history.map((h: any) => ({
            date: h.month,
            value: h.net_worth,
            orig: h
          })));
        }
      })
      .catch(console.error);
  }, [nwTimeframe]);

  // Fetch cash flow data when timeframe changes
  useEffect(() => {
    const months = CASHFLOW_TF_MAP[cfTimeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/cash-flow?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.months) {
          setSpendingData(data.months.map((m: any) => {
            const [yr, mo] = m.month.split('-');
            return {
              day: `${MONTH_NAMES[parseInt(mo, 10) - 1]} '${yr.slice(2)}`,
              income: m.income,
              spending: m.spending
            };
          }));
        }
      })
      .catch(console.error);
  }, [cfTimeframe]);

  // Fetch recent transactions and summary metrics (once)
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/transactions?limit=8")
      .then(res => res.json())
      .then(data => setRecentTransactions(data.transactions || []))
      .catch(err => console.error(err));

    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    fetch(`http://127.0.0.1:8000/api/reports/summary?start_date=${y}-${m}-01&end_date=${y}-${m}-31`)
      .then(res => res.json())
      .then(data => setMetrics(data))
      .catch(console.error);
  }, []);

  // Fetch budget summary + categories for current month
  useEffect(() => {
    const now = new Date();
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    // Fetch summary and budget-vs-actual in parallel
    Promise.all([
      fetch(`http://127.0.0.1:8000/api/budgets/summary?month=${month}`).then(r => r.json()),
      fetch(`http://127.0.0.1:8000/api/budgets?month=${month}`).then(r => r.json()).catch(() => []),
    ]).then(([summary, budgetData]) => {
      // budgetData is {month, categories: [{category, target, actual, remaining, pct_used}, ...]}
      const cats = budgetData?.categories || [];
      setBudgetSummary({
        ...summary,
        total_budgeted: summary.total_budget || 0,
        categories: cats.map((b: any) => ({
          category: b.category,
          target_amount: b.target || b.target_amount || 0,
          spent: b.actual || 0,
        })),
      });
    }).catch(console.error);
  }, []);

  // Fetch recurring transactions
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/recurring")
      .then(res => res.json())
      .then(data => setRecurringItems(data.recurring || []))
      .catch(console.error);
  }, []);

  const latestNw = networthData.length > 0 ? networthData[networthData.length - 1].orig : null;

  // Budget widget calculations
  const budgetTotal = budgetSummary?.total_budgeted || 0;
  const budgetSpent = budgetSummary?.total_spent || 0;
  const budgetRemaining = budgetTotal - budgetSpent;
  const budgetPct = budgetTotal > 0 ? Math.min((budgetSpent / budgetTotal) * 100, 100) : 0;
  const now = new Date();
  const budgetMonth = `${MONTH_NAMES[now.getMonth()]} ${now.getFullYear()}`;

  // Recurring widget calculations
  const recurringTotal = recurringItems.reduce((s, r) => s + (r.expected_amount || r.last_amount || 0), 0);

  return (
    <div className="flex-1 overflow-auto custom-scrollbar p-8 space-y-6">
      
      {/* Top Snapshot Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div 
          className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/20 rounded-xl p-6 shadow-sm cursor-pointer hover:border-primary/40 hover:shadow-md transition-all duration-200"
          onClick={() => navigate('/accounts')}
        >
          <div className="flex items-center gap-2 mb-2 text-slate-500">
            <span className="material-symbols-outlined text-xl">payments</span>
            <span className="font-semibold text-sm tracking-wide">CASH</span>
          </div>
          <p className="text-3xl font-extrabold">${latestNw?.banking_assets?.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}</p>
          <p className="text-xs text-green-500 font-bold mt-2">Dynamic from dummy data</p>
        </div>
        <div 
          className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/20 rounded-xl p-6 shadow-sm cursor-pointer hover:border-primary/40 hover:shadow-md transition-all duration-200"
          onClick={() => navigate('/accounts')}
        >
          <div className="flex items-center gap-2 mb-2 text-slate-500">
            <span className="material-symbols-outlined text-xl">credit_card</span>
            <span className="font-semibold text-sm tracking-wide">DEBT</span>
          </div>
          <p className="text-3xl font-extrabold">-${latestNw?.liabilities?.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}</p>
          <p className="text-xs text-slate-500 font-bold mt-2">Dynamic from dummy data</p>
        </div>
        <div 
          className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/20 rounded-xl p-6 shadow-sm cursor-pointer hover:border-primary/40 hover:shadow-md transition-all duration-200"
          onClick={() => navigate('/transactions')}
        >
          <div className="flex items-center gap-2 mb-2 text-slate-500">
            <span className="material-symbols-outlined text-xl">sync_alt</span>
            <span className="font-semibold text-sm tracking-wide">MONTHLY CASH FLOW</span>
          </div>
          <p className="text-3xl font-extrabold text-green-500">${metrics?.net?.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}</p>
          <div className="flex items-center gap-4 mt-2 text-xs font-bold text-slate-500">
            <span>In: <span className="text-slate-900 dark:text-slate-100">${metrics?.total_income?.toLocaleString() || '0'}</span></span>
            <span>Out: <span className="text-slate-900 dark:text-slate-100">${metrics?.total_spending?.toLocaleString() || '0'}</span></span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Net Worth Chart */}
        <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm col-span-1 lg:col-span-1 flex flex-col h-[400px]">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="font-bold text-lg mb-1">${latestNw?.net_worth?.toLocaleString() || '0'} net worth</h3>
              <p className="text-xs text-slate-500">Based on seeded dummy data</p>
            </div>
            <select 
              className="bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
              value={nwTimeframe}
              onChange={(e) => setNwTimeframe(e.target.value)}
            >
              {Object.keys(TIMEFRAME_MAP).map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 w-full mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={networthData} margin={{ top: 5, right: 0, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0ea5e9" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={20} />
                <YAxis hide domain={['dataMin - 1000', 'dataMax + 1000']} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any) => [`$${value.toLocaleString()}`, 'Net Worth']}
                />
                <Area type="monotone" dataKey="value" stroke="#0ea5e9" strokeWidth={3} fillOpacity={1} fill="url(#colorValue)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Spending Chart */}
        <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm col-span-1 lg:col-span-1 flex flex-col h-[400px]">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3 className="font-bold text-lg mb-1">Cash Flow <span className="text-sm font-normal text-slate-500">${metrics?.total_spending?.toLocaleString() || '0'} this month</span></h3>
            </div>
            <select 
              className="bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
              value={cfTimeframe}
              onChange={(e) => setCfTimeframe(e.target.value)}
            >
              {Object.keys(CASHFLOW_TF_MAP).map(tf => (
                <option key={tf} value={tf}>{tf}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 w-full mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={spendingData} margin={{ top: 5, right: 0, left: -20, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.2} />
                <XAxis dataKey="day" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(val) => `$${val/1000}K`} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '12px' }}
                  formatter={(value: any, name: any) => [`$${Number(value).toLocaleString()}`, name]}
                />
                <Line type="monotone" dataKey="income" stroke="#10b981" strokeWidth={2} dot={false} name="Income" />
                <Line type="monotone" dataKey="spending" stroke="#ef4444" strokeWidth={3} dot={false} name="Spending" activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="flex items-center justify-center gap-6 mt-2 text-xs font-bold">
            <div className="flex items-center gap-2 text-emerald-500">
              <div className="w-3 h-0 border-t-2 border-emerald-500"></div>
              <span>Income</span>
            </div>
            <div className="flex items-center gap-2 text-red-500">
              <div className="w-3 h-0 border-t-2 border-red-500"></div>
              <span>Spending</span>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Transactions Mini */}
        <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl shadow-sm col-span-1 lg:col-span-2 overflow-hidden flex flex-col">
          <div className="p-6 border-b border-slate-200 dark:border-primary/10 flex items-center justify-between">
            <h3 className="font-bold text-lg">Transactions <span className="text-sm font-normal text-slate-500">Most recent</span></h3>
            <button 
              className="text-xs font-bold text-primary hover:underline"
              onClick={() => navigate('/transactions')}
            >View All</button>
          </div>
          <div className="flex-1 overflow-auto divide-y divide-slate-100 dark:divide-primary/5">
            {recentTransactions.map((tx: any) => (
              <div 
                key={tx.id} 
                className="p-4 flex items-center justify-between hover:bg-slate-50/50 dark:hover:bg-primary/5 transition-colors cursor-pointer group"
                onClick={() => navigate('/transactions', { state: { selectedTxId: tx.id } })}
              >
                <div className="flex items-center gap-4">
                  <div className="size-8 bg-slate-100 dark:bg-primary/10 rounded-full flex items-center justify-center">
                    <img src={`https://logo.clearbit.com/${tx.merchant?.replace(/ /g, '').toLowerCase()}.com`} 
                         onError={(e) => { e.currentTarget.src = "https://ui-avatars.com/api/?name=" + (tx.merchant || "TX") + "&background=random"; }} 
                         className="size-5 rounded-full object-cover" alt="" />
                  </div>
                  <div>
                    <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">{tx.description || tx.merchant}</h4>
                    <p className="text-xs text-slate-500 flex items-center gap-1">
                      <span className="material-symbols-outlined text-[12px]">category</span>
                      {tx.category}
                      <span className="text-slate-400 ml-1">•</span>
                      <span className="text-slate-400">{ACCOUNT_NAMES[tx.account_id] || tx.account_id}</span>
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`font-bold text-sm ${(tx.signed_amount ?? tx.amount) < 0 ? 'text-slate-900 dark:text-slate-100' : 'text-green-500'}`}>
                    {(tx.signed_amount ?? tx.amount) < 0 ? "" : "+"}${Math.abs(tx.signed_amount ?? tx.amount).toFixed(2)}
                  </span>
                  <span className="material-symbols-outlined text-slate-400 text-sm group-hover:text-primary transition-colors">chevron_right</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right side stack */}
        <div className="col-span-1 flex flex-col gap-6">
          
          {/* Budget Widget — API Driven */}
          <div 
            className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm w-full cursor-pointer hover:border-primary/30 transition-colors"
            onClick={() => navigate('/budgets')}
          >
            <h3 className="font-bold text-lg mb-6">Budget <span className="text-sm font-normal text-slate-500">{budgetMonth}</span></h3>
            
            <div className="mb-6">
              <div className="flex justify-between text-sm font-bold mb-2">
                <span>Expenses</span>
                <span className="text-slate-500">${budgetTotal.toLocaleString()} budget</span>
              </div>
              <div className="w-full bg-slate-100 dark:bg-primary/5 h-2 rounded-full overflow-hidden">
                <div className="bg-primary h-full rounded-full transition-all duration-500" style={{ width: `${budgetPct}%` }}></div>
              </div>
              <div className="flex justify-between text-xs mt-2 font-semibold">
                <span>${budgetSpent.toLocaleString()} spent</span>
                <span className="text-primary">${budgetRemaining.toLocaleString()} remaining</span>
              </div>
            </div>

            {budgetSummary?.categories && (
              <div className="space-y-2 mt-4 border-t border-slate-100 dark:border-primary/10 pt-4">
                {budgetSummary.categories.slice(0, 4).map((cat: any) => {
                  const pct = cat.target_amount > 0 ? Math.min((cat.spent / cat.target_amount) * 100, 100) : 0;
                  return (
                    <div key={cat.category} className="flex items-center gap-3">
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-400 w-20 truncate">{cat.category}</span>
                      <div className="flex-1 bg-slate-100 dark:bg-primary/5 h-1.5 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full ${pct > 90 ? 'bg-red-500' : 'bg-primary'}`} style={{ width: `${pct}%` }}></div>
                      </div>
                      <span className="text-[10px] font-bold text-slate-500 w-8 text-right">{pct.toFixed(0)}%</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Recurring Widget — API Driven */}
          <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl shadow-sm overflow-hidden flex-1 flex flex-col">
             <div className="p-6 border-b border-slate-200 dark:border-primary/10 flex items-center justify-between">
              <h3 className="font-bold text-lg">Recurring <span className="text-sm font-normal text-slate-500">${recurringTotal.toLocaleString(undefined, {minimumFractionDigits: 2})} /mo</span></h3>
            </div>
            <div className="flex-1 overflow-auto divide-y divide-slate-100 dark:divide-primary/5 px-4 pb-4">
              {recurringItems.slice(0, 5).map((item: any) => {
                const catMeta = CATEGORY_ICONS[item.category] || { icon: 'receipt_long', color: 'slate' };
                return (
                  <div key={item.id} className="py-4 flex items-center justify-between hover:bg-slate-50/50 dark:hover:bg-primary/5 rounded-lg px-2 transition-colors cursor-pointer" onClick={() => navigate('/transactions')}>
                    <div className="flex items-center gap-3">
                      <div className={`size-8 bg-${catMeta.color}-500/10 rounded-full flex items-center justify-center border border-${catMeta.color}-500/20`}>
                        <span className={`material-symbols-outlined text-${catMeta.color}-500 text-sm`}>{catMeta.icon}</span>
                      </div>
                      <div>
                        <h4 className="font-bold text-sm">{item.merchant}</h4>
                        <p className="text-xs text-slate-500 capitalize">{item.frequency}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-sm">${(item.expected_amount || item.last_amount || 0).toLocaleString(undefined, {minimumFractionDigits: 2})}</p>
                      <p className="text-[10px] uppercase font-bold text-slate-400">
                        {item.next_expected ? new Date(item.next_expected).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}
                      </p>
                    </div>
                  </div>
                );
              })}
              {recurringItems.length === 0 && (
                <div className="py-8 text-center text-sm text-slate-400">No recurring transactions found</div>
              )}
            </div>
          </div>

        </div>
      </div>

    </div>
  );
}
