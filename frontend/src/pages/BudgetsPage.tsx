import { useState } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";

const budgets = [
  { id: 1, category: "Housing", assigned: 2500, spent: 2500, icon: "home", color: "#8b5cf6" },
  { id: 2, category: "Food & Dining", assigned: 800, spent: 650, icon: "restaurant", color: "#11d483" },
  { id: 3, category: "Transportation", assigned: 400, spent: 220, icon: "directions_car", color: "#0ea5e9" },
  { id: 4, category: "Utilities", assigned: 350, spent: 310, icon: "bolt", color: "#f97316" },
  { id: 5, category: "Entertainment", assigned: 200, spent: 280, icon: "movie", color: "#ec4899" }, // over budget
  { id: 6, category: "Shopping", assigned: 300, spent: 100, icon: "shopping_bag", color: "#64748b" },
];

export default function BudgetsPage() {
  const [activeTab] = useState("March 2026");

  const totalAssigned = budgets.reduce((acc, curr) => acc + curr.assigned, 0);
  const totalSpent = budgets.reduce((acc, curr) => acc + curr.spent, 0);
  const remainingTotal = totalAssigned - totalSpent;
  const percentSpent = (totalSpent / totalAssigned) * 100;

  const chartData = budgets.map(b => ({
    name: b.category,
    value: b.spent,
    color: b.color
  }));

  // Add remaining slice to make the pie represent total assigned if not over budget
  if (remainingTotal > 0) {
    chartData.push({
      name: "Remaining",
      value: remainingTotal,
      color: "#e2e8f0" // Slate-200 for remaining or we could use transparency
    });
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar">
      
      {/* Top Header & Tabs */}
      <div className="flex items-center justify-between border-b border-slate-200 dark:border-primary/10 px-8 py-5 bg-white/30 dark:bg-background-dark/30 backdrop-blur-md sticky top-0 z-10">
        <div className="flex items-center gap-6">
          <button className="text-slate-400 hover:text-primary transition-colors">
            <span className="material-symbols-outlined text-lg">chevron_left</span>
          </button>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white leading-none">{activeTab}</h2>
          <button className="text-slate-400 hover:text-primary transition-colors">
            <span className="material-symbols-outlined text-lg">chevron_right</span>
          </button>
        </div>
        
        <div className="flex items-center gap-4">
          <button className="flex items-center gap-2 px-4 py-2 bg-white dark:bg-background-dark border border-slate-200 dark:border-primary/20 rounded-lg text-sm font-bold shadow-sm hover:border-primary/50 transition-colors">
             <span className="material-symbols-outlined text-sm">settings</span>
             Configure
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-primary/20 text-primary border border-primary/30 rounded-lg text-sm font-bold shadow-sm hover:bg-primary hover:text-white transition-all duration-300">
            <span className="material-symbols-outlined text-sm">add</span>
            New Budget
          </button>
        </div>
      </div>

      <div className="p-8 flex flex-col lg:flex-row gap-8 flex-1">
        
        {/* Left Column: Summary */}
        <div className="w-full lg:w-1/3 flex flex-col gap-6">
          
          <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm">
            <div className="flex flex-col items-center justify-center text-center">
              <span className="text-sm font-bold text-slate-500 uppercase tracking-widest mb-2">Safe to spend</span>
              <span className={`text-5xl font-extrabold tracking-tight ${remainingTotal >= 0 ? 'text-primary' : 'text-red-500'}`}>
                ${remainingTotal >= 0 ? remainingTotal.toLocaleString() : (remainingTotal * -1).toLocaleString()}
                {remainingTotal < 0 && <span className="text-lg ml-1 text-red-500 font-bold block mt-1">Over budget</span>}
              </span>
              <span className="text-slate-500 font-medium mt-4">
                You have budgeted <strong>${totalAssigned.toLocaleString()}</strong> this month.
              </span>
            </div>

            <div className="mt-8 border-t border-slate-100 dark:border-primary/10 pt-6">
              <div className="flex justify-between text-sm mb-2 font-bold">
                <span className="text-slate-500">Total Spent</span>
                <span className="text-slate-900 dark:text-white">${totalSpent.toLocaleString()}</span>
              </div>
              <div className="w-full h-3 bg-slate-100 dark:bg-primary/5 rounded-full overflow-hidden">
                <div 
                  className={`h-full rounded-full transition-all duration-500 ${percentSpent > 100 ? 'bg-red-500' : 'bg-primary'}`} 
                  style={{ width: `${Math.min(percentSpent, 100)}%` }}
                />
              </div>
              <div className="flex justify-between text-xs mt-2 font-semibold">
                <span className={percentSpent > 100 ? 'text-red-500' : 'text-slate-400'}>
                  {percentSpent.toFixed(0)}% of budget
                </span>
                <span className="text-slate-400">18 days left</span>
              </div>
            </div>
          </div>

          <div className="bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl p-6 shadow-sm flex-1">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-bold uppercase tracking-widest text-xs text-slate-500">Spending Breakdown</h3>
            </div>
            <div className="relative w-full h-[250px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px', color: '#fff', fontSize: '12px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)', zIndex: 1000 }}
                    itemStyle={{ color: '#fff', fontWeight: 'bold' }}
                    formatter={(value: any, name: any) => [`$${value.toLocaleString()}`, name]}
                  />
                  <Pie
                    data={chartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={100}
                    paddingAngle={2}
                    dataKey="value"
                    stroke="none"
                  >
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} opacity={entry.name === 'Remaining' ? 0.3 : 1} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                 <span className="text-2xl font-bold text-slate-900 dark:text-white">${totalSpent.toLocaleString()}</span>
                 <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Spent total</span>
              </div>
            </div>
          </div>

        </div>

        {/* Right Column: Individual Budgets */}
        <div className="w-full lg:w-2/3 bg-white dark:bg-background-dark/30 border border-slate-200 dark:border-primary/10 rounded-xl shadow-sm overflow-hidden flex flex-col">
          <div className="p-6 border-b border-slate-200 dark:border-primary/10 flex items-center justify-between bg-slate-50/30 dark:bg-background-dark/50">
            <h3 className="font-bold text-xl">Categories</h3>
             <span className="bg-slate-100 dark:bg-primary/10 text-slate-600 dark:text-primary text-[10px] px-3 py-1 rounded-full font-bold uppercase tracking-wider">
                {budgets.length} Active Budgets
             </span>
          </div>

          <div className="p-4 flex-1 overflow-y-auto custom-scrollbar">
            <div className="space-y-4">
              {budgets.map((budget) => {
                const isOver = budget.spent > budget.assigned;
                const percent = (budget.spent / budget.assigned) * 100;
                const remaining = budget.assigned - budget.spent;
                
                return (
                  <div key={budget.id} className="group p-4 rounded-xl border border-slate-100 dark:border-primary/5 hover:bg-slate-50 dark:hover:bg-primary/5 hover:border-slate-200 dark:hover:border-primary/20 transition-all cursor-pointer">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-4">
                        <div className="size-10 rounded-lg flex items-center justify-center text-white shadow-sm" style={{ backgroundColor: budget.color }}>
                          <span className="material-symbols-outlined text-lg">{budget.icon}</span>
                        </div>
                        <div>
                          <h4 className="font-bold text-slate-900 dark:text-slate-100">{budget.category}</h4>
                          <p className="text-xs font-medium text-slate-500">{isOver ? 'Over budget' : `${remaining.toLocaleString()} left`}</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-bold text-slate-900 dark:text-white">
                          ${budget.spent} <span className="text-slate-400 text-sm font-medium">/ ${budget.assigned}</span>
                        </div>
                      </div>
                    </div>
                    
                    {/* Progress Bar */}
                    <div className="w-full h-2.5 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden relative">
                      <div 
                        className={`absolute top-0 left-0 h-full rounded-full transition-all duration-500 ${isOver ? 'bg-red-500' : ''}`}
                        style={{ width: `${Math.min(percent, 100)}%`, backgroundColor: !isOver ? budget.color : undefined }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
