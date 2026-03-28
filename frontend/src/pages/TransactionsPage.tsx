import { useState, useEffect, useCallback, useRef } from "react";
import { useLocation, useSearchParams, useNavigate } from "react-router-dom";
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
import { TransactionLogo } from "@/components/ui/TransactionLogo";

import { useAccounts } from "@/lib/accounts";
import { toast } from "@/lib/toast";

const PAGE_SIZE = 25;

// Per-category color mapping — boosted opacity for legibility (was 12% ? 18%)
const CATEGORY_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  'Income':           { bg: 'bg-[oklch(0.52_0.13_155/0.18)]', text: 'text-[oklch(0.34_0.13_155)]',  border: 'border-[oklch(0.52_0.13_155/0.40)]' },
  'Transfer':         { bg: 'bg-[oklch(0.52_0.10_185/0.18)]', text: 'text-[oklch(0.32_0.10_185)]',  border: 'border-[oklch(0.52_0.10_185/0.40)]' },
  'Groceries':        { bg: 'bg-[oklch(0.50_0.09_90/0.20)]',  text: 'text-[oklch(0.33_0.10_90)]',   border: 'border-[oklch(0.50_0.09_90/0.40)]'  },
  'Dining':           { bg: 'bg-[oklch(0.55_0.11_45/0.20)]',  text: 'text-[oklch(0.36_0.12_45)]',   border: 'border-[oklch(0.55_0.11_45/0.40)]'  },
  'Shopping':         { bg: 'bg-[oklch(0.52_0.12_240/0.18)]', text: 'text-[oklch(0.34_0.14_240)]',  border: 'border-[oklch(0.52_0.12_240/0.40)]' },
  'Entertainment':    { bg: 'bg-[oklch(0.50_0.09_320/0.18)]', text: 'text-[oklch(0.33_0.10_320)]',  border: 'border-[oklch(0.50_0.09_320/0.40)]' },
  'Travel':           { bg: 'bg-[oklch(0.52_0.11_290/0.18)]', text: 'text-[oklch(0.33_0.12_290)]',  border: 'border-[oklch(0.52_0.11_290/0.40)]' },
  'Utilities':        { bg: 'bg-[oklch(0.52_0.10_185/0.18)]', text: 'text-[oklch(0.32_0.10_185)]',  border: 'border-[oklch(0.52_0.10_185/0.40)]' },
  'Auto':             { bg: 'bg-[oklch(0.48_0.13_20/0.18)]',  text: 'text-[oklch(0.34_0.15_20)]',   border: 'border-[oklch(0.48_0.13_20/0.40)]'  },
  'Medical':          { bg: 'bg-[oklch(0.48_0.13_20/0.18)]',  text: 'text-[oklch(0.34_0.15_20)]',   border: 'border-[oklch(0.48_0.13_20/0.40)]'  },
  'Insurance':        { bg: 'bg-[oklch(0.50_0.09_90/0.20)]',  text: 'text-[oklch(0.33_0.10_90)]',   border: 'border-[oklch(0.50_0.09_90/0.40)]'  },
  'Home Improvement': { bg: 'bg-[oklch(0.55_0.11_45/0.20)]',  text: 'text-[oklch(0.36_0.12_45)]',   border: 'border-[oklch(0.55_0.11_45/0.40)]'  },
  'Mortgage':         { bg: 'bg-[oklch(0.55_0.11_45/0.20)]',  text: 'text-[oklch(0.36_0.12_45)]',   border: 'border-[oklch(0.55_0.11_45/0.40)]'  },
  'Savings':          { bg: 'bg-[oklch(0.52_0.12_240/0.18)]', text: 'text-[oklch(0.34_0.14_240)]',  border: 'border-[oklch(0.52_0.12_240/0.40)]' },
  'Tax Refund':       { bg: 'bg-[oklch(0.52_0.13_155/0.18)]', text: 'text-[oklch(0.34_0.13_155)]',  border: 'border-[oklch(0.52_0.13_155/0.40)]' },
  'Uncategorized':    { bg: 'bg-slate-100 dark:bg-slate-800', text: 'text-slate-600 dark:text-slate-300', border: 'border-slate-300 dark:border-slate-600' },
};
const getCategoryStyle = (cat: string) => CATEGORY_COLORS[cat] || CATEGORY_COLORS['Uncategorized'];

