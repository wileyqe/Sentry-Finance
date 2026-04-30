import { useState } from 'react';
import { formatCurrency } from "@/lib/formatCurrency";

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

const testIdPart = (value: unknown) =>
  String(value ?? "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "unknown";

export default function AccountsSummaryCard({ accounts }: AccountsSummaryCardProps) {
  const [viewMode, setViewMode] = useState<'totals' | 'percent'>('totals');

  // ── Asset buckets ────────────────────────────────────────────────────────
  const ASSET_BUCKETS = [
    {
      key: 'real_estate',
      label: 'Real Estate',
      color: 'var(--chart-c4)',
      accounts: accounts.filter(a => ['real_estate', 'property'].includes(a.type) && a.balance >= 0),
    },
    {
      key: 'vehicles',
      label: 'Vehicles',
      color: 'var(--chart-c7)',
      accounts: accounts.filter(a => a.type === 'vehicle' && a.balance >= 0),
    },
    {
      key: 'investments',
      label: 'Investments',
      color: 'var(--chart-c2)',
      accounts: accounts.filter(a => ['investment', 'retirement'].includes(a.type) && a.balance >= 0),
    },
    {
      key: 'cash',
      label: 'Cash',
      color: 'var(--chart-c1)',
      accounts: accounts.filter(a => ['checking', 'savings'].includes(a.type) && a.balance >= 0),
    },
  ].filter(b => b.accounts.length > 0);  // ← only show if populated

  const bucketTotal = (b: typeof ASSET_BUCKETS[0]) =>
    b.accounts.reduce((s, a) => s + (a.balance || 0), 0);

  const totalAssets = ASSET_BUCKETS.reduce((s, b) => s + bucketTotal(b), 0);

  // ── Liability buckets ────────────────────────────────────────────────────
  // Filter by TYPE only — never by sign.  An older defensive `balance < 0`
  // filter masked sign-convention bugs in the data layer (e.g. a credit
  // card seeded with positive balances would silently disappear from the
  // sidebar instead of surfacing as a "Credit cards: +$X" red flag).
  // Sign correctness is now enforced by the seeder integrity assertion
  // (Phase A) and by the canonical net-worth pattern (Phase B).
  const creditCardAccounts = accounts.filter(a => a.type === 'credit_card');
  const bnplAccounts       = accounts.filter(a => a.type === 'bnpl');
  const loanAccounts       = accounts.filter(a => ['loan', 'mortgage'].includes(a.type));

  const creditCardsTotal = Math.abs(creditCardAccounts.reduce((s, a) => s + (a.balance || 0), 0));
  const bnplTotal        = Math.abs(bnplAccounts.reduce((s, a) => s + (a.balance || 0), 0));
  const loansTotal       = Math.abs(loanAccounts.reduce((s, a) => s + (a.balance || 0), 0));

  const LIAB_BUCKETS = [
    { key: 'credit',  label: 'Credit Cards',   total: creditCardsTotal, color: 'var(--color-loss)' },
    { key: 'bnpl',    label: 'BNPL',            total: bnplTotal,        color: 'var(--chart-c3)'   },
    { key: 'loans',   label: 'Loans',           total: loansTotal,       color: 'var(--chart-c5)'   },
  ].filter(b => b.total > 0);  // ← only show if non-zero

  const totalLiabilities = LIAB_BUCKETS.reduce((s, b) => s + b.total, 0);

  // ── Formatting ───────────────────────────────────────────────────────────
  const fmtDollar = (v: number) => formatCurrency(v);

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
        : <div className="flex-1 bg-surface-raised rounded-full" />
      }
    </div>
  );

  // ── Row helper ────────────────────────────────────────────────────────────
  const LegendRow = ({ color, label, value, parent }: {
    color: string; label: string; value: number; parent: number;
  }) => {
    const slug = testIdPart(label);
    return (
    <div className="flex items-center justify-between text-sm">
      <div className="flex items-center gap-2 text-muted-foreground">
        <div className="size-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
        <span>{label}</span>
      </div>
      <span className="font-medium text-numeric text-foreground" data-testid={`accounts-summary-bucket-${slug}`}>
        {fmtVal(value, parent)}
      </span>
    </div>
    );
  };

  return (
    <div className="card-l1 overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-6 py-5 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-foreground">Summary</h2>
          <span className="material-symbols-outlined text-muted-foreground text-lg">auto_awesome</span>
        </div>
        <div className="flex items-center bg-surface-raised dark:bg-primary/5 rounded-full p-1 border border-border">
          {(['totals', 'percent'] as const).map(mode => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              data-testid={`accounts-summary-mode-${mode}`}
              className={`px-3 py-1 rounded-full text-xs font-bold capitalize transition-colors ${
                viewMode === mode
                  ? 'bg-card dark:bg-primary/20 text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {mode}
            </button>
          ))}
        </div>
      </div>

      <div className="p-6 flex flex-col gap-7 flex-1">

        {/* ── Assets ── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="text-label">Assets</span>
            <span className="font-bold text-foreground text-numeric" data-testid="accounts-summary-assets-total">
              {fmtDollar(totalAssets)}
            </span>
          </div>
          <StackedBar
            buckets={ASSET_BUCKETS.map(b => ({ color: b.color, value: bucketTotal(b) }))}
            total={totalAssets}
          />
          {ASSET_BUCKETS.length > 0 && (
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
          )}
          {ASSET_BUCKETS.length === 0 && (
            <p className="text-xs text-muted-foreground" data-testid="accounts-summary-buckets-empty">No asset buckets</p>
          )}
        </div>

        <div className="h-px w-full bg-border" />

        {/* ── Liabilities ── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <span className="text-label">Liabilities</span>
            <span className="font-bold text-loss text-numeric" data-testid="accounts-summary-liabilities-total">
              {fmtDollar(totalLiabilities)}
            </span>
          </div>
          <StackedBar
            buckets={LIAB_BUCKETS.map(b => ({ color: b.color, value: b.total }))}
            total={totalLiabilities}
          />
          {LIAB_BUCKETS.length > 0 && (
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
          )}
          {LIAB_BUCKETS.length === 0 && (
            <p className="text-xs text-muted-foreground" data-testid="accounts-summary-liability-buckets-empty">No liability buckets</p>
          )}
        </div>

      </div>

      <div className="px-6 py-4 border-t border-border text-center">
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
