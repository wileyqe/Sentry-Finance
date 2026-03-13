import { useState } from 'react';

interface Account {
  id: string;
  name: string;
  type: string;
  balance: number;
  institution_id: string;
}

interface AccountsSummaryCardProps {
  accounts: Account[];
}

export default function AccountsSummaryCard({ accounts }: AccountsSummaryCardProps) {
  const [viewMode, setViewMode] = useState<'totals' | 'percent'>('totals');

  // Asset categorization
  const cashAccounts = accounts.filter(a => ['checking', 'savings'].includes(a.type) && a.balance >= 0);
  const investmentAccounts = accounts.filter(a => ['investment', 'retirement'].includes(a.type) && a.balance >= 0);
  const realEstateAccounts = accounts.filter(a => ['real_estate', 'property'].includes(a.type) && a.balance >= 0);
  
  // Any other positive balance accounts go to "Other Assets" or are grouped into Cash/Investments. 
  // Let's strictly follow the design: Real Estate, Investments, Cash
  
  const cashTotal = cashAccounts.reduce((acc, a) => acc + (a.balance || 0), 0);
  const investmentsTotal = investmentAccounts.reduce((acc, a) => acc + (a.balance || 0), 0);
  const realEstateTotal = realEstateAccounts.reduce((acc, a) => acc + (a.balance || 0), 0);
  
  const totalAssets = cashTotal + investmentsTotal + realEstateTotal;

  // Liability categorization
  const creditCardAccounts = accounts.filter(a => ['credit_card'].includes(a.type) && a.balance < 0);
  const bnplAccounts = accounts.filter(a => ['bnpl'].includes(a.type) && a.balance < 0);
  
  const creditCardsTotal = Math.abs(creditCardAccounts.reduce((acc, a) => acc + (a.balance || 0), 0));
  const bnplTotal = Math.abs(bnplAccounts.reduce((acc, a) => acc + (a.balance || 0), 0));
  
  const handledLiabIds = new Set([...creditCardAccounts, ...bnplAccounts].map(a => a.id));
  const otherLiabAccounts = accounts.filter(a => a.balance < 0 && !handledLiabIds.has(a.id));
  const loansTotal = Math.abs(otherLiabAccounts.reduce((acc, a) => acc + (a.balance || 0), 0));

  const totalLiabilities = creditCardsTotal + bnplTotal + loansTotal;

  // Formatting helpers
  const formatValue = (val: number, parentTotal: number) => {
    if (viewMode === 'percent') {
      if (parentTotal === 0) return '0%';
      return `${((val / parentTotal) * 100).toFixed(1)}%`;
    }
    return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const getWidth = (val: number, parentTotal: number) => {
    if (parentTotal === 0) return 0;
    return (val / parentTotal) * 100;
  };

  const downloadCSV = () => {
    const header = "Institution,Account Name,Type,Balance\n";
    const rows = accounts.map(a => `${a.institution_id},"${a.name}",${a.type},${a.balance}`).join("\n");
    const csv = header + rows;
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'accounts_summary.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-white dark:bg-background-dark/50 border border-slate-200 dark:border-primary/10 rounded-xl overflow-hidden shadow-sm flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 flex items-center justify-between border-b border-slate-200 dark:border-primary/10">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">Summary</h2>
          <span className="material-symbols-outlined text-slate-400 text-lg">auto_awesome</span>
        </div>
        
        <div className="flex items-center bg-slate-100 dark:bg-primary/5 rounded-full p-1 border border-slate-200 dark:border-primary/10">
          <button 
            onClick={() => setViewMode('totals')}
            className={`px-3 py-1 rounded-full text-xs font-bold transition-colors ${viewMode === 'totals' ? 'bg-white dark:bg-primary/20 text-slate-900 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
          >
            Totals
          </button>
          <button 
            onClick={() => setViewMode('percent')}
            className={`px-3 py-1 rounded-full text-xs font-bold transition-colors ${viewMode === 'percent' ? 'bg-white dark:bg-primary/20 text-slate-900 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
          >
            Percent
          </button>
        </div>
      </div>

      <div className="p-6 flex flex-col gap-8 flex-1">
        
        {/* Assets Section */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-slate-900 dark:text-white">Assets</h3>
            <span className="text-slate-500 font-medium">
              ${totalAssets.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          
          {/* Stacked Bar for Assets */}
          <div className="flex h-3 rounded-full overflow-hidden mb-5 gap-1">
            {totalAssets > 0 ? (
              <>
                <div style={{ width: `${getWidth(realEstateTotal, totalAssets)}%` }} className="bg-purple-500 rounded-l-full" />
                <div style={{ width: `${getWidth(investmentsTotal, totalAssets)}%` }} className="bg-sky-400" />
                <div style={{ width: `${getWidth(cashTotal, totalAssets)}%` }} className="bg-emerald-500 rounded-r-full" />
              </>
            ) : (
              <div className="w-full bg-slate-100 dark:bg-primary/5 rounded-full" />
            )}
          </div>
          
          {/* Legend for Assets */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-purple-500" />
                <span>Real Estate</span>
              </div>
              <span className="font-medium">{formatValue(realEstateTotal, totalAssets)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-sky-400" />
                <span>Investments</span>
              </div>
              <span className="font-medium">{formatValue(investmentsTotal, totalAssets)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-emerald-500" />
                <span>Cash</span>
              </div>
              <span className="font-medium">{formatValue(cashTotal, totalAssets)}</span>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="h-px w-full bg-slate-100 dark:bg-primary/5" />

        {/* Liabilities Section */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-bold text-slate-900 dark:text-white">Liabilities</h3>
            <span className="text-slate-500 font-medium">
              ${totalLiabilities.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          
          {/* Bar for Liabilities */}
          <div className="flex h-3 rounded-full overflow-hidden mb-5 gap-1">
            {totalLiabilities > 0 ? (
              <>
                <div style={{ width: `${getWidth(creditCardsTotal, totalLiabilities)}%` }} className="bg-rose-500 rounded-l-full" />
                <div style={{ width: `${getWidth(bnplTotal, totalLiabilities)}%` }} className="bg-orange-400" />
                <div style={{ width: `${getWidth(loansTotal, totalLiabilities)}%` }} className="bg-amber-400 rounded-r-full" />
              </>
            ) : (
              <div className="w-full bg-slate-100 dark:bg-primary/5 rounded-full" />
            )}
          </div>
          
          {/* Legend for Liabilities */}
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-rose-500" />
                <span>Credit Cards</span>
              </div>
              <span className="font-medium">{formatValue(creditCardsTotal, totalLiabilities)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-orange-400" />
                <span>BNPL Contracts</span>
              </div>
              <span className="font-medium">{formatValue(bnplTotal, totalLiabilities)}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
                <div className="size-2 rounded-full bg-amber-400" />
                <span>Loans</span>
              </div>
              <span className="font-medium">{formatValue(loansTotal, totalLiabilities)}</span>
            </div>
          </div>
        </div>

      </div>

      {/* Footer / Actions */}
      <div className="px-6 py-4 border-t border-slate-200 dark:border-primary/10 text-center">
        <button 
          onClick={downloadCSV}
          className="text-primary font-bold text-sm tracking-wide hover:underline transition-all"
        >
          Download CSV
        </button>
      </div>
    </div>
  );
}
