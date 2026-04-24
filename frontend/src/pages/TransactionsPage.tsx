import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useLocation, useSearchParams, useNavigate } from "react-router-dom";
import { useSessionState } from "@/hooks/useSessionState";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { PageShell } from "@/components/ui/page-shell";
import { TransactionLogo } from "@/components/ui/TransactionLogo";

import { useAccounts } from "@/lib/accounts";
import { useView } from "@/context/ViewContext";
import { toast } from "@/lib/toast";
import { apiFetch } from "@/lib/api";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR } from "@/lib/dateUtils";
import SyntheticBadge from "@/components/ui/SyntheticBadge";

function formatDate(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${MONTH_ABBR[parseInt(m, 10) - 1]} ${parseInt(d, 10)}, ${y}`;
}

const PAGE_SIZE = 25;

// Per-category color mapping.  Both abstract names ("Dining") AND the
// real category strings emitted by dal/categorization.py
// ("Restaurants/Dining") are listed so the chip lights up regardless of
// which taxonomy a row carries.  Without these aliases the live data
// rendered every chip as gray "Uncategorized".
const _GREEN  = { bg: 'bg-[oklch(0.52_0.13_155/0.18)]', text: 'text-[oklch(0.34_0.13_155)]',  border: 'border-[oklch(0.52_0.13_155/0.40)]' };
const _TEAL   = { bg: 'bg-[oklch(0.52_0.10_185/0.18)]', text: 'text-[oklch(0.32_0.10_185)]',  border: 'border-[oklch(0.52_0.10_185/0.40)]' };
const _OLIVE  = { bg: 'bg-[oklch(0.50_0.09_90/0.20)]',  text: 'text-[oklch(0.33_0.10_90)]',   border: 'border-[oklch(0.50_0.09_90/0.40)]'  };
const _ORANGE = { bg: 'bg-[oklch(0.55_0.11_45/0.20)]',  text: 'text-[oklch(0.36_0.12_45)]',   border: 'border-[oklch(0.55_0.11_45/0.40)]'  };
const _BLUE   = { bg: 'bg-[oklch(0.52_0.12_240/0.18)]', text: 'text-[oklch(0.34_0.14_240)]',  border: 'border-[oklch(0.52_0.12_240/0.40)]' };
const _PURPLE = { bg: 'bg-[oklch(0.50_0.09_320/0.18)]', text: 'text-[oklch(0.33_0.10_320)]',  border: 'border-[oklch(0.50_0.09_320/0.40)]' };
const _VIOLET = { bg: 'bg-[oklch(0.52_0.11_290/0.18)]', text: 'text-[oklch(0.33_0.12_290)]',  border: 'border-[oklch(0.52_0.11_290/0.40)]' };
const _RED    = { bg: 'bg-[oklch(0.48_0.13_20/0.18)]',  text: 'text-[oklch(0.34_0.15_20)]',   border: 'border-[oklch(0.48_0.13_20/0.40)]'  };
const _GRAY   = { bg: 'bg-surface-raised dark:bg-surface-raised', text: 'text-muted-foreground', border: 'border-border' };

const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  // Income (green)
  'Income': _GREEN,
  'Paychecks/Salary': _GREEN,
  'Deposits': _GREEN,
  'Interest': _GREEN,
  'Tax Refund': _GREEN,
  'Other Income': _GREEN,
  'Military Pension': _GREEN,

  // Transfers / debt service (teal)
  'Transfer': _TEAL,
  'Transfers': _TEAL,
  'Credit Card Payments': _TEAL,
  'Loan Payments': _TEAL,
  'Mortgage': _TEAL,
  'Mortgages': _TEAL,
  'Auto Loan': _TEAL,
  'Student Loan': _TEAL,

  // Food (olive / orange)
  'Groceries': _OLIVE,
  'Dining': _ORANGE,
  'Restaurants/Dining': _ORANGE,

  // Shopping / merch (blue)
  'Shopping': _BLUE,
  'General Merchandise': _BLUE,

  // Entertainment / subs (purple/violet)
  'Entertainment': _PURPLE,
  'Travel': _VIOLET,
  'Dues and Subscriptions': _PURPLE,

  // Utilities / phone (teal)
  'Utilities': _TEAL,
  'Telephone Services': _TEAL,

  // Auto / medical / insurance (red/olive)
  'Auto': _RED,
  'Medical': _RED,
  'Healthcare': _RED,
  'Insurance': _OLIVE,

  // Home (orange)
  'Home Improvement': _ORANGE,

  'Savings': _BLUE,
  'Uncategorized': _GRAY,
};
const getCategoryStyle = (cat: string) => CATEGORY_COLORS[cat] || CATEGORY_COLORS['Uncategorized'];

// Timeframe presets — anchored in local time, no UTC drift, correct
// month-end day (used to hard-code "31" which only worked because
// SQLite compares ISO strings lexicographically).
const _fmtDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const _lastDayOfMonth = (y: number, m0: number) => new Date(y, m0 + 1, 0).getDate();

const TIME_PRESETS: Record<string, { start: string; end: string } | null> = {
  'All Time': null,
  'This Month': (() => {
    const now = new Date();
    const y = now.getFullYear();
    const m0 = now.getMonth();
    const last = _lastDayOfMonth(y, m0);
    return {
      start: `${y}-${String(m0 + 1).padStart(2, '0')}-01`,
      end:   `${y}-${String(m0 + 1).padStart(2, '0')}-${String(last).padStart(2, '0')}`,
    };
  })(),
  'Last 3 Months': (() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth() - 2, 1);
    return { start: _fmtDate(start), end: _fmtDate(now) };
  })(),
  'Last 6 Months': (() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth() - 5, 1);
    return { start: _fmtDate(start), end: _fmtDate(now) };
  })(),
};

// Category classifiers used by the Income/Expenses direction filter. Hoisted
// to module scope — they were being rebuilt on every filtered iteration,
// which meant 2 Set allocations per transaction on a 1000-row filter.
// Mirrors the backend blacklist+sign-check pattern (CLAUDE.md §4.6).
const SPEND_OR_TRANSFER_CATS = new Set([
  'Transfers', 'Transfer', 'Credit Card Payments', 'Mortgages',
  'Loan Payments', 'Loan Payment', 'Auto Loan', 'Student Loan',
  'Refunds/Adjustments',
]);
const INCOME_CATS = new Set([
  'Income', 'Paychecks/Salary', 'Deposits', 'Interest',
  'Rental Income', 'Investment Income', 'Retirement Income',
  'Tax Refund', 'Other Income', 'Military Pension',
  'VA Benefits', 'VA Education Benefits', 'Officiating Income',
  'Non-Recurring Income',
]);

export default function TransactionsPage() {
  const { accounts: ACCOUNTS_LIST, accountNames: ACCOUNT_NAMES, categories: CATEGORIES } = useAccounts();
  const SYNTHETIC_ACCOUNTS = useMemo(
    () => new Set(ACCOUNTS_LIST.filter(a => !!a.is_synthetic).map(a => a.id)),
    [ACCOUNTS_LIST],
  );
  // Active view (Quintin / Household / Amy) — threaded into every fetch
  // so the list, recurring dedupe set, and add-transaction default land
  // in the right scope. Before this wiring TransactionsPage always
  // returned the full household roll-up regardless of the chip.
  const { ownerParam } = useView();
  const ownerOnlyQs = ownerParam ? `?owner_id=${encodeURIComponent(ownerParam)}` : "";
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlAccountId = searchParams.get('account_id');
  const urlRecurring = searchParams.get('recurring') === 'true';
  const urlMerchant = searchParams.get('merchant');
  const urlSearch = searchParams.get('search');
  const [showAddDialog, setShowAddDialog] = useState(false);
  useEffect(() => {
    if (!showAddDialog) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowAddDialog(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAddDialog]);
  // Default account is patched in via useEffect once accounts load — there
  // is no hardcoded ID, the previous default was a phantom ('chase_chk_001')
  // that didn't exist in the DB and would orphan any submitted row.
  const [newTx, setNewTx] = useState({
    description: '',
    amount: '',
    category: 'Uncategorized',
    account_id: '',
    posting_date: new Date().toISOString().split('T')[0],
  });
  const [allTransactions, setAllTransactions] = useState<any[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [selectedTransaction, setSelectedTransaction] = useState<any>(null);

  // Filter state (persisted across navigation via sessionStorage)
  const [timePreset, setTimePreset] = useSessionState('transactions:timePreset', 'All Time');
  const [directionFilter, setDirectionFilter] = useSessionState<string | null>('transactions:directionFilter', null);
  const [categoryFilter, setCategoryFilter] = useSessionState<string | null>('transactions:categoryFilter', null);
  const [searchQuery, setSearchQuery] = useState(urlSearch || '');
  const [currentPage, setCurrentPage] = useState(0);
  const [sortColumn, setSortColumn] = useSessionState<string>('transactions:sortColumn', 'posting_date');
  const [sortDirection, setSortDirection] = useSessionState<'asc' | 'desc'>('transactions:sortDirection', 'desc');
  const [showTimeDropdown, setShowTimeDropdown] = useState(false);
  const [showFilterPopover, setShowFilterPopover] = useState(false);
  const timeDropdownRef = useRef<HTMLDivElement>(null);
  const filterDropdownRef = useRef<HTMLDivElement>(null);

  // Teach the System Wizard
  const [showTeachDialog, setShowTeachDialog] = useState(false);
  const [teachForm, setTeachForm] = useState({
    category: '',
    merchant_name: '',
    match_type: 'merchant_contains',
    match_string: '',
    mark_recurring: false
  });

  // Advanced filter state (popover, persisted via sessionStorage)
  const [accountFilterAdv, setAccountFilterAdv] = useSessionState<string | null>('transactions:accountFilterAdv', null);
  const [merchantSearch, setMerchantSearch] = useSessionState('transactions:merchantSearch', '');
  const [amountMin, setAmountMin] = useSessionState('transactions:amountMin', '');
  const [amountMax, setAmountMax] = useSessionState('transactions:amountMax', '');
  const [customStartDate, setCustomStartDate] = useSessionState('transactions:customStartDate', '');
  const [customEndDate, setCustomEndDate] = useSessionState('transactions:customEndDate', '');

  // Recurring filter state (session-persisted, URL param overrides on direct navigation)
  const [recurringFilter, setRecurringFilter] = useSessionState('transactions:recurringFilter', urlRecurring);
  const [merchantFilter, setMerchantFilter] = useState<string | null>(urlMerchant || null);
  const [recurringMerchants, setRecurringMerchants] = useState<Set<string>>(new Set());
  const [recurringError, setRecurringError] = useState<Error | null>(null);

  // Fetch recurring merchants (owner-scoped) whenever the active view changes.
  const fetchRecurring = useCallback(() => {
    setRecurringError(null);
    apiFetch<{ recurring?: { merchant?: string }[] }>(`/api/recurring${ownerOnlyQs}`)
      .then(data => {
        const merchants = new Set<string>(
          (data.recurring || []).map(r => (r.merchant || '').toLowerCase())
        );
        setRecurringMerchants(merchants);
      })
      .catch(e => {
        console.error(e);
        setRecurringMerchants(new Set());
        setRecurringError(e instanceof Error ? e : new Error(String(e)));
        toast("Failed to load recurring merchants", "error");
      });
  }, [ownerOnlyQs]);

  useEffect(() => { fetchRecurring(); }, [fetchRecurring]);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (timeDropdownRef.current && !timeDropdownRef.current.contains(e.target as Node)) {
        setShowTimeDropdown(false);
      }
      if (filterDropdownRef.current && !filterDropdownRef.current.contains(e.target as Node)) {
        setShowFilterPopover(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Build URL and fetch
  const fetchTransactions = useCallback(() => {
    const params = new URLSearchParams();
    params.set('limit', '1000'); // Fetch all, paginate client-side

    const timeRange = TIME_PRESETS[timePreset];
    if (timeRange) {
      params.set('start_date', timeRange.start);
      params.set('end_date', timeRange.end);
    }

    if (urlAccountId) {
      params.set('account_id', urlAccountId);
    }
    if (ownerParam) {
      params.set('owner_id', ownerParam);
    }

    apiFetch<{ transactions?: any[]; total_count?: number }>(
      `/api/transactions?${params.toString()}`
    )
      .then(data => {
        setAllTransactions(data.transactions || []);
        setTotalCount(data.total_count ?? (data.transactions || []).length);
        setCurrentPage(0);
      })
      .catch(err => console.error("Error fetching transactions: ", err));
  }, [timePreset, urlAccountId, ownerParam]);

  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

  // Default the Add Transaction account to the first real account once
  // the accounts list loads.  Replaces the hardcoded 'chase_chk_001'
  // ghost ID that didn't exist in the DB.
  useEffect(() => {
    if (!newTx.account_id && ACCOUNTS_LIST.length > 0) {
      setNewTx(prev => ({ ...prev, account_id: ACCOUNTS_LIST[0].id }));
    }
  }, [ACCOUNTS_LIST, newTx.account_id]);

  // Handle pre-selected transaction from Dashboard navigation
  useEffect(() => {
    const state = location.state as any;
    if (state?.selectedTxId && allTransactions.length > 0) {
      const tx = allTransactions.find(t => t.id === state.selectedTxId);
      if (tx) setSelectedTransaction(tx);
      // Clear the state so it doesn't re-trigger
      window.history.replaceState({}, document.title);
    }
  }, [location.state, allTransactions]);

  // Prebuild the recurring-merchant match list once per recurring-set refresh.
  // Previously the filter did `[...recurringMerchants].some(...)` per tx,
  // spreading the Set into a fresh array every iteration (O(n·m) allocations).
  const recurringMatchList = useMemo(
    () => Array.from(recurringMerchants).filter(rm => rm.length >= 3),
    [recurringMerchants],
  );

  // Apply client-side filters.  Memoized so that unrelated re-renders
  // (e.g. opening a modal) don't re-scan 1000 rows.
  const filteredTransactions = useMemo(() => allTransactions.filter(tx => {
    // Direction filter — uses the canonical pattern (transfer_tag IS NULL
    // + spend/income blacklist) so the chip counts match the Cash Flow
    // page.  Raw sign-only filtering used to count transfers and
    // CC payments as income, inflating the Income chip 3x.
    const amt = tx.signed_amount ?? tx.amount;
    const isTransfer = !!tx.transfer_tag;
    const cat = tx.category || '';
    if (directionFilter === 'Income') {
      if (amt <= 0) return false;
      if (isTransfer) return false;
      if (SPEND_OR_TRANSFER_CATS.has(cat)) return false;
    }
    if (directionFilter === 'Expenses') {
      if (amt >= 0) return false;
      if (isTransfer) return false;
      if (INCOME_CATS.has(cat) || SPEND_OR_TRANSFER_CATS.has(cat)) return false;
    }

    // Category filter (from popover)
    if (categoryFilter && tx.category !== categoryFilter) return false;

    // Account filter (from popover)
    if (accountFilterAdv && tx.account_id !== accountFilterAdv) return false;

    // Merchant search (from popover)
    if (merchantSearch) {
      const ms = merchantSearch.toLowerCase();
      const desc = (tx.description || '').toLowerCase();
      const merch = (tx.merchant || '').toLowerCase();
      if (!desc.includes(ms) && !merch.includes(ms)) return false;
    }

    // Amount range (from popover)
    const absAmt = Math.abs(tx.signed_amount ?? tx.amount ?? 0);
    if (amountMin !== '' && absAmt < parseFloat(amountMin)) return false;
    if (amountMax !== '' && absAmt > parseFloat(amountMax)) return false;

    // Custom date range (from popover — overrides time preset if set)
    if (customStartDate || customEndDate) {
      const txDate = tx.posting_date || '';
      if (customStartDate && txDate < customStartDate) return false;
      if (customEndDate && txDate > customEndDate) return false;
    }

    // Global search bar
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matches = [
        tx.description?.toLowerCase().includes(q),
        tx.merchant?.toLowerCase().includes(q),
        tx.category?.toLowerCase().includes(q),
        ACCOUNT_NAMES[tx.account_id]?.toLowerCase().includes(q),
        tx.account_id?.toLowerCase().includes(q),
      ].some(Boolean);
      if (!matches) return false;
    }

    // Recurring filter — substring match in either direction.
    // Exact-equality lookup used to silently drop everything because
    // (a) the merchant_normalizer turns "AMAZON PRIME RENEWAL" into a
    // shorter `merchant` like "Amazon", and (b) the recurring API
    // returns canonical names like "AMAZON PRIME" that don't equal
    // either the description or the normalized merchant.  Substring
    // matching against the recurring set fixes both directions.
    if (recurringFilter) {
      const desc = (tx.description || '').toLowerCase();
      const merch = (tx.merchant || '').toLowerCase();
      const isRecurring = recurringMatchList.some(rm =>
        desc.includes(rm) || merch.includes(rm)
      );
      if (!isRecurring) return false;
      if (merchantFilter) {
        const mf = merchantFilter.toLowerCase();
        if (!desc.includes(mf) && !merch.includes(mf)) return false;
      }
    }

    return true;
  }), [
    allTransactions, directionFilter, categoryFilter, accountFilterAdv,
    merchantSearch, amountMin, amountMax, customStartDate, customEndDate,
    searchQuery, recurringFilter, merchantFilter, recurringMatchList,
    ACCOUNT_NAMES,
  ]);

  // Sorting
  const handleSort = (col: string) => {
    if (sortColumn === col) {
      setSortDirection(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortColumn(col);
      setSortDirection(col === 'posting_date' ? 'desc' : 'asc');
    }
    setCurrentPage(0);
  };

  const sortedTransactions = useMemo(() => [...filteredTransactions].sort((a, b) => {
    const dir = sortDirection === 'asc' ? 1 : -1;
    switch (sortColumn) {
      case 'posting_date':
        return dir * ((a.posting_date || '').localeCompare(b.posting_date || ''));
      case 'merchant':
        return dir * ((a.description || a.merchant || '').localeCompare(b.description || b.merchant || ''));
      case 'category':
        return dir * ((a.category || '').localeCompare(b.category || ''));
      case 'account':
        return dir * ((ACCOUNT_NAMES[a.account_id] || a.account_id || '').localeCompare(ACCOUNT_NAMES[b.account_id] || b.account_id || ''));
      case 'amount': {
        const amtA = a.signed_amount ?? a.amount ?? 0;
        const amtB = b.signed_amount ?? b.amount ?? 0;
        return dir * (amtA - amtB);
      }
      default:
        return 0;
    }
  }), [filteredTransactions, sortColumn, sortDirection, ACCOUNT_NAMES]);

  // Pagination
  const totalPages = Math.ceil(sortedTransactions.length / PAGE_SIZE);
  const paginatedTransactions = sortedTransactions.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE
  );

  const SortIcon = ({ col }: { col: string }) => (
    <span className={`material-symbols-outlined text-[14px] transition-transform ${sortColumn === col ? 'text-primary' : 'text-muted-foreground opacity-0 group-hover/th:opacity-100'}`}>
      {sortColumn === col ? (sortDirection === 'asc' ? 'arrow_upward' : 'arrow_downward') : 'swap_vert'}
    </span>
  );

  const handleCategoryChange = (newCategory: string) => {
    if (!selectedTransaction) return;
    
    // Optimistic UI update
    setAllTransactions(prev => prev.map(t => 
      t.id === selectedTransaction.id ? { ...t, category: newCategory } : t
    ));
    setSelectedTransaction({ ...selectedTransaction, category: newCategory });

    // Backend update
    apiFetch(
      `/api/transactions/${selectedTransaction.id}/category?category=${encodeURIComponent(newCategory)}`,
      { method: 'PATCH' },
    ).then(() => {
      toast(`Category updated to ${newCategory}`, "success");
    }).catch(() => {
      toast("Failed to update category", "error");
    });
  };

  // Active filter indicator
  const advFilterCount = [categoryFilter, accountFilterAdv, merchantSearch, amountMin || amountMax, customStartDate || customEndDate].filter(Boolean).length;
  const hasActiveFilters = directionFilter || categoryFilter || searchQuery || timePreset !== 'All Time' || urlAccountId || recurringFilter || accountFilterAdv || merchantSearch || amountMin || amountMax || customStartDate || customEndDate;

  return (
    <PageShell className="overflow-hidden relative">
      <div className="sticky top-0 z-10 bg-background border-b border-border px-12 py-3 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Account Filter Chip (from Accounts page nav) */}
          {urlAccountId && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--chart-c7)]/15 text-[var(--chart-c7)] border border-[var(--chart-c7)]/30 rounded-lg text-xs font-semibold">
              <span className="material-symbols-outlined text-xs">account_balance</span>
              {ACCOUNT_NAMES[urlAccountId] || urlAccountId}
              <button onClick={() => navigate('/transactions')} className="ml-1 hover:text-loss transition-colors">
                <span className="material-symbols-outlined text-xs">close</span>
              </button>
            </div>
          )}
          {/* Time Preset Dropdown */}
          <div className="relative" ref={timeDropdownRef}>
            <button 
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                timePreset !== 'All Time'
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border border-border'
              }`}
              onClick={() => setShowTimeDropdown(!showTimeDropdown)}
            >
              {timePreset} <span className="material-symbols-outlined text-xs">expand_more</span>
            </button>
            {showTimeDropdown && (
              <div className="absolute top-full left-0 mt-1 bg-popover text-popover-foreground border border-border rounded-lg shadow-xl z-50 min-w-[160px] py-1 animate-in fade-in slide-in-from-top-2 duration-150">
                {Object.keys(TIME_PRESETS).map(preset => (
                  <button
                    key={preset}
                    className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-primary/10 transition-colors ${timePreset === preset ? 'text-primary bg-primary/5' : 'text-foreground'}`}
                    onClick={() => { setTimePreset(preset); setShowTimeDropdown(false); }}
                  >
                    {preset}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Income Filter */}
          <button
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              directionFilter === 'Income'
                ? 'bg-gain-subtle text-gain border border-[var(--color-gain)]/30'
                : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border border-border'
            }`}
            onClick={() => setDirectionFilter(directionFilter === 'Income' ? null : 'Income')}
          >
            <span className="material-symbols-outlined text-xs">trending_up</span>
            Income
          </button>

          {/* Expenses Filter */}
          <button
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              directionFilter === 'Expenses'
                ? 'bg-loss-subtle text-loss border border-[var(--color-loss)]/30'
                : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border border-border'
            }`}
            onClick={() => setDirectionFilter(directionFilter === 'Expenses' ? null : 'Expenses')}
          >
            <span className="material-symbols-outlined text-xs">trending_down</span>
            Expenses
          </button>

          {/* Recurring Filter */}
          <button
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
              recurringFilter
                ? 'bg-[var(--chart-c4)]/15 text-[var(--chart-c4)] border border-[var(--chart-c4)]/30'
                : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border border-border'
            }`}
            onClick={() => {
              setRecurringFilter(!recurringFilter);
              if (recurringFilter) setMerchantFilter(null);
              setCurrentPage(0);
            }}
          >
            <span className="material-symbols-outlined text-xs">autorenew</span>
            Recurring
            {merchantFilter && recurringFilter && (
              <>
                <span className="text-[10px]">&middot;</span>
                <span className="truncate max-w-[100px]">{merchantFilter}</span>
                <button onClick={(e) => { e.stopPropagation(); setMerchantFilter(null); }} className="ml-0.5 hover:text-loss">
                  <span className="material-symbols-outlined text-[10px]">close</span>
                </button>
              </>
            )}
          </button>

          {/* Multi-field Filter Popover */}
          <div className="relative" ref={filterDropdownRef}>
            <button
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                advFilterCount > 0
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border border-border'
              }`}
              onClick={() => setShowFilterPopover(p => !p)}
            >
              <span className="material-symbols-outlined text-xs">filter_list</span>
              Filter
              {advFilterCount > 0 && (
                <span className="inline-flex items-center justify-center size-4 rounded-full bg-primary text-primary-foreground text-[10px] font-bold">{advFilterCount}</span>
              )}
              <span className="material-symbols-outlined text-xs">expand_more</span>
            </button>

            {showFilterPopover && (
              <div className="absolute top-full left-0 mt-1 bg-popover text-popover-foreground border border-border rounded-xl shadow-2xl z-50 w-[340px] animate-in fade-in slide-in-from-top-2 duration-150 overflow-hidden">
                <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                  <span className="text-label">Filters</span>
                  {advFilterCount > 0 && (
                    <button
                      className="text-[10px] font-semibold text-muted-foreground hover:text-loss transition-colors"
                      onClick={() => { setCategoryFilter(null); setAccountFilterAdv(null); setMerchantSearch(''); setAmountMin(''); setAmountMax(''); setCustomStartDate(''); setCustomEndDate(''); }}
                    >Clear all</button>
                  )}
                </div>

                <div className="p-4 space-y-4 max-h-[480px] overflow-y-auto custom-scrollbar">

                  {/* Category */}
                  <div>
                    <p className="text-label mb-2">Category</p>
                    <div className="flex flex-wrap gap-1.5">
                      {[null, ...CATEGORIES].map(cat => (
                        <button
                          key={cat ?? '__all'}
                          onClick={() => setCategoryFilter(cat)}
                          className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors ${
                            categoryFilter === cat
                              ? 'bg-primary/20 text-primary border-primary/30'
                              : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border-border hover:border-primary/40 hover:text-primary'
                          }`}
                        >
                          {cat ?? 'All'}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Account */}
                  <div>
                    <p className="text-label mb-2">Account</p>
                    <div className="flex flex-col gap-1">
                      {[null, ...Object.entries(ACCOUNT_NAMES)].map(entry => {
                        const [id, name] = entry === null ? [null, 'All Accounts'] : entry as [string, string];
                        return (
                          <button
                            key={id ?? '__all'}
                            onClick={() => setAccountFilterAdv(id)}
                            className={`text-left px-3 py-1.5 rounded-lg text-xs font-semibold border transition-colors ${
                              accountFilterAdv === id
                                ? 'bg-primary/20 text-primary border-primary/30'
                                : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border-border hover:border-primary/40 hover:text-primary'
                            }`}
                          >
                            {name}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Merchant */}
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground mb-2">Merchant</p>
                    <div className="relative">
                      <span className="material-symbols-outlined text-xs text-muted-foreground absolute left-2.5 top-1/2 -translate-y-1/2">search</span>
                      <input
                        type="text"
                        placeholder="Search merchant…"
                        value={merchantSearch}
                        onChange={e => setMerchantSearch(e.target.value)}
                        className="w-full pl-7 pr-3 py-1.5 text-xs bg-surface-raised dark:bg-surface-raised border border-border rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                      />
                    </div>
                  </div>

                  {/* Amount Range */}
                  <div>
                    <p className="text-label mb-2">Amount</p>
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground font-bold">$</span>
                        <input
                          type="number"
                          placeholder="Min"
                          value={amountMin}
                          onChange={e => setAmountMin(e.target.value)}
                          className="w-full pl-5 pr-2 py-1.5 text-xs bg-surface-raised dark:bg-surface-raised border border-border rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                        />
                      </div>
                      <span className="text-xs text-muted-foreground font-bold">-</span>
                      <div className="relative flex-1">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground font-bold">$</span>
                        <input
                          type="number"
                          placeholder="Max"
                          value={amountMax}
                          onChange={e => setAmountMax(e.target.value)}
                          className="w-full pl-5 pr-2 py-1.5 text-xs bg-surface-raised dark:bg-surface-raised border border-border rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Date Range */}
                  <div>
                    <p className="text-label mb-2">Date Range</p>
                    <div className="flex items-center gap-2">
                      <input
                        type="date"
                        value={customStartDate}
                        onChange={e => setCustomStartDate(e.target.value)}
                        className="flex-1 px-2 py-1.5 text-xs bg-surface-raised dark:bg-surface-raised border border-border rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                      />
                      <span className="text-xs text-muted-foreground font-bold">-</span>
                      <input
                        type="date"
                        value={customEndDate}
                        onChange={e => setCustomEndDate(e.target.value)}
                        className="flex-1 px-2 py-1.5 text-xs bg-surface-raised dark:bg-surface-raised border border-border rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                      />
                    </div>
                  </div>

                </div>
              </div>
            )}
          </div>

          {/* Clear All Filters */}
          {hasActiveFilters && (
            <button 
              className="flex items-center gap-1 px-2 py-1.5 text-xs font-semibold text-muted-foreground hover:text-loss transition-colors"
              onClick={() => {
                setTimePreset('All Time');
                setDirectionFilter(null);
                setCategoryFilter(null);
                setAccountFilterAdv(null);
                setMerchantSearch('');
                setAmountMin('');
                setAmountMax('');
                setCustomStartDate('');
                setCustomEndDate('');
                setSearchQuery('');
                setCurrentPage(0);
                if (urlAccountId) navigate('/transactions');
              }}
            >
              <span className="material-symbols-outlined text-xs">close</span>
              Clear
            </button>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Search Bar */}
          <div className="relative">
            <span className="material-symbols-outlined text-sm text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2">search</span>
            <input
              type="text"
              placeholder="Search transactions..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(0); }}
              className="pl-9 pr-4 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[200px]"
            />
          </div>
          <button
            onClick={() => setShowAddDialog(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] transition-transform"
          >
            <span className="material-symbols-outlined text-sm">add</span> Add Transaction
          </button>
        </div>
      </div>

      <div className="px-12 pt-6 pb-8 flex-1 overflow-hidden flex flex-col">
        {recurringError && (
          <div
            role="alert"
            className="card-l1 mb-4 p-4 flex items-start gap-3 bg-loss-subtle border-loss/20"
          >
            <span className="material-symbols-outlined text-2xl text-loss shrink-0" aria-hidden="true">error</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-foreground">Recurring-transaction labels unavailable</p>
              <p className="text-xs text-muted-foreground mt-1">
                {recurringError.message || "Network error"} — the list below is complete, but recurring badges and the "Recurring only" filter are currently disabled.
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={fetchRecurring} className="gap-1.5 shrink-0">
              <span className="material-symbols-outlined text-[14px]">refresh</span>
              Try again
            </Button>
          </div>
        )}
        <div className="card-l1 overflow-hidden flex flex-col h-full">
          <div className="flex-1 overflow-auto custom-scrollbar">
            <Table className="w-full relative min-w-[700px]">
              <TableHeader className="bg-surface-raised dark:bg-surface-raised sticky top-0 z-10 shadow-sm">
                <TableRow>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-muted-foreground w-[15%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('posting_date')}><span className="flex items-center gap-1">Date <SortIcon col="posting_date" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-muted-foreground w-[35%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('merchant')}><span className="flex items-center gap-1">Merchant <SortIcon col="merchant" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-muted-foreground w-[20%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('category')}><span className="flex items-center gap-1">Category <SortIcon col="category" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-muted-foreground w-[15%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('account')}><span className="flex items-center gap-1">Account <SortIcon col="account" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-muted-foreground w-[15%] text-right cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('amount')}><span className="flex items-center gap-1 justify-end">Amount <SortIcon col="amount" /></span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedTransactions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="px-6 py-12 text-center text-muted-foreground">
                      <div className="flex flex-col items-center gap-2">
                        <span className="material-symbols-outlined text-3xl">search_off</span>
                        <p className="font-semibold">No transactions found</p>
                        <p className="text-xs">Try adjusting your filters or search query</p>
                      </div>
                    </TableCell>
                  </TableRow>
                ) : paginatedTransactions.map((tx) => (
                  <TableRow 
                    key={tx.id} 
                    className="group hover:bg-primary/[0.06] cursor-pointer transition-all duration-150"
                    onClick={() => setSelectedTransaction(tx)}
                  >
                    <TableCell className="px-6 py-4 text-sm text-muted-foreground whitespace-nowrap">{formatDate(tx.posting_date)}</TableCell>
                    <TableCell className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <TransactionLogo merchantName={tx.merchant || tx.description || 'Unknown'} size="md" />
                        <div className="flex flex-col min-w-0">
                          <span title={tx.merchant || tx.description} className="text-sm font-bold truncate max-w-[200px] text-foreground">
                            {tx.merchant || tx.description}
                          </span>
                          {tx.merchant && tx.description && tx.merchant !== tx.description && (
                            <span title={tx.description} className="text-xs text-muted-foreground truncate max-w-[200px]">
                              {tx.description}
                            </span>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      {(() => {
                        const cs = getCategoryStyle(tx.category);
                        return (
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap ${cs.bg} ${cs.text} ${cs.border}`}>
                            {tx.category}
                          </span>
                        );
                      })()}
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-muted-foreground whitespace-nowrap">
                      {ACCOUNT_NAMES[tx.account_id] || tx.account_id}
                      {SYNTHETIC_ACCOUNTS.has(tx.account_id) && <> <SyntheticBadge compact /></>}
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm font-bold text-right whitespace-nowrap">
                      {(() => {
                        const amount = tx.signed_amount ?? tx.amount;
                        return (
                          <span className={amount < 0 ? "text-loss text-numeric" : "text-gain text-numeric"}>
                            {amount >= 0 ? '+' : ''}{formatCurrency(amount)}
                          </span>
                        );
                      })()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          
          <div className="px-6 py-4 border-t border-border flex items-center justify-between bg-surface-raised/50 dark:bg-background/50 shrink-0">
            <span className="text-xs text-muted-foreground">
              Showing {paginatedTransactions.length > 0 ? currentPage * PAGE_SIZE + 1 : 0}-{Math.min((currentPage + 1) * PAGE_SIZE, sortedTransactions.length)} of {hasActiveFilters ? sortedTransactions.length : Math.max(sortedTransactions.length, totalCount)} transactions
              {hasActiveFilters && ` (filtered from ${Math.max(allTransactions.length, totalCount)})`}
            </span>
            <div className="flex items-center gap-2">
              <button
                className="px-3 py-1 text-xs border border-border rounded-lg hover:bg-primary/5 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                disabled={currentPage === 0}
                onClick={() => setCurrentPage(p => Math.max(0, p - 1))}
              >Previous</button>
              
              {/* Page numbers */}
              <div className="flex items-center gap-1">
                {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                  let pageNum: number;
                  if (totalPages <= 5) {
                    pageNum = i;
                  } else if (currentPage < 3) {
                    pageNum = i;
                  } else if (currentPage > totalPages - 4) {
                    pageNum = totalPages - 5 + i;
                  } else {
                    pageNum = currentPage - 2 + i;
                  }
                  return (
                    <button
                      key={pageNum}
                      className={`size-7 text-xs rounded-md font-bold transition-all ${
                        currentPage === pageNum
                          ? 'bg-primary text-primary-foreground shadow-sm'
                          : 'text-muted-foreground hover:bg-primary/10'
                      }`}
                      onClick={() => setCurrentPage(pageNum)}
                    >
                      {pageNum + 1}
                    </button>
                  );
                })}
              </div>

              <button
                className="px-3 py-1 text-xs border border-border rounded-lg hover:bg-primary/5 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
                disabled={currentPage >= totalPages - 1}
                onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))}
              >Next</button>
            </div>
          </div>
        </div>
      </div>
      
      {/* Add Transaction Dialog */}
      {showAddDialog && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowAddDialog(false)}>
          <div className="bg-popover text-popover-foreground border border-border rounded-xl shadow-2xl w-[420px] p-6 animate-in fade-in zoom-in-95 duration-200" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg" id="add-tx-title">Add Transaction</h3>
              <button
                onClick={() => setShowAddDialog(false)}
                className="text-muted-foreground hover:text-loss transition-colors"
                aria-label="Close add-transaction dialog"
              >
                <span className="material-symbols-outlined text-sm" aria-hidden="true">close</span>
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label htmlFor="add-tx-description" className="block text-label mb-1">Description</label>
                <input id="add-tx-description" value={newTx.description} onChange={(e) => setNewTx(p => ({...p, description: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none focus:border-primary/50" placeholder="e.g. Costco Wholesale" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="add-tx-amount" className="block text-label mb-1">Amount</label>
                  <input id="add-tx-amount" type="number" step="0.01" value={newTx.amount} onChange={(e) => setNewTx(p => ({...p, amount: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none focus:border-primary/50" placeholder="-127.00" />
                </div>
                <div>
                  <label htmlFor="add-tx-date" className="block text-label mb-1">Date</label>
                  <input id="add-tx-date" type="date" value={newTx.posting_date} onChange={(e) => setNewTx(p => ({...p, posting_date: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none focus:border-primary/50" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="add-tx-category" className="block text-label mb-1">Category</label>
                  <select id="add-tx-category" value={newTx.category} onChange={(e) => setNewTx(p => ({...p, category: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none cursor-pointer">
                    {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label htmlFor="add-tx-account" className="block text-label mb-1">Account</label>
                  <select id="add-tx-account" value={newTx.account_id} onChange={(e) => setNewTx(p => ({...p, account_id: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none cursor-pointer">
                    {Object.entries(ACCOUNT_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
                  </select>
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                onClick={() => {
                  const amt = parseFloat(newTx.amount);
                  if (!newTx.description || isNaN(amt)) return;
                  apiFetch('/api/transactions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      description: newTx.description,
                      amount: amt,
                      signed_amount: amt,
                      category: newTx.category,
                      account_id: newTx.account_id,
                      posting_date: newTx.posting_date,
                      status: 'posted',
                      direction: amt < 0 ? 'outflow' : 'inflow',
                    })
                  }).then(() => {
                    setShowAddDialog(false);
                    setNewTx({ description: '', amount: '', category: 'Uncategorized', account_id: 'chase_chk_001', posting_date: new Date().toISOString().split('T')[0] });
                    fetchTransactions();
                  }).catch(console.error);
                }}
                className="flex-1 px-4 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-bold hover:bg-primary/80 transition-colors"
              >Add Transaction</button>
              <button onClick={() => setShowAddDialog(false)} className="px-4 py-2.5 border border-border rounded-lg text-sm font-semibold hover:bg-surface-raised transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}

      <Sheet open={!!selectedTransaction} onOpenChange={(open) => !open && setSelectedTransaction(null)}>
        <SheetContent className="w-[380px] sm:w-[420px] border-l border-border bg-background overflow-y-auto">
          <SheetHeader className="border-b border-border pb-4 mb-6">
            <SheetTitle>Transaction Details</SheetTitle>
          </SheetHeader>
          
          {selectedTransaction && (
            <div className="space-y-5">
              <div className="text-center space-y-1">
                <div className="size-12 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-3 border border-primary/20">
                  <span className="material-symbols-outlined text-xl text-primary">shopping_bag</span>
                </div>
                <h4 className="text-lg font-bold">{selectedTransaction.description || selectedTransaction.merchant}</h4>
                {(() => {
                  const detailAmount = selectedTransaction.signed_amount ?? selectedTransaction.amount;
                  return (
                    <p className={`text-2xl font-bold text-numeric ${detailAmount < 0 ? 'text-loss' : 'text-gain'}`}>
                      {detailAmount >= 0 ? '+' : ''}{formatCurrency(detailAmount)}
                    </p>
                  );
                })()}
                <p className="text-xs text-muted-foreground">{formatDate(selectedTransaction.posting_date)}</p>
              </div>

              <div className="grid grid-cols-2 gap-4 bg-surface-raised dark:bg-surface-raised p-3 rounded-xl border border-border">
                <div>
                  <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Status</p>
                  <p className="text-xs font-semibold flex items-center gap-1 mt-0.5">
                    <span className="size-1.5 rounded-full bg-[var(--color-gain)]"></span> {selectedTransaction.status}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Account</p>
                  <p className="text-xs font-semibold mt-0.5">{ACCOUNT_NAMES[selectedTransaction.account_id] || selectedTransaction.account_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Institution</p>
                  <p className="text-xs font-semibold mt-0.5">{institutionDisplayName(selectedTransaction.institution_id)}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-muted-foreground tracking-wider">Category</p>
                  <p className="text-xs font-semibold mt-0.5">{selectedTransaction.category}</p>
                </div>
              </div>

              <div className="space-y-3">
                <label className="block text-xs font-bold text-foreground">Reclassify Category</label>
                <Select value={selectedTransaction.category} onValueChange={handleCategoryChange}>
                  <SelectTrigger className="w-full bg-surface-raised dark:bg-surface-raised h-9 text-sm">
                    <SelectValue placeholder="Select Category" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map(cat => (
                      <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex flex-col gap-2 mt-2">
                  <p className="text-[10px] text-muted-foreground">Changes will be applied to this transaction only.</p>
                  <button
                    onClick={() => {
                        const merch = selectedTransaction.merchant || selectedTransaction.description || '';
                        setTeachForm({
                          category: selectedTransaction.category || 'Uncategorized',
                          merchant_name: merch,
                          match_type: 'merchant_contains',
                          match_string: merch.toLowerCase(),
                          mark_recurring: recurringMerchants.has(merch.toLowerCase())
                        });
                        setShowTeachDialog(true);
                    }}
                    className="w-full text-center py-2 border border-primary/30 text-primary bg-primary/10 rounded-md text-xs font-semibold hover:bg-primary/20 transition-colors flex items-center justify-center gap-1.5"
                  >
                    <span className="material-symbols-outlined text-[14px]">school</span>
                    Teach the System (Create Rule)
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-bold text-foreground">Recurring</label>
                <button
                  onClick={() => {
                    const merchant = selectedTransaction.description || selectedTransaction.merchant;
                    const isCurrentlyRecurring = recurringMerchants.has((merchant || '').toLowerCase());
                    if (isCurrentlyRecurring) {
                      // Dismiss/unmark recurring
                      const recId = `${selectedTransaction.account_id}__${(merchant || '').toLowerCase().replace(/ /g, '_')}`;
                      apiFetch(`/api/recurring/${recId}?action=dismiss`, { method: 'PATCH' })
                        .then(() => {
                          setRecurringMerchants(prev => {
                            const next = new Set(prev);
                            next.delete((merchant || '').toLowerCase());
                            return next;
                          });
                        })
                        .catch(console.error);
                    } else {
                      // Mark as recurring
                      apiFetch('/api/recurring/mark', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          merchant: merchant,
                          account_id: selectedTransaction.account_id,
                          category: selectedTransaction.category || 'Uncategorized',
                          amount: Math.abs(selectedTransaction.signed_amount ?? selectedTransaction.amount),
                        }),
                      })
                        .then(() => {
                          setRecurringMerchants(prev => new Set([...prev, (merchant || '').toLowerCase()]));
                        })
                        .catch(console.error);
                    }
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg border text-sm font-semibold transition-all ${
                    recurringMerchants.has((selectedTransaction.description || selectedTransaction.merchant || '').toLowerCase())
                      ? 'bg-[var(--chart-c4)]/10 text-[var(--chart-c4)] border-[var(--chart-c4)]/30 hover:bg-[var(--chart-c4)]/20'
                      : 'bg-surface-raised dark:bg-surface-raised text-muted-foreground border-border hover:bg-primary/5'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-sm">autorenew</span>
                    {recurringMerchants.has((selectedTransaction.description || selectedTransaction.merchant || '').toLowerCase())
                      ? 'Marked as Recurring'
                      : 'Mark as Recurring'}
                  </div>
                  <div className={`size-5 rounded-full border-2 flex items-center justify-center transition-all ${
                    recurringMerchants.has((selectedTransaction.description || selectedTransaction.merchant || '').toLowerCase())
                      ? 'bg-[var(--chart-c4)] border-[var(--chart-c4)]'
                      : 'border-border'
                  }`}>
                    {recurringMerchants.has((selectedTransaction.description || selectedTransaction.merchant || '').toLowerCase()) && (
                      <span className="material-symbols-outlined text-[var(--primary-foreground)] text-[11px]">check</span>
                    )}
                  </div>
                </button>
                <p className="text-[10px] text-muted-foreground">Toggle to mark/unmark this merchant as a recurring payment.</p>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-bold text-foreground">Receipt Image</label>
                <div className="h-20 w-full rounded-lg border-2 border-dashed border-border flex items-center justify-center gap-2 hover:bg-primary/5 cursor-pointer transition-colors group">
                  <span className="material-symbols-outlined text-sm text-muted-foreground group-hover:text-primary transition-colors">add_a_photo</span>
                  <span className="text-xs text-muted-foreground font-medium">Upload receipt</span>
                </div>
              </div>

              <div className="flex gap-3 pt-4 border-t border-border">
                <Button className="flex-1 bg-primary text-primary-foreground font-bold hover:bg-primary/80" onClick={() => { toast("Changes saved", "success"); setSelectedTransaction(null); }}>
                  Save Changes
                </Button>
                <Button
                  variant="outline"
                  className="text-loss border-[var(--color-loss)]/30 hover:bg-loss-subtle"
                  onClick={() => {
                    if (!confirm('Are you sure you want to delete this transaction? This cannot be undone.')) return;
                    apiFetch(`/api/transactions/${selectedTransaction.id}`, { method: 'DELETE' })
                      .then(() => {
                        setAllTransactions(prev => prev.filter(t => t.id !== selectedTransaction.id));
                        setSelectedTransaction(null);
                        toast("Transaction deleted", "success");
                      })
                      .catch(() => toast("Failed to delete transaction", "error"));
                  }}
                >Delete</Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
      {/* Teach the System Dialog */}
      {showTeachDialog && selectedTransaction && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[100] flex items-center justify-center" onClick={() => setShowTeachDialog(false)}>
          <div className="bg-popover text-popover-foreground border border-border rounded-xl shadow-2xl w-[420px] p-6 animate-in fade-in zoom-in-95 duration-200" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg flex items-center gap-2">
                <span className="material-symbols-outlined text-primary">school</span>
                Teach the System
              </h3>
              <button onClick={() => setShowTeachDialog(false)} className="text-muted-foreground hover:text-loss transition-colors">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div className="space-y-4">
              <p className="text-xs text-muted-foreground mb-2">Create a rule to automatically categorize future and existing transactions.</p>
              <div>
                <label className="block text-label mb-1">Target Category</label>
                <select value={teachForm.category} onChange={(e) => setTeachForm(p => ({...p, category: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none cursor-pointer">
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-label mb-1">Standardized Merchant Name</label>
                <input value={teachForm.merchant_name} onChange={(e) => setTeachForm(p => ({...p, merchant_name: e.target.value}))} className="w-full px-3 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-lg text-sm outline-none focus:border-primary/50" placeholder="e.g. Costco" />
              </div>
              <div className="bg-surface-raised dark:bg-surface-raised p-3 rounded-lg border border-border">
                <label className="block text-label mb-2">Matching Condition</label>
                <div className="flex gap-2">
                  <select value={teachForm.match_type} onChange={(e) => setTeachForm(p => ({...p, match_type: e.target.value}))} className="flex-[1] px-2 py-1.5 bg-input border border-border rounded-md text-xs outline-none cursor-pointer">
                    <option value="merchant_exact">Exact Match</option>
                    <option value="merchant_contains">String Contains</option>
                  </select>
                  <input value={teachForm.match_string} onChange={(e) => setTeachForm(p => ({...p, match_string: e.target.value}))} className="flex-[2] px-2 py-1.5 bg-input border border-border rounded-md text-xs outline-none focus:border-primary/50" placeholder="e.g. costco" />
                </div>
              </div>
              <label className="flex items-center gap-2 cursor-pointer mt-2">
                <input type="checkbox" checked={teachForm.mark_recurring} onChange={(e) => setTeachForm(p => ({...p, mark_recurring: e.target.checked}))} className="rounded border-border text-primary focus:ring-primary size-4" />
                <span className="text-sm font-semibold text-foreground">Also mark as recurring</span>
              </label>
            </div>
            <div className="flex gap-3 mt-6">
              <button
                onClick={() => {
                  apiFetch(`/api/transactions/${selectedTransaction.id}/categorize`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      category: teachForm.category,
                      merchant_name: teachForm.merchant_name,
                      create_rule: true,
                      match_type: teachForm.match_type,
                      match_value: { string: teachForm.match_string },
                      mark_recurring: teachForm.mark_recurring,
                    })
                  }).then(() => {
                    setShowTeachDialog(false);
                    fetchTransactions();
                    setSelectedTransaction(null);
                    toast("Rule created successfully", "success");
                  }).catch(() => {
                    toast("Failed to create rule", "error");
                  });
                }}
                className="flex-1 px-4 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-bold hover:bg-primary/80 transition-colors"
              >Create Rule</button>
              <button onClick={() => setShowTeachDialog(false)} className="px-4 py-2.5 border border-border rounded-lg text-sm font-semibold hover:bg-surface-raised transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </PageShell>
  );
}