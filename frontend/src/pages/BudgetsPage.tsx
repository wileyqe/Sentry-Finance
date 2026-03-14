import { useState, useEffect, useCallback } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

const CATEGORY_META: Record<string, { icon: string; color: string }> = {
  "Housing":              { icon: "home",                  color: "oklch(0.52 0.11 290)" },
  "Food & Dining":       { icon: "restaurant",            color: "oklch(0.52 0.13 155)" },
  "Dining":              { icon: "restaurant",            color: "oklch(0.52 0.13 155)" },
  "Transportation":      { icon: "directions_car",        color: "oklch(0.52 0.12 240)" },
  "Utilities":           { icon: "bolt",                  color: "oklch(0.55 0.11 45)"  },
  "Entertainment":       { icon: "movie",                 color: "oklch(0.50 0.09 320)" },
  "Shopping":            { icon: "shopping_bag",          color: "oklch(0.52 0.12 240)" },
  "Groceries":           { icon: "local_grocery_store",   color: "oklch(0.50 0.08 90)"  },
  "Auto":                { icon: "directions_car",        color: "oklch(0.48 0.13 20)"  },
  "Home Improvement":    { icon: "construction",          color: "oklch(0.55 0.11 45)"  },
  "Medical":             { icon: "medical_services",      color: "oklch(0.48 0.13 20)"  },
  "Insurance":           { icon: "shield",                color: "oklch(0.52 0.10 185)" },
  "Travel":              { icon: "flight",                color: "oklch(0.52 0.11 290)" },
  "Mortgage":            { icon: "real_estate_agent",     color: "oklch(0.52 0.11 290)" },
  "ATM/Cash Withdrawal": { icon: "local_atm",             color: "oklch(0.50 0.08 90)"  },
  "Automotive":          { icon: "directions_car",        color: "oklch(0.48 0.13 20)"  },
};

const FALLBACK_COLORS = [
  "oklch(0.52 0.13 155)", "oklch(0.52 0.12 240)", "oklch(0.52 0.11 290)",
  "oklch(0.55 0.11 45)",  "oklch(0.48 0.13 20)",  "oklch(0.52 0.10 185)",
  "oklch(0.50 0.09 320)", "oklch(0.50 0.08 90)",
];

function getMeta(cat: string, idx: number) {
  return CATEGORY_META[cat] || { icon: "category", color: FALLBACK_COLORS[idx % FALLBACK_COLORS.length] };
}

