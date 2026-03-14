import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { AreaChart, BarChart } from "@tremor/react";
import { motion } from "framer-motion";

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

  useEffect(() => {
    const months = TIMEFRAME_MAP[nwTimeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/net-worth-history?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.history) {
          setNetworthData(data.history.map((h: any) => ({
            date: h.month,
            "Net Worth": h.net_worth,
            orig: h
          })));
        }
      })
      .catch(console.error);
  }, [nwTimeframe]);

  useEffect(() => {
    const months = CASHFLOW_TF_MAP[cfTimeframe] || 6;
    fetch(`http://127.0.0.1:8000/api/reports/cash-flow?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.months) {
          setSpendingData(data.months.map((m: any) => {
            const monthStr = m?.month || '2026-01';
            const [yr, mo] = monthStr.split('-');
            return {
              day: `${MONTH_NAMES[parseInt(mo, 10) - 1] || 'Unk'} '${yr.slice(2)}`,
              Income: Math.abs(m.income || 0),
              Spending: Math.abs(m.spending || 0)
            };
          }));
        }
      })
      .catch(console.error);
  }, [cfTimeframe]);

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

  useEffect(() => {
    const now = new Date();
    const month = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    Promise.all([
      fetch(`http://127.0.0.1:8000/api/budgets/summary?month=${month}`).then(r => r.json()),
      fetch(`http://127.0.0.1:8000/api/budgets?month=${month}`).then(r => r.json()).catch(() => []),
    ]).then(([summary, budgetData]) => {
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

  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/recurring")
      .then(res => res.json())
      .then(data => setRecurringItems(data.recurring || []))
      .catch(console.error);
  }, []);

  const latestNw = networthData.length > 0 ? networthData[networthData.length - 1].orig : null;

  const budgetTotal = budgetSummary?.total_budgeted || 0;
  const budgetSpent = budgetSummary?.total_spent || 0;
  const budgetRemaining = budgetTotal - budgetSpent;
  const budgetPct = budgetTotal > 0 ? Math.min((budgetSpent / budgetTotal) * 100, 100) : 0;
  const now = new Date();
  const budgetMonth = `${MONTH_NAMES[now.getMonth()]} ${now.getFullYear()}`;
  const recurringTotal = recurringItems.reduce((s, r) => s + (r.expected_amount || r.last_amount || 0), 0);

  const formatCurrency = (n: number) => `$${Intl.NumberFormat('us').format(n)}`;

  return (
    <motion.div 
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 overflow-auto custom-scrollbar p-12 space-y-16"
    >
      
      {/* Top Snapshot Cards - Zero Slop, Stark Typography */}
      <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-3 gap-8">
        <motion.div 
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="cursor-pointer group"
          onClick={() => navigate('/accounts?filter=assets')}
        >
          <div className="flex items-center gap-2 mb-4">
            <span className="text-label">Cash Assets</span>
          </div>
          <p className="text-5xl font-bold tracking-tight text-slate-800 dark:text-slate-100 mb-1 text-numeric">
            ${latestNw?.banking_assets?.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}
          </p>
          <div className="h-0.5 w-full bg-slate-200 dark:bg-slate-800 mt-6 group-hover:bg-emerald-500 transition-colors duration-300"></div>
        </motion.div>
        
        <motion.div 
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="cursor-pointer group"
          onClick={() => navigate('/accounts?filter=liabilities')}
        >
          <div className="flex items-center gap-2 mb-4">
            <span className="text-label">Liabilities</span>
          </div>
          <p className="text-5xl font-bold tracking-tight text-loss mb-1 text-numeric">
            ${Math.abs(latestNw?.liabilities || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}
          </p>
          <div className="h-0.5 w-full bg-slate-200 dark:bg-slate-800 mt-6 group-hover:bg-red-500 transition-colors duration-300"></div>
        </motion.div>
        
        <motion.div 
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="cursor-pointer group"
          onClick={() => navigate('/transactions')}
        >
          <div className="flex items-center gap-2 mb-4">
            <span className="text-label">Monthly Net Flow</span>
          </div>
          <p className={`text-5xl font-bold tracking-tight mb-1 text-numeric ${(metrics?.net || 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
            ${metrics?.net?.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) || '0.00'}
          </p>
          <div className="h-0.5 w-full bg-slate-200 dark:bg-slate-800 mt-6 group-hover:bg-slate-400 dark:group-hover:bg-slate-500 transition-colors duration-300"></div>
        </motion.div>
      </motion.div>

      {/* Main Charts Section */}
      <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* Net Worth Chart */}
        <div className="flex flex-col h-[320px] overflow-hidden">
          <div className="flex items-end justify-between mb-4 pb-4 border-b border-slate-200 dark:border-slate-800 shrink-0">
            <div>
              <h3 className="font-sans text-3xl font-bold tracking-tight">${latestNw?.net_worth?.toLocaleString() || '0'}</h3>
              <p className="text-label mt-1">Net Worth</p>
            </div>
            <select 
              className="bg-transparent text-slate-500 text-xs outline-none cursor-pointer hover:text-[var(--color-gain)] transition-colors"
              value={nwTimeframe}
              onChange={(e) => setNwTimeframe(e.target.value)}
            >
              {Object.keys(TIMEFRAME_MAP).map(tf => (
                <option key={tf} value={tf} className="bg-white dark:bg-slate-900">{tf}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 w-full min-h-0">
            <AreaChart
              className="h-full"
              data={networthData}
              index="date"
              categories={['Net Worth']}
              colors={['emerald']}
              valueFormatter={formatCurrency}
              showLegend={false}
              showGridLines={false}
              showYAxis={true}
              yAxisWidth={60}
              curveType="monotone"
            />
          </div>
        </div>

        {/* Cash Flow Chart */}
        <div className="flex flex-col h-[320px] overflow-hidden">
          <div className="flex items-end justify-between mb-4 pb-4 border-b border-slate-200 dark:border-slate-800 shrink-0">
            <div>
              <h3 className="font-sans text-3xl font-bold tracking-tight">${Math.abs(metrics?.total_spending || 0).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</h3>
              <p className="text-label mt-1">Spent This Month</p>
            </div>
            <select 
              className="bg-transparent text-slate-500 text-xs outline-none cursor-pointer hover:text-[var(--color-gain)] transition-colors"
              value={cfTimeframe}
              onChange={(e) => setCfTimeframe(e.target.value)}
            >
              {Object.keys(CASHFLOW_TF_MAP).map(tf => (
                <option key={tf} value={tf} className="bg-white dark:bg-slate-900">{tf}</option>
              ))}
            </select>
          </div>
          <div className="flex-1 w-full min-h-0">
            <BarChart
              className="h-full"
              data={spendingData}
              index="day"
              categories={['Income', 'Spending']}
              colors={['emerald', 'rose']}
              valueFormatter={formatCurrency}
              showLegend={true}
              showGridLines={false}
              showYAxis={true}
              yAxisWidth={60}
            />
          </div>
        </div>
      </motion.div>

      <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-3 gap-12 pt-8">
        
        {/* Transactions Mini - Zero Slop List */}
        <div className="col-span-1 lg:col-span-2 flex flex-col">
          <div className="pb-4 mb-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
            <h3 className="text-label">Recent Transactions</h3>
            <button 
              className="text-label text-slate-400 hover:text-[var(--color-gain)] transition-colors"
              onClick={() => navigate('/transactions')}
            >View All</button>
          </div>
          <div className="flex-1 overflow-auto">
            {recentTransactions.map((tx: any) => (
              <motion.div 
                whileHover={{ x: 4, backgroundColor: 'rgba(16, 185, 129, 0.05)' }}
                key={tx.id} 
                className="py-4 border-b border-slate-100 dark:border-slate-800/50 flex items-center justify-between cursor-pointer group"
                onClick={() => navigate('/transactions', { state: { selectedTxId: tx.id } })}
              >
                <div className="flex items-center gap-6">
                  <div>
                    <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">{tx.description || tx.merchant}</h4>
                    <p className="text-label mt-1">
                      {tx.category} • {ACCOUNT_NAMES[tx.account_id] || tx.account_id}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className={`text-sm text-numeric ${(tx.signed_amount ?? tx.amount) < 0 ? 'text-slate-500' : 'text-gain'}`}>
                    {(tx.signed_amount ?? tx.amount) < 0 ? "" : "+"}${Math.abs(tx.signed_amount ?? tx.amount).toFixed(2)}
                  </span>
                  <span className="material-symbols-outlined text-slate-300 dark:text-slate-700 text-sm group-hover:text-emerald-500 transition-colors">arrow_forward</span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>

        {/* Right side stack - Minimal Budget & Recurring Lists */}
        <div className="col-span-1 flex flex-col gap-12">
          
          {/* Budget Widget */}
          <div 
            className="w-full cursor-pointer group"
            onClick={() => navigate('/budgets')}
          >
            <div className="pb-4 mb-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-label">Current Budget</h3>
              <span className="text-label text-slate-400">{budgetMonth}</span>
            </div>
            
            <div className="mb-6">
              <p className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100 mb-2">${budgetSpent.toLocaleString()}</p>
              <div className="w-full bg-slate-100 dark:bg-slate-800 h-1 overflow-hidden relative">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${budgetPct}%` }}
                  transition={{ duration: 1, ease: "easeOut" }}
                  className="bg-slate-900 dark:bg-slate-300 h-full absolute top-0 left-0" 
                />
              </div>
              <div className="flex justify-between mt-3 text-label">
                <span>Total: ${budgetTotal.toLocaleString()}</span>
                <span>{budgetRemaining < 0 ? '-' : ''}${Math.abs(budgetRemaining).toLocaleString()} rem</span>
              </div>
            </div>

            {budgetSummary?.categories && (
              <div className="space-y-4 mt-6">
                {budgetSummary.categories.slice(0, 4).map((cat: any) => {
                  const pct = cat.target_amount > 0 ? Math.min((cat.spent / cat.target_amount) * 100, 100) : 0;
                  return (
                    <motion.div whileHover={{ x: 2 }} key={cat.category} className="flex items-center gap-4">
                      <span className="text-sm font-bold text-slate-900 dark:text-slate-100 w-24 truncate">{cat.category}</span>
                      <div className="flex-1 bg-slate-100 dark:bg-slate-800 h-[2px] overflow-hidden">
                        <motion.div 
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 1, ease: "easeOut" }}
                          className={`h-full ${pct > 90 ? 'bg-[var(--color-loss)]' : 'bg-[var(--color-gain)]'}`} 
                        />
                      </div>
                      <span className="text-xs font-mono tracking-widest text-slate-500 w-10 text-right">{pct.toFixed(0)}%</span>
                    </motion.div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Recurring Widget */}
          <div className="flex-1 flex flex-col">
             <div className="pb-4 mb-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-label">Recurring</h3>
              <span className="text-label text-slate-400">${recurringTotal.toLocaleString(undefined, {minimumFractionDigits: 0})} /mo</span>
            </div>
            <div className="flex-1 overflow-auto">
              {recurringItems.slice(0, 5).map((item: any) => {
                return (
                  <motion.div 
                    whileHover={{ x: 4 }}
                    key={item.id} 
                    className="py-3 flex items-center justify-between cursor-pointer group" 
                    onClick={() => navigate(`/transactions?recurring=true&merchant=${encodeURIComponent(item.merchant)}`)}
                  >
                    <div>
                      <h4 className="font-bold text-sm text-slate-900 dark:text-slate-100">{item.merchant}</h4>
                      <p className="text-label text-slate-400 mt-1">{item.frequency}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-sm tracking-widest">${(item.expected_amount || item.last_amount || 0).toLocaleString(undefined, {minimumFractionDigits: 0})}</p>
                      <p className="text-label text-slate-400 mt-1">
                        {item.next_expected ? new Date(item.next_expected).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '—'}
                      </p>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </div>

        </div>
      </motion.div>

    </motion.div>
  );
}