// Timeframe presets
const TIME_PRESETS: Record<string, { start: string; end: string } | null> = {
  'All Time': null,
  'This Month': (() => {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, '0');
    return { start: `${y}-${m}-01`, end: `${y}-${m}-31` };
  })(),
  'Last 3 Months': (() => {
    const now = new Date();
    const end = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-31`;
    const d3 = new Date(now.getFullYear(), now.getMonth() - 2, 1);
    const start = `${d3.getFullYear()}-${String(d3.getMonth() + 1).padStart(2, '0')}-01`;
    return { start, end };
  })(),
  'Last 6 Months': (() => {
    const now = new Date();
    const end = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-31`;
    const d6 = new Date(now.getFullYear(), now.getMonth() - 5, 1);
    const start = `${d6.getFullYear()}-${String(d6.getMonth() + 1).padStart(2, '0')}-01`;
    return { start, end };
  })(),
};

export default function TransactionsPage() {
  const { accountNames: ACCOUNT_NAMES, categories: CATEGORIES } = useAccounts();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlAccountId = searchParams.get('account_id');
  const urlRecurring = searchParams.get('recurring') === 'true';
  const urlMerchant = searchParams.get('merchant');
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newTx, setNewTx] = useState({ description: '', amount: '', category: 'Uncategorized', account_id: 'chase_chk_001', posting_date: new Date().toISOString().split('T')[0] });
  const [allTransactions, setAllTransactions] = useState<any[]>([]);
  const [selectedTransaction, setSelectedTransaction] = useState<any>(null);

  // Filter state
  const [timePreset, setTimePreset] = useState('All Time');
  const [directionFilter, setDirectionFilter] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(0);
  const [sortColumn, setSortColumn] = useState<string>('posting_date');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');
  const [showTimeDropdown, setShowTimeDropdown] = useState(false);
  const [showFilterPopover, setShowFilterPopover] = useState(false);
  const timeDropdownRef = useRef<HTMLDivElement>(null);
  const filterDropdownRef = useRef<HTMLDivElement>(null);

  // Advanced filter state (popover)
  const [accountFilterAdv, setAccountFilterAdv] = useState<string | null>(null);
  const [merchantSearch, setMerchantSearch] = useState('');
  const [amountMin, setAmountMin] = useState('');
  const [amountMax, setAmountMax] = useState('');
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');

  // Recurring filter state
  const [recurringFilter, setRecurringFilter] = useState(urlRecurring);
  const [merchantFilter, setMerchantFilter] = useState<string | null>(urlMerchant || null);
  const [recurringMerchants, setRecurringMerchants] = useState<Set<string>>(new Set());

  // Fetch recurring merchants once
  useEffect(() => {
    fetch('http://127.0.0.1:8000/api/recurring')
      .then(r => r.json())
      .then(data => {
        const merchants = new Set<string>((data.recurring || []).map((r: any) => (r.merchant || '').toLowerCase()));
        setRecurringMerchants(merchants);
      })
      .catch(console.error);
  }, []);

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

    fetch(`http://127.0.0.1:8000/api/transactions?${params.toString()}`)
      .then(res => res.json())
      .then(data => {
        setAllTransactions(data.transactions || []);
        setCurrentPage(0);
      })
      .catch(err => console.error("Error fetching transactions: ", err));
  }, [timePreset, urlAccountId]);

  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

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

  // Apply client-side filters
  const filteredTransactions = allTransactions.filter(tx => {
    // Direction filter
    if (directionFilter === 'Income' && (tx.signed_amount ?? tx.amount) <= 0) return false;
    if (directionFilter === 'Expenses' && (tx.signed_amount ?? tx.amount) >= 0) return false;

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
    const amt = Math.abs(tx.signed_amount ?? tx.amount ?? 0);
    if (amountMin !== '' && amt < parseFloat(amountMin)) return false;
    if (amountMax !== '' && amt > parseFloat(amountMax)) return false;

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

    // Recurring filter
    if (recurringFilter) {
      const desc = (tx.description || tx.merchant || '').toLowerCase();
      const merch = (tx.merchant || tx.description || '').toLowerCase();
      const isRecurring = recurringMerchants.has(desc) || recurringMerchants.has(merch);
      if (!isRecurring) return false;
      if (merchantFilter) {
        const mf = merchantFilter.toLowerCase();
        if (!desc.includes(mf) && !merch.includes(mf)) return false;
      }
    }

    return true;
  });

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

  const sortedTransactions = [...filteredTransactions].sort((a, b) => {
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
  });

  // Pagination
  const totalPages = Math.ceil(sortedTransactions.length / PAGE_SIZE);
  const paginatedTransactions = sortedTransactions.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE
  );

  const SortIcon = ({ col }: { col: string }) => (
    <span className={`material-symbols-outlined text-[14px] transition-transform ${sortColumn === col ? 'text-primary' : 'text-slate-400 opacity-0 group-hover/th:opacity-100'}`}>
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
    fetch(`http://127.0.0.1:8000/api/transactions/${selectedTransaction.id}/category?category=${encodeURIComponent(newCategory)}`, {
      method: 'PATCH'
    }).then(() => {
      toast(`Category updated to ${newCategory}`, "success");
    }).catch(() => {
      toast("Failed to update category", "error");
    });
  };

  // Active filter indicator
  const advFilterCount = [categoryFilter, accountFilterAdv, merchantSearch, amountMin || amountMax, customStartDate || customEndDate].filter(Boolean).length;
  const hasActiveFilters = directionFilter || categoryFilter || searchQuery || timePreset !== 'All Time' || urlAccountId || recurringFilter || accountFilterAdv || merchantSearch || amountMin || amountMax || customStartDate || customEndDate;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background overflow-hidden relative">
      <div className="px-12 py-4 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Account Filter Chip (from Accounts page nav) */}
          {urlAccountId && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-500/20 text-sky-600 dark:text-sky-400 border border-sky-500/30 rounded-lg text-xs font-semibold">
              <span className="material-symbols-outlined text-xs">account_balance</span>
              {ACCOUNT_NAMES[urlAccountId] || urlAccountId}
              <button onClick={() => navigate('/transactions')} className="ml-1 hover:text-red-500 transition-colors">
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
                  : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
              }`}
              onClick={() => setShowTimeDropdown(!showTimeDropdown)}
            >
              {timePreset} <span className="material-symbols-outlined text-xs">expand_more</span>
            </button>
            {showTimeDropdown && (
              <div className="absolute top-full left-0 mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-primary/20 rounded-lg shadow-xl z-50 min-w-[160px] py-1 animate-in fade-in slide-in-from-top-2 duration-150">
                {Object.keys(TIME_PRESETS).map(preset => (
                  <button 
                    key={preset}
                    className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-primary/10 transition-colors ${timePreset === preset ? 'text-primary bg-primary/5' : 'text-slate-700 dark:text-slate-300'}`}
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
                ? 'bg-green-500/20 text-green-600 dark:text-green-400 border border-green-500/30'
                : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
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
                ? 'bg-red-500/20 text-red-600 dark:text-red-400 border border-red-500/30'
                : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
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
                ? 'bg-violet-500/20 text-violet-600 dark:text-violet-400 border border-violet-500/30'
                : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
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
                <span className="text-[10px]">Â·</span>
                <span className="truncate max-w-[100px]">{merchantFilter}</span>
                <button onClick={(e) => { e.stopPropagation(); setMerchantFilter(null); }} className="ml-0.5 hover:text-red-500">
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
                  : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
              }`}
              onClick={() => setShowFilterPopover(p => !p)}
            >
              <span className="material-symbols-outlined text-xs">filter_list</span>
              Filter
              {advFilterCount > 0 && (
                <span className="inline-flex items-center justify-center size-4 rounded-full bg-primary text-white text-[10px] font-bold">{advFilterCount}</span>
              )}
              <span className="material-symbols-outlined text-xs">expand_more</span>
            </button>

            {showFilterPopover && (
              <div className="absolute top-full left-0 mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-primary/20 rounded-xl shadow-2xl z-50 w-[340px] animate-in fade-in slide-in-from-top-2 duration-150 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
                  <span className="text-label">Filters</span>
                  {advFilterCount > 0 && (
                    <button
                      className="text-[10px] font-semibold text-slate-400 hover:text-red-500 transition-colors"
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
                              : 'bg-slate-50 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:border-primary/40 hover:text-primary'
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
                                : 'bg-slate-50 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600 hover:border-primary/40 hover:text-primary'
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
                    <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-2">Merchant</p>
                    <div className="relative">
                      <span className="material-symbols-outlined text-xs text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2">search</span>
                      <input
                        type="text"
                        placeholder="Search merchant…"
                        value={merchantSearch}
                        onChange={e => setMerchantSearch(e.target.value)}
                        className="w-full pl-7 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                      />
                    </div>
                  </div>

                  {/* Amount Range */}
                  <div>
                    <p className="text-label mb-2">Amount</p>
                    <div className="flex items-center gap-2">
                      <div className="relative flex-1">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-slate-400 font-bold">$</span>
                        <input
                          type="number"
                          placeholder="Min"
                          value={amountMin}
                          onChange={e => setAmountMin(e.target.value)}
                          className="w-full pl-5 pr-2 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                        />
                      </div>
                      <span className="text-xs text-slate-400 font-bold">—</span>
                      <div className="relative flex-1">
                        <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[10px] text-slate-400 font-bold">$</span>
                        <input
                          type="number"
                          placeholder="Max"
                          value={amountMax}
                          onChange={e => setAmountMax(e.target.value)}
                          className="w-full pl-5 pr-2 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
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
                        className="flex-1 px-2 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
                      />
                      <span className="text-xs text-slate-400 font-bold">—</span>
                      <input
                        type="date"
                        value={customEndDate}
                        onChange={e => setCustomEndDate(e.target.value)}
                        className="flex-1 px-2 py-1.5 text-xs bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all"
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
              className="flex items-center gap-1 px-2 py-1.5 text-xs font-semibold text-slate-500 hover:text-red-500 transition-colors"
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
            <span className="material-symbols-outlined text-sm text-slate-400 absolute left-3 top-1/2 -translate-y-1/2">search</span>
            <input 
              type="text"
              placeholder="Search transactions..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(0); }}
              className="pl-9 pr-4 py-2 bg-slate-100 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[200px]"
            />
          </div>
          <button
            onClick={() => setShowAddDialog(true)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-background-dark rounded-lg text-sm font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] transition-transform"
          >
            <span className="material-symbols-outlined text-sm">add</span> Add Transaction
          </button>
        </div>
      </div>

      <div className="px-12 pb-12 flex-1 overflow-hidden flex flex-col">
        <div className="card-l1 overflow-hidden flex flex-col h-full">
          <div className="flex-1 overflow-auto custom-scrollbar">
            <Table className="w-full relative min-w-[700px]">
              <TableHeader className="bg-slate-50 dark:bg-primary/5 sticky top-0 z-10 shadow-sm">
                <TableRow>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 w-[15%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('posting_date')}><span className="flex items-center gap-1">Date <SortIcon col="posting_date" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 w-[35%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('merchant')}><span className="flex items-center gap-1">Merchant <SortIcon col="merchant" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 w-[20%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('category')}><span className="flex items-center gap-1">Category <SortIcon col="category" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 w-[15%] cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('account')}><span className="flex items-center gap-1">Account <SortIcon col="account" /></span></TableHead>
                  <TableHead className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 w-[15%] text-right cursor-pointer select-none group/th hover:text-primary transition-colors" onClick={() => handleSort('amount')}><span className="flex items-center gap-1 justify-end">Amount <SortIcon col="amount" /></span></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedTransactions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="px-6 py-12 text-center text-slate-400">
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
                    <TableCell className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap">{tx.posting_date}</TableCell>
                    <TableCell className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <TransactionLogo merchantName={tx.merchant || tx.description || 'Unknown'} size="md" />
                        <div className="flex flex-col min-w-0">
                          <span className="text-sm font-bold truncate max-w-[200px] text-slate-900 dark:text-slate-100">
                            {tx.merchant || tx.description}
                          </span>
                          {tx.merchant && tx.description && tx.merchant !== tx.description && (
                            <span className="text-xs text-slate-500 dark:text-slate-400 truncate max-w-[200px]">
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
                    <TableCell className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap">{ACCOUNT_NAMES[tx.account_id] || tx.account_id}</TableCell>
                    <TableCell className="px-6 py-4 text-sm font-bold text-right whitespace-nowrap">
                      <span className={(tx.signed_amount ?? tx.amount) < 0 ? "text-loss text-numeric" : "text-gain text-numeric"}>
                        {(tx.signed_amount ?? tx.amount) < 0 ? "-" : "+"}${Math.abs(tx.signed_amount ?? tx.amount).toFixed(2)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          
          <div className="px-6 py-4 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50/50 dark:bg-background/50 shrink-0">
            <span className="text-xs text-slate-500">
              Showing {paginatedTransactions.length > 0 ? currentPage * PAGE_SIZE + 1 : 0}â€“{Math.min((currentPage + 1) * PAGE_SIZE, sortedTransactions.length)} of {sortedTransactions.length} transactions
              {hasActiveFilters && ` (filtered from ${allTransactions.length})`}
            </span>
            <div className="flex items-center gap-2">
              <button 
                className="px-3 py-1 text-xs border border-slate-200 dark:border-primary/20 rounded-lg hover:bg-primary/5 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
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
                          ? 'bg-primary text-white shadow-sm'
                          : 'text-slate-500 hover:bg-primary/10'
                      }`}
                      onClick={() => setCurrentPage(pageNum)}
                    >
                      {pageNum + 1}
                    </button>
                  );
                })}
              </div>

              <button 
                className="px-3 py-1 text-xs border border-slate-200 dark:border-primary/20 rounded-lg hover:bg-primary/5 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
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
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[420px] p-6 animate-in fade-in zoom-in-95 duration-200" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg">Add Transaction</h3>
              <button onClick={() => setShowAddDialog(false)} className="text-slate-400 hover:text-red-500 transition-colors">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-label mb-1">Description</label>
                <input value={newTx.description} onChange={(e) => setNewTx(p => ({...p, description: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none focus:border-primary/50" placeholder="e.g. Costco Wholesale" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-label mb-1">Amount</label>
                  <input type="number" step="0.01" value={newTx.amount} onChange={(e) => setNewTx(p => ({...p, amount: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none focus:border-primary/50" placeholder="-127.00" />
                </div>
                <div>
                  <label className="block text-label mb-1">Date</label>
                  <input type="date" value={newTx.posting_date} onChange={(e) => setNewTx(p => ({...p, posting_date: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none focus:border-primary/50" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-label mb-1">Category</label>
                  <select value={newTx.category} onChange={(e) => setNewTx(p => ({...p, category: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none cursor-pointer">
                    {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-label mb-1">Account</label>
                  <select value={newTx.account_id} onChange={(e) => setNewTx(p => ({...p, account_id: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm outline-none cursor-pointer">
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
                  fetch('http://127.0.0.1:8000/api/transactions', {
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
                className="flex-1 px-4 py-2.5 bg-primary text-background-dark rounded-lg text-sm font-bold hover:bg-primary/80 transition-colors"
              >Add Transaction</button>
              <button onClick={() => setShowAddDialog(false)} className="px-4 py-2.5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm font-semibold hover:bg-slate-50 transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}

      <Sheet open={!!selectedTransaction} onOpenChange={(open) => !open && setSelectedTransaction(null)}>
        <SheetContent className="w-[380px] sm:w-[420px] border-l border-slate-200 dark:border-slate-800 bg-white dark:bg-background overflow-y-auto">
          <SheetHeader className="border-b border-slate-200 dark:border-primary/10 pb-4 mb-6">
            <SheetTitle>Transaction Details</SheetTitle>
          </SheetHeader>
          
          {selectedTransaction && (
            <div className="space-y-5">
              <div className="text-center space-y-1">
                <div className="size-12 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-3 border border-primary/20">
                  <span className="material-symbols-outlined text-xl text-primary">shopping_bag</span>
                </div>
                <h4 className="text-lg font-bold">{selectedTransaction.description || selectedTransaction.merchant}</h4>
                <p className={`text-2xl font-bold text-numeric ${(selectedTransaction.signed_amount ?? selectedTransaction.amount) < 0 ? 'text-loss' : 'text-gain'}`}>
                  {(selectedTransaction.signed_amount ?? selectedTransaction.amount) < 0 ? '-' : '+'}${Math.abs(selectedTransaction.signed_amount ?? selectedTransaction.amount).toFixed(2)}
                </p>
                <p className="text-xs text-slate-500">{selectedTransaction.posting_date}</p>
              </div>

              <div className="grid grid-cols-2 gap-4 bg-slate-50 dark:bg-primary/5 p-3 rounded-xl border border-slate-200 dark:border-primary/10">
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Status</p>
                  <p className="text-xs font-semibold flex items-center gap-1 mt-0.5">
                    <span className="size-1.5 rounded-full bg-green-500"></span> {selectedTransaction.status}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Account</p>
                  <p className="text-xs font-semibold mt-0.5">{ACCOUNT_NAMES[selectedTransaction.account_id] || selectedTransaction.account_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Institution</p>
                  <p className="text-xs font-semibold mt-0.5">{selectedTransaction.institution_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Category</p>
                  <p className="text-xs font-semibold mt-0.5">{selectedTransaction.category}</p>
                </div>
              </div>

              <div className="space-y-3">
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">Reclassify Category</label>
                <Select value={selectedTransaction.category} onValueChange={handleCategoryChange}>
                  <SelectTrigger className="w-full bg-slate-50 dark:bg-primary/5 h-9 text-sm">
                    <SelectValue placeholder="Select Category" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map(cat => (
                      <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-slate-500">Changes will be applied to this transaction only.</p>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">Recurring</label>
                <button
                  onClick={() => {
                    const merchant = selectedTransaction.description || selectedTransaction.merchant;
                    const isCurrentlyRecurring = recurringMerchants.has((merchant || '').toLowerCase());
                    if (isCurrentlyRecurring) {
                      // Dismiss/unmark recurring
                      const recId = `${selectedTransaction.account_id}__${(merchant || '').toLowerCase().replace(/ /g, '_')}`;
                      fetch(`http://127.0.0.1:8000/api/recurring/${recId}?action=dismiss`, { method: 'PATCH' })
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
                      fetch('http://127.0.0.1:8000/api/recurring/mark', {
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
                      ? 'bg-violet-500/10 text-violet-600 border-violet-500/30 hover:bg-violet-500/20'
                      : 'bg-slate-50 dark:bg-primary/5 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-primary/20 hover:bg-primary/5'
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
                      ? 'bg-violet-500 border-violet-500'
                      : 'border-slate-300 dark:border-slate-600'
                  }`}>
                    {recurringMerchants.has((selectedTransaction.description || selectedTransaction.merchant || '').toLowerCase()) && (
                      <span className="material-symbols-outlined text-white text-[11px]">check</span>
                    )}
                  </div>
                </button>
                <p className="text-[10px] text-slate-500">Toggle to mark/unmark this merchant as a recurring payment.</p>
              </div>

              <div className="space-y-2">
                <label className="block text-xs font-bold text-slate-700 dark:text-slate-300">Receipt Image</label>
                <div className="h-20 w-full rounded-lg border-2 border-dashed border-slate-200 dark:border-primary/20 flex items-center justify-center gap-2 hover:bg-primary/5 cursor-pointer transition-colors group">
                  <span className="material-symbols-outlined text-sm text-slate-400 group-hover:text-primary transition-colors">add_a_photo</span>
                  <span className="text-xs text-slate-500 font-medium">Upload receipt</span>
                </div>
              </div>

              <div className="flex gap-3 pt-4 border-t border-slate-200 dark:border-primary/10">
                <Button className="flex-1 bg-primary text-background-dark font-bold hover:bg-primary/80" onClick={() => setSelectedTransaction(null)}>
                  Save Changes
                </Button>
                <Button variant="outline" className="text-red-500 border-red-500/30 hover:bg-red-500/10">Delete</Button>
              </div>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}