export default function BudgetsPage() {
  const [currentMonth, setCurrentMonth] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  });
  const [budgets, setBudgets] = useState<any[]>([]);
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [showNewBudget, setShowNewBudget] = useState(false);
  const [newBudgetCat, setNewBudgetCat] = useState('');
  const [newBudgetAmt, setNewBudgetAmt] = useState('');

  const displayMonth = (() => {
    const [y, m] = currentMonth.split('-');
    const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    return `${months[parseInt(m) - 1]} ${y}`;
  })();

  const fetchData = useCallback(() => {
    fetch(`http://127.0.0.1:8000/api/budgets?month=${currentMonth}`)
      .then(r => r.json())
      .then(budgetData => {
        const cats = (budgetData.categories || [])
          .filter((b: any) => (b.target || b.target_amount || 0) > 0)
          .sort((a: any, b: any) => (b.actual || 0) - (a.actual || 0));
        setBudgets(cats);
      }).catch(console.error);
  }, [currentMonth]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const navigateMonth = (dir: number) => {
    const [y, m] = currentMonth.split('-').map(Number);
    const d = new Date(y, m - 1 + dir, 1);
    setCurrentMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  };

  const totalAssigned = budgets.reduce((s, b) => s + (b.target || b.target_amount || 0), 0);
  const totalSpent = budgets.reduce((s, b) => s + (b.actual || 0), 0);
  const remainingTotal = totalAssigned - totalSpent;
  const percentSpent = totalAssigned > 0 ? (totalSpent / totalAssigned) * 100 : 0;

  // Build chart data from budget categories
  const chartData = budgets.map((b, i) => ({
    name: b.category,
    value: b.actual || 0,
    color: getMeta(b.category, i).color,
  })).filter(d => d.value > 0);

  if (remainingTotal > 0) {
    chartData.push({ name: "Remaining", value: remainingTotal, color: "#e2e8f0" });
  }

  const daysInMonth = new Date(parseInt(currentMonth.split('-')[0]), parseInt(currentMonth.split('-')[1]), 0).getDate();
  const today = new Date();
  const currentDay = today.getFullYear() === parseInt(currentMonth.split('-')[0]) && today.getMonth() + 1 === parseInt(currentMonth.split('-')[1]) ? today.getDate() : daysInMonth;
  const daysLeft = Math.max(0, daysInMonth - currentDay);

  const handleSaveBudget = async (category: string, amount: number) => {
    await fetch(`http://127.0.0.1:8000/api/budgets/${encodeURIComponent(category)}?month=${currentMonth}&target=${amount}`, { method: 'PUT' });
    setEditingCategory(null);
    fetchData();
  };

  const handleDeleteBudget = async (category: string) => {
    await fetch(`http://127.0.0.1:8000/api/budgets/${encodeURIComponent(category)}?month=${currentMonth}`, { method: 'DELETE' });
    fetchData();
  };

  const handleNewBudget = async () => {
    const amt = parseFloat(newBudgetAmt);
    if (!newBudgetCat || isNaN(amt) || amt <= 0) return;
    await fetch(`http://127.0.0.1:8000/api/budgets/${encodeURIComponent(newBudgetCat)}?month=${currentMonth}&target=${amt}`, { method: 'PUT' });
    setShowNewBudget(false);
    setNewBudgetCat('');
    setNewBudgetAmt('');
    fetchData();
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar">
      
      {/* Top Header */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800/50 px-8 py-5 bg-white/50 dark:bg-background-dark/50 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-6">
          <button onClick={() => navigateMonth(-1)} className="text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors">
            <span className="material-symbols-outlined text-lg">chevron_left</span>
          </button>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white leading-none tracking-tight">{displayMonth}</h2>
          <button onClick={() => navigateMonth(1)} className="text-slate-400 hover:text-slate-700 dark:hover:text-white transition-colors">
            <span className="material-symbols-outlined text-lg">chevron_right</span>
          </button>
        </div>
        
        <div className="flex items-center gap-3">
          <button className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm font-semibold hover:border-slate-400 transition-colors">
             <span className="material-symbols-outlined text-sm">settings</span>
             Configure
          </button>
          <button 
            onClick={() => setShowNewBudget(true)}
            className="flex items-center gap-2 px-4 py-2 bg-[var(--color-gain)] text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            <span className="material-symbols-outlined text-sm">add</span>
            New Budget
          </button>
        </div>
      </div>

      <div className="p-8 flex flex-col lg:flex-row gap-8 flex-1">
        
        {/* Left Column: Summary */}
        <div className="w-full lg:w-[380px] flex-shrink-0 flex flex-col gap-6">
          
          <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-6">
            <div className="flex flex-col items-center justify-center text-center">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em] mb-3">Safe to spend</span>
              <span className={`text-5xl font-bold tracking-tight text-numeric ${remainingTotal >= 0 ? 'text-slate-900 dark:text-white' : 'text-loss'}`}>
                {remainingTotal < 0 ? '-' : ''}${Math.abs(remainingTotal).toLocaleString()}
              </span>
              {remainingTotal < 0 && <span className="text-xs mt-2 text-loss font-semibold">Over budget</span>}
              <span className="text-slate-500 text-sm mt-3">
                You have budgeted <strong className="text-slate-700 dark:text-slate-300">${totalAssigned.toLocaleString()}</strong> this month.
              </span>
            </div>

            <div className="mt-6 border-t border-slate-100 dark:border-slate-800 pt-5">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-slate-500 font-medium">Total Spent</span>
                <span className="font-bold text-slate-900 dark:text-white">${totalSpent.toLocaleString()}</span>
              </div>
              <div className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div 
                  className="h-full rounded-full transition-all duration-700"
                  style={{ width: `${Math.min(percentSpent, 100)}%`, background: percentSpent > 100 ? 'var(--color-loss)' : 'oklch(0.52 0.13 155)' }}
                />
              </div>
              <div className="flex justify-between text-xs mt-2">
                <span className={percentSpent > 100 ? 'text-red-500 font-semibold' : 'text-slate-400'}>
                  {percentSpent.toFixed(0)}% of budget
                </span>
                <span className="text-slate-400">{daysLeft} days left</span>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl p-6 flex-1">
            <h3 className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em] mb-4">Spending Breakdown</h3>
            <div className="relative w-full h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '12px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)' }}
                    itemStyle={{ color: '#fff', fontWeight: 'bold' }}
                    formatter={(value: any, name: any) => [`$${value.toLocaleString()}`, name]}
                  />
                  <Pie
                    data={chartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={65}
                    outerRadius={95}
                    paddingAngle={2}
                    dataKey="value"
                    stroke="none"
                  >
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} opacity={entry.name === 'Remaining' ? 0.15 : 1} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                 <span className="text-2xl font-bold text-slate-900 dark:text-white">${totalSpent.toLocaleString()}</span>
                 <span className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em]">Spent total</span>
              </div>
            </div>
          </div>

        </div>

        {/* Right Column: Categories */}
        <div className="flex-1 bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden flex flex-col">
          <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <h3 className="font-bold text-lg text-slate-900 dark:text-white">Categories</h3>
             <span className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.15em]">
                {budgets.length} Active Budgets
             </span>
          </div>

          <div className="p-4 flex-1 overflow-y-auto custom-scrollbar">
            <div className="space-y-1">
              {budgets.map((budget, idx) => {
                const target = budget.target || budget.target_amount || 0;
                const spent = budget.actual || 0;
                const isOver = spent > target;
                const percent = target > 0 ? (spent / target) * 100 : 0;
                const remaining = target - spent;
                const meta = getMeta(budget.category, idx);
                const isEditing = editingCategory === budget.category;
                
                return (
                  <div key={budget.category} className="group px-4 py-3.5 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                    <div className="flex items-center justify-between mb-2.5">
                      <div className="flex items-center gap-3">
                        <div className="size-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: meta.color + '15' }}>
                          <span className="material-symbols-outlined text-base" style={{ color: meta.color }}>{meta.icon}</span>
                        </div>
                        <div>
                          <h4 className="font-semibold text-sm text-slate-900 dark:text-white">{budget.category}</h4>
                          <p className="text-[11px] text-slate-400">{isOver ? 'Over budget' : `$${Math.abs(remaining).toLocaleString()} left`}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          {isEditing ? (
                            <div className="flex items-center gap-1">
                              <span className="text-xs text-slate-400">$</span>
                              <input
                                type="number"
                                autoFocus
                                className="w-20 px-2 py-1 text-sm font-semibold border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-800 outline-none focus:border-slate-500 text-right"
                                value={editValue}
                                onChange={(e) => setEditValue(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') handleSaveBudget(budget.category, parseFloat(editValue));
                                  if (e.key === 'Escape') setEditingCategory(null);
                                }}
                                onBlur={() => handleSaveBudget(budget.category, parseFloat(editValue))}
                              />
                            </div>
                          ) : (
                            <div 
                              className="font-semibold text-sm text-slate-900 dark:text-white cursor-pointer hover:text-blue-600 transition-colors"
                              onClick={() => { setEditingCategory(budget.category); setEditValue(String(target)); }}
                              title="Click to edit budget"
                            >
                              ${spent.toLocaleString()} <span className="text-slate-400 text-xs font-normal">/ ${target.toLocaleString()}</span>
                            </div>
                          )}
                        </div>
                        <button 
                          onClick={() => handleDeleteBudget(budget.category)}
                          className="opacity-0 group-hover:opacity-100 text-slate-300 hover:text-red-500 transition-all"
                          title="Delete budget"
                        >
                          <span className="material-symbols-outlined text-sm">close</span>
                        </button>
                      </div>
                    </div>
                    
                    {/* Progress Bar */}
                    <div className="w-full h-1.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                      <div 
                        className="h-full rounded-full transition-all duration-700"
                        style={{ 
                          width: `${Math.min(percent, 100)}%`, 
                          backgroundColor: isOver ? 'var(--color-loss)' : meta.color 
                        }}
                      />
                    </div>
                  </div>
                );
              })}
              {budgets.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                  <span className="material-symbols-outlined text-4xl mb-3">savings</span>
                  <p className="font-semibold">No budgets for {displayMonth}</p>
                  <p className="text-xs mt-1">Click "New Budget" to get started</p>
                </div>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* New Budget Dialog */}
      {showNewBudget && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowNewBudget(false)}>
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[380px] p-6 animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg">New Budget</h3>
              <button onClick={() => setShowNewBudget(false)} className="text-slate-400 hover:text-red-500 transition-colors">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Category</label>
                <input 
                  value={newBudgetCat} 
                  onChange={(e) => setNewBudgetCat(e.target.value)} 
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" 
                  placeholder="e.g. Groceries" 
                />
              </div>
              <div>
                <label className="block text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">Monthly Target</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">$</span>
                  <input 
                    type="number" 
                    value={newBudgetAmt} 
                    onChange={(e) => setNewBudgetAmt(e.target.value)} 
                    className="w-full pl-7 pr-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" 
                    placeholder="500" 
                  />
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button onClick={handleNewBudget} className="flex-1 px-4 py-2.5 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity">Create Budget</button>
              <button onClick={() => setShowNewBudget(false)} className="px-4 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
