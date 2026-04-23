import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { motion } from "framer-motion";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatCurrency } from "@/lib/formatCurrency";
import { formatMonthYearFull } from "@/lib/dateUtils";

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
  // Budgets are a household-only concept (V23) — this page renders the
  // same data regardless of which owner the ViewSelector is set to.
  // Edits affect the single household row.

  const [currentMonth, setCurrentMonth] = useSessionState('budgets:currentMonth', (() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  })());
  const [budgets, setBudgets] = useState<any[]>([]);
  const [editingCategory, setEditingCategory] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [showNewBudget, setShowNewBudget] = useState(false);
  const [newBudgetCat, setNewBudgetCat] = useState('');
  const [newBudgetAmt, setNewBudgetAmt] = useState('');

  // Drill-down support: dashboard budget category rows pass ?category=Foo
  // when they navigate here. We highlight + scroll to that row once.
  const [searchParams] = useSearchParams();
  const focusCategory = searchParams.get('category');
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    if (!focusCategory || budgets.length === 0) return;
    const el = rowRefs.current[focusCategory];
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }, [focusCategory, budgets]);

  const displayMonth = formatMonthYearFull(currentMonth);

  const fetchData = useCallback(() => {
    apiFetch<{ categories?: any[] }>(`/api/budgets?month=${currentMonth}`)
      .then(budgetData => {
        // Show every category that has either a target OR actual spending.
        // The previous filter (`target > 0`) silently hid over-budget rows
        // for categories the user hadn't yet budgeted — defeating the
        // "what should I do differently?" mission of the page.
        const cats = (budgetData.categories || [])
          .filter((b: any) =>
            (b.target || b.target_amount || 0) > 0 || (b.actual || 0) > 0
          )
          .sort((a: any, b: any) => (b.actual || 0) - (a.actual || 0));
        setBudgets(cats);
      }).catch((e) => {
        console.error(e);
        toast("Failed to load budgets", "error");
      });
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

  // Editorial hero derived values
  const dailyPace = currentDay > 0 ? totalSpent / currentDay : 0;
  const projectedTotal = dailyPace * daysInMonth;
  const overUnder = projectedTotal - totalAssigned;
  const overUnderIsOver = overUnder > 0;
  const trimPerDay = daysLeft > 0 ? Math.max(0, overUnder) / daysLeft : 0;
  const dailyAllowance = daysLeft > 0 ? Math.max(0, remainingTotal) / daysLeft : 0;

  const handleSaveBudget = async (category: string, amount: number) => {
    try {
      await apiFetch(`/api/budgets/${encodeURIComponent(category)}?month=${currentMonth}&target=${amount}`, { method: 'PUT' });
      toast(`${category} budget updated`, "success");
    } catch {
      toast(`Failed to update ${category} budget`, "error");
    }
    setEditingCategory(null);
    fetchData();
  };

  const handleDeleteBudget = async (category: string) => {
    if (!confirm(`Remove the ${category} budget for ${displayMonth}?`)) return;
    try {
      await apiFetch(`/api/budgets/${encodeURIComponent(category)}?month=${currentMonth}`, { method: 'DELETE' });
      toast(`${category} budget removed`, "success");
    } catch {
      toast(`Failed to delete ${category} budget`, "error");
    }
    fetchData();
  };

  const handleNewBudget = async () => {
    const amt = parseFloat(newBudgetAmt);
    if (!newBudgetCat || isNaN(amt) || amt <= 0) return;
    try {
      await apiFetch(`/api/budgets/${encodeURIComponent(newBudgetCat)}?month=${currentMonth}&target=${amt}`, { method: 'PUT' });
      toast(`${newBudgetCat} budget created`, "success");
    } catch {
      toast(`Failed to create budget`, "error");
    }
    setShowNewBudget(false);
    setNewBudgetCat('');
    setNewBudgetAmt('');
    fetchData();
  };

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar"
    >
      
      {/* Top Header */}
      <motion.div variants={itemVariants} className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 px-12 py-5 bg-white/50 dark:bg-background/50 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-6">
          <Button variant="ghost" size="icon" onClick={() => navigateMonth(-1)} aria-label="Previous month">
            <span className="material-symbols-outlined text-lg">chevron_left</span>
          </Button>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white leading-none tracking-tight">{displayMonth}</h2>
          <Button variant="ghost" size="icon" onClick={() => navigateMonth(1)} aria-label="Next month">
            <span className="material-symbols-outlined text-lg">chevron_right</span>
          </Button>
        </div>
        
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => toast("Budget configuration coming soon", "info")}
            className="gap-2 px-4 py-2 text-sm font-semibold"
          >
             <span className="material-symbols-outlined text-sm">settings</span>
             Configure
          </Button>
          <Button
            onClick={() => setShowNewBudget(true)}
            className="gap-2 px-4 py-2 text-sm font-semibold"
          >
            <span className="material-symbols-outlined text-sm">add</span>
            New Budget
          </Button>
        </div>
      </motion.div>

      <motion.div variants={itemVariants} className="p-12 flex flex-col lg:flex-row gap-8 flex-1">
        
        {/* Left Column: Summary */}
        <div className="w-full lg:w-[380px] flex-shrink-0 flex flex-col gap-6">
          
          {/* Safe to spend — editorial hero */}
          <Card className="p-6">
            <div className="relative pl-5">
              <span
                className={`absolute left-0 top-1 bottom-1 w-[3px] rounded-full ${remainingTotal >= 0 ? 'bg-[var(--color-gain)]' : 'bg-[var(--color-loss)]'}`}
                aria-hidden="true"
              />

              <p className="font-mono text-[10px] uppercase tracking-[0.25em] text-slate-500 dark:text-slate-400 mb-2">
                {formatMonthYearFull(currentMonth)} · Safe to spend
              </p>

              <h3 className={`font-serif text-[48px] leading-none font-semibold tracking-tight tabular-nums ${remainingTotal >= 0 ? 'text-slate-900 dark:text-white' : 'text-[var(--color-loss)]'}`}>
                {(() => {
                  const parts = formatCurrency(Math.abs(remainingTotal)).replace('$', '').split('.');
                  const negative = remainingTotal < 0;
                  return (
                    <>
                      {negative ? '−$' : '$'}{parts[0]}
                      <span className="text-[26px] text-slate-400 dark:text-slate-500 font-light">.{parts[1] || '00'}</span>
                    </>
                  );
                })()}
              </h3>

              {totalAssigned > 0 && (
                <p className="mt-3 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                  {remainingTotal >= 0 ? (
                    <>
                      Across <span className="font-semibold">{daysLeft} day{daysLeft === 1 ? '' : 's'} left</span>
                      {' '}— at your current pace of{' '}
                      <span className="font-semibold">{formatCurrency(dailyPace)}/day</span>
                      {overUnderIsOver ? (
                        <>
                          , you'll finish{' '}
                          <span className="font-semibold text-[var(--color-loss)]">{formatCurrency(Math.abs(overUnder))} over</span>
                          , trim{' '}
                          <span className="font-semibold">{formatCurrency(trimPerDay)}/day</span>
                          {' '}to land on target.
                        </>
                      ) : (
                        <>
                          , you'll finish{' '}
                          <span className="font-semibold text-[var(--color-gain)]">{formatCurrency(Math.abs(overUnder))} under</span>
                          {' '}budget.
                        </>
                      )}
                    </>
                  ) : (
                    <>
                      <span className="font-semibold text-[var(--color-loss)]">Over budget</span>
                      {' '}by {formatCurrency(Math.abs(remainingTotal))} with{' '}
                      <span className="font-semibold">{daysLeft} day{daysLeft === 1 ? '' : 's'}</span>
                      {' '}still to go this month.
                    </>
                  )}
                </p>
              )}

              <div className="mt-4 flex items-center gap-6 flex-wrap">
                <div className="flex flex-col">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">% used</span>
                  <span className={`font-serif text-base font-semibold tabular-nums ${percentSpent > 100 ? 'text-[var(--color-loss)]' : 'text-slate-900 dark:text-slate-100'}`}>
                    {percentSpent.toFixed(0)}%
                  </span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Days left</span>
                  <span className="font-serif text-base font-semibold tabular-nums text-slate-900 dark:text-slate-100">{daysLeft}</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Daily allowance</span>
                  <span className="font-serif text-base font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                    {formatCurrency(dailyAllowance)}
                  </span>
                </div>
              </div>

              <div className="mt-5 pt-4 border-t border-slate-100 dark:border-slate-800">
                <div className="flex justify-between text-xs mb-2">
                  <span className="text-slate-500">
                    <span className="font-semibold text-slate-700 dark:text-slate-300 tabular-nums">{formatCurrency(totalSpent)}</span>
                    {' '}spent of{' '}
                    <span className="font-semibold text-slate-700 dark:text-slate-300 tabular-nums">{formatCurrency(totalAssigned)}</span>
                  </span>
                </div>
                <div className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{
                      width: `${Math.min(percentSpent, 100)}%`,
                      backgroundColor: percentSpent >= 100 ? 'var(--color-loss)' : percentSpent >= 80 ? '#eab308' : 'var(--color-gain)',
                    }}
                  />
                </div>
              </div>
            </div>
          </Card>

          <Card className="p-6 flex-1">
            <h3 className="text-label mb-4">Spending Breakdown</h3>
            <div className="relative w-full h-[220px]">
              {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#0f172a', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', color: '#fff', fontSize: '12px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)' }}
                    itemStyle={{ color: '#fff', fontWeight: 'bold' }}
                    formatter={(value: any, name: any) => [formatCurrency(value), name]}
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
              ) : (
              <div className="flex items-center justify-center h-full text-slate-400">
                <div className="flex flex-col items-center gap-2">
                  <span className="material-symbols-outlined text-3xl">donut_small</span>
                  <p className="text-sm">No spending data yet</p>
                </div>
              </div>
              )}
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                 {chartData.length > 0 && (
                 <>
                 <span className="text-2xl font-bold text-slate-900 dark:text-white">{formatCurrency(totalSpent)}</span>
                 <span className="text-label">Spent total</span>
                 </>
                 )}
              </div>
            </div>
          </Card>

        </div>

        {/* Right Column: Categories */}
        <Card className="flex-1 overflow-hidden flex flex-col">
          <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
            <h3 className="font-bold text-lg text-slate-900 dark:text-white">Categories</h3>
             <span className="text-label">
                {budgets.length} Active Budgets
             </span>
          </div>

          <div className="p-4 flex-1 overflow-y-auto custom-scrollbar">
            <div className="space-y-1">
              {budgets.map((budget, idx) => {
                const target = budget.target || budget.target_amount || 0;
                const spent = budget.actual || 0;
                const remaining = budget.remaining || (target - spent);
                const percent = budget.pct_used || (target > 0 ? (spent / target) * 100 : 0);
                const status = budget.status || (percent >= 100 ? 'over' : percent >= 80 ? 'warning' : 'on_track');
                const isOver = status === 'over';
                const isWarning = status === 'warning';
                
                const meta = getMeta(budget.category, idx);
                const isEditing = editingCategory === budget.category;
                
                const isFocused = focusCategory === budget.category;
                return (
                  <div
                    key={budget.category}
                    ref={(el) => { rowRefs.current[budget.category] = el; }}
                    className={`group px-4 py-3.5 rounded-lg transition-colors ${
                      isFocused
                        ? 'bg-emerald-50 dark:bg-emerald-500/10 ring-2 ring-emerald-400'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-2.5">
                      <div className="flex items-center gap-3">
                        <div className="size-9 rounded-lg flex items-center justify-center" style={{ backgroundColor: meta.color + '15' }}>
                          <span className="material-symbols-outlined text-base" style={{ color: meta.color }}>{meta.icon}</span>
                        </div>
                        <div>
                          <h4 className="font-semibold text-sm text-slate-900 dark:text-white">{budget.category}</h4>
                          <p className={`text-[11px] ${isOver ? 'text-loss font-semibold' : isWarning ? 'text-yellow-600 dark:text-yellow-500 font-semibold' : 'text-slate-400'}`}>
                            {isOver ? 'Over budget' : `${formatCurrency(Math.abs(remaining))} left`}
                          </p>
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
                              className="font-semibold text-sm text-slate-900 dark:text-white cursor-pointer hover:text-[var(--color-gain)] transition-colors"
                              onClick={() => { setEditingCategory(budget.category); setEditValue(String(target)); }}
                              title="Click to edit budget"
                            >
                              {formatCurrency(spent)} <span className="text-slate-400 text-xs font-normal">/ {formatCurrency(target)}</span>
                            </div>
                          )}
                        </div>
                        <button 
                          onClick={() => handleDeleteBudget(budget.category)}
                          className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-red-500 transition-all scale-90 group-hover:scale-100"
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
                          backgroundColor: isOver ? 'var(--color-loss)' : isWarning ? '#eab308' : meta.color 
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
        </Card>

      </motion.div>

      {/* New Budget Dialog */}
      {showNewBudget && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowNewBudget(false)}>
          <Card
            className="w-[380px] p-6 animate-in fade-in zoom-in-95 duration-200"
            style={{ boxShadow: "var(--shadow-xl)" }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg">New Budget</h3>
              <button onClick={() => setShowNewBudget(false)} className="text-slate-400 hover:text-red-500 transition-colors">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-label mb-1">Category</label>
                <input 
                  value={newBudgetCat} 
                  onChange={(e) => setNewBudgetCat(e.target.value)} 
                  className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" 
                  placeholder="e.g. Groceries" 
                />
              </div>
              <div>
                <label className="block text-label mb-1">Monthly Target</label>
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
              <Button onClick={handleNewBudget} className="flex-1 px-4 py-2.5 text-sm font-semibold">Create Budget</Button>
              <Button variant="outline" onClick={() => setShowNewBudget(false)} className="px-4 py-2.5 text-sm font-semibold">Cancel</Button>
            </div>
          </Card>
        </div>
      )}
    </motion.div>
  );
}
