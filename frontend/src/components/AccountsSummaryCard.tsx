import { useState } from 'react';

interface Account {
  id: string;
  name: string;
  type: string;
  balance: number;
  institution_id: string;
  purchase_price?: number;
}

interface AccountsSummaryCardProps {
  accounts: Account[];
}

export default function AccountsSummaryCard({ accounts }: AccountsSummaryCardProps) {
  const [viewMode, setViewMode] = useState<'totals' | 'percent'>('totals');

  // ── Asset buckets ────────────────────────────────────────────────────────
  const ASSET_BUCKETS = [
    {
      key: 'real_estate',
      label: 'Real Estate',
      color: 'oklch(0.50 0.08 300)',   // --chart-c5 purple-ish
      accounts: accounts.filter(a => ['real_estate', 'property'].includes(a.type) && a.balance >= 0),
    },
    {
      key: 'investments',
      label: 'Investments',
      color: 'oklch(0.52 0.12 240)',   // --chart-c2 blue
      accounts: accounts.filter(a => ['investment', 'retirement'].includes(a.type) && a.balance >= 0),
    },
    {
      key: 'cash',
      label: 'Cash',
      color: 'oklch(0.52 0.13 155)',   // --chart-c1 emerald (--color-gain)
      accounts: accounts.filter(a => ['checking', 'savings'].includes(a.type) && a.balance >= 0),
    },
  ].filter(b => b.accounts.length > 0);  // ← only show if populated

  const bucketTotal = (b: typeof ASSET_BUCKETS[0]) =>
    b.accounts.reduce((s, a) => s + (a.balance || 0), 0);

  const totalAssets = ASSET_BUCKETS.reduce((s, b) => s + bucketTotal(b), 0);

  // ── Liability buckets ────────────────────────────────────────────────────
  const creditCardAccounts = accounts.filter(a => a.type === 'credit_card' && a.balance < 0);
  const bnplAccounts       = accounts.filter(a => a.type === 'bnpl'         && a.balance < 0);
  const loanAccounts       = accounts.filter(a => ['loan'].includes(a.type) && a.balance < 0);

  const creditCardsTotal = Math.abs(creditCardAccounts.reduce((s, a) => s + a.balance, 0));
  const bnplTotal        = Math.abs(bnplAccounts.reduce((s, a) => s + a.balance, 0));
  const loansTotal       = Math.abs(loanAccounts.reduce((s, a) => s + a.balance, 0));

  const LIAB_BUCKETS = [
    { key: 'credit',  label: 'Credit Cards',   total: creditCardsTotal, color: 'oklch(0.48 0.13 20)'  },  // --color-loss
    { key: 'bnpl',    label: 'BNPL',            total: bnplTotal,        color: 'oklch(0.50 0.10 40)'  },  // --chart-c4 amber
    { key: 'loans',   label: 'Loans',           total: loansTotal,       color: 'oklch(0.50 0.08 60)'  },  // --chart-c3 gold
  ].filter(b => b.total > 0);  // ← only show if non-zero

  const totalLiabilities = LIAB_BUCKETS.reduce((s, b) => s + b.total, 0);

  // ── Formatting ───────────────────────────────────────────────────────────
  const fmtDollar = (v: number) =>
    `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const fmtVal = (val: number, parent: number) =>
    viewMode === 'percent'
      ? (parent === 0 ? '0%' : `${((val / parent) * 100).toFixed(1)}%`)
      : fmtDollar(val);

  const pct = (val: number, parent: number) =>
    parent === 0 ? 0 : (val / parent) * 100;

  // ── CSV download ─────────────────────────────────────────────────────────
  const downloadCSV = () => {
    const rows = accounts.map(a =>
      `${a.institution_id},"${a.name}",${a.type},${a.balance}`
    );
    const csv = 'Institution,Account Name,Type,Balance\n' + rows.join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const el  = document.createElement('a');
    el.href = url; el.download = 'accounts_summary.csv';
    document.body.appendChild(el); el.click();
    document.body.removeChild(el); URL.revokeObjectURL(url);
  };

  // ── Stacked bar helper ────────────────────────────────────────────────────
  const StackedBar = ({ buckets, total }: {
    buckets: Array<{ color: string; value: number }>;
    total: number;
  }) => (
    <div className="flex h-2.5 rounded-full overflow-hidden gap-0.5 mb-4">
      {total > 0
        ? buckets.map((b, i) => (
            <div
              key={i}
              style={{ width: `${pct(b.value, total)}%`, backgroundColor: b.color }}
              className={`${i === 0 ? 'rounded-l-full' : ''} ${i === buckets.length - 1 ? 'rounded-r-full' : ''}`}
            />
          ))
        : <div className="flex-1 bg-slate-100 dark:bg-slate-800 rounded-full" />
      }
    </div>
  );

  // ── Row helper ────────────────────────────────────────────────────────────
  const LegendRow = ({ color, label, value, parent }: {
    color: string; label: string; value: number; parent: number;
  }) => (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
        <div className="size-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
        <span>{label}</span>
      </div>
      <span className="font-medium text-numeric text-slate-800 dark:text-slate-100">
        {fmtVal(value, parent)}
      </span>
    </div>
  );

  return (
    <div className="bg-white dark:bg-background-dark/50 border border-slate-200 dark:border-primary/10 rounded-xl overflow-hidden shadow-sm flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 flex items-center justify-between border-b border-slate-200 dark:border-primary/10">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">Summary</h2>
          <span className="material-symbols-outlined text-slate-400 text-lg">auto_awesome</span>
        </div>
        <div className="flex items-center bg-slate-100 dark:bg-primary/5 rounded-full p-1 border border-slate-200 dark:border-primary/10">
          {(['totals', 'percent'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`px-3 py-1 rounded-full text-xs font-bold capitalize transition-colors ${
                viewMode === mode
                  ? 'bg-white dark:bg-primary/20 text-slate-900 dark:text-white shadow-sm'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      <div className="p-6 flex flex-col gap-7 flex-1">

        {/* ── Assets ── */}
        {ASSET_BUCKETS.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-label">Assets</span>
              <span className="font-bold text-slate-900 dark:text-white text-numeric">
                {fmtDollar(totalAssets)}
              </span>
            </div>
            <StackedBar
              buckets={ASSET_BUCKETS.map(b => ({ color: b.color, value: bucketTotal(b) }))}
              total={totalAssets}
            />
            <div className="flex flex-col gap-2.5">
              {ASSET_BUCKETS.map(b => (
                <LegendRow
                  key={b.key}
                  color={b.color}
                  label={b.label}
                  value={bucketTotal(b)}
                  parent={totalAssets}
                />
              ))}
            </div>
          </div>
        )}

        {/* Divider — only if both sections present */}
        {ASSET_BUCKETS.length > 0 && LIAB_BUCKETS.length > 0 && (
          <div className="h-px w-full bg-slate-100 dark:bg-slate-800" />
        )}

        {/* ── Liabilities ── */}
        {LIAB_BUCKETS.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-label">Liabilities</span>
              <span className="font-bold text-loss text-numeric">
                {fmtDollar(totalLiabilities)}
              </span>
            </div>
            <StackedBar
              buckets={LIAB_BUCKETS.map(b => ({ color: b.color, value: b.total }))}
              total={totalLiabilities}
            />
            <div className="flex flex-col gap-2.5">
              {LIAB_BUCKETS.map(b => (
                <LegendRow
                  key={b.key}
                  color={b.color}
                  label={b.label}
                  value={b.total}
                  parent={totalLiabilities}
                />
              ))}
            </div>
          </div>
        )}

      </div>

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
