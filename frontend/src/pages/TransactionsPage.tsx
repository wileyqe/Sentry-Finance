import { useState, useEffect, useCallback, useRef } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
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

// Map account IDs to display names
const ACCOUNT_NAMES: Record<string, string> = {
  chase_chk_001: 'Chase Total Checking',
  nfcu_sav_001: 'NFCU Emergency Savings',
  chase_cc_001: 'Sapphire Reserve',
  amex_cc_001: 'Blue Cash Preferred',
  rocket_mtg_001: 'Home Mortgage',
  fidelity_inv_001: 'Individual Brokerage',
  acorns_inv_001: 'Acorns Invest',
};

const PAGE_SIZE = 25;

const CATEGORIES = [
  'Income', 'Mortgage', 'Transfer', 'Groceries', 'Dining', 'Shopping',
  'Entertainment', 'Travel', 'Utilities', 'Auto', 'Medical', 'Insurance',
  'Home Improvement', 'Uncategorized',
];

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
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const urlAccountId = searchParams.get('account_id');
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
  const [showCategoryDropdown, setShowCategoryDropdown] = useState(false);
  const timeDropdownRef = useRef<HTMLDivElement>(null);
  const categoryDropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (timeDropdownRef.current && !timeDropdownRef.current.contains(e.target as Node)) {
        setShowTimeDropdown(false);
      }
      if (categoryDropdownRef.current && !categoryDropdownRef.current.contains(e.target as Node)) {
        setShowCategoryDropdown(false);
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

    // Category filter
    if (categoryFilter && tx.category !== categoryFilter) return false;

    // Search filter (description, merchant, category, account)
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
    }).catch(err => console.error("Failed to update category", err));
  };

  // Active filter indicator
  const hasActiveFilters = directionFilter || categoryFilter || searchQuery || timePreset !== 'All Time' || urlAccountId;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-hidden relative">
      <div className="px-8 py-4 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Account Filter Chip (from Accounts page nav) */}
          {urlAccountId && (
            <div className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-500/20 text-sky-600 dark:text-sky-400 border border-sky-500/30 rounded-lg text-xs font-semibold">
              <span className="material-symbols-outlined text-xs">account_balance</span>
              {ACCOUNT_NAMES[urlAccountId] || urlAccountId}
              <a href="/transactions" className="ml-1 hover:text-red-500 transition-colors">
                <span className="material-symbols-outlined text-xs">close</span>
              </a>
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

          {/* Category Dropdown */}
          <div className="relative" ref={categoryDropdownRef}>
            <button 
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                categoryFilter
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'bg-slate-100 dark:bg-primary/5 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-primary/20'
              }`}
              onClick={() => setShowCategoryDropdown(!showCategoryDropdown)}
            >
              {categoryFilter || 'Category'} <span className="material-symbols-outlined text-xs">expand_more</span>
            </button>
            {showCategoryDropdown && (
              <div className="absolute top-full left-0 mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-primary/20 rounded-lg shadow-xl z-50 min-w-[180px] py-1 max-h-[300px] overflow-y-auto custom-scrollbar animate-in fade-in slide-in-from-top-2 duration-150">
                <button 
                  className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-primary/10 transition-colors ${!categoryFilter ? 'text-primary bg-primary/5' : 'text-slate-700 dark:text-slate-300'}`}
                  onClick={() => { setCategoryFilter(null); setShowCategoryDropdown(false); }}
                >
                  All Categories
                </button>
                {CATEGORIES.map(cat => (
                  <button 
                    key={cat}
                    className={`w-full text-left px-4 py-2 text-xs font-semibold hover:bg-primary/10 transition-colors ${categoryFilter === cat ? 'text-primary bg-primary/5' : 'text-slate-700 dark:text-slate-300'}`}
                    onClick={() => { setCategoryFilter(cat); setShowCategoryDropdown(false); }}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Clear Filters */}
          {hasActiveFilters && (
            <button 
              className="flex items-center gap-1 px-2 py-1.5 text-xs font-semibold text-slate-500 hover:text-red-500 transition-colors"
              onClick={() => {
                setTimePreset('All Time');
                setDirectionFilter(null);
                setCategoryFilter(null);
                setSearchQuery('');
                setCurrentPage(0);
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
          <button className="flex items-center gap-2 px-4 py-2 bg-primary text-background-dark rounded-lg text-sm font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] transition-transform">
            <span className="material-symbols-outlined text-sm">add</span> Add Transaction
          </button>
        </div>
      </div>

      <div className="px-8 pb-8 flex-1 overflow-hidden flex flex-col">
        <div className="border border-slate-200 dark:border-primary/10 rounded-xl overflow-hidden bg-white dark:bg-background-dark/30 flex flex-col h-full">
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
                    className="group hover:bg-primary/5 cursor-pointer transition-colors"
                    onClick={() => setSelectedTransaction(tx)}
                  >
                    <TableCell className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap">{tx.posting_date}</TableCell>
                    <TableCell className="px-6 py-4 text-sm font-bold truncate max-w-[200px]">{tx.description || tx.merchant}</TableCell>
                    <TableCell className="px-6 py-4">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary/10 text-primary border border-primary/20 whitespace-nowrap`}>
                        {tx.category}
                      </span>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400 whitespace-nowrap">{ACCOUNT_NAMES[tx.account_id] || tx.account_id}</TableCell>
                    <TableCell className="px-6 py-4 text-sm font-bold text-right whitespace-nowrap">
                      <span className={(tx.signed_amount ?? tx.amount) < 0 ? "text-red-500" : "text-green-500"}>
                        {(tx.signed_amount ?? tx.amount) < 0 ? "-" : "+"}${Math.abs(tx.signed_amount ?? tx.amount).toFixed(2)}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          
          <div className="px-6 py-4 border-t border-slate-200 dark:border-primary/10 flex items-center justify-between bg-slate-50/50 dark:bg-background-dark/50 shrink-0">
            <span className="text-xs text-slate-500">
              Showing {paginatedTransactions.length > 0 ? currentPage * PAGE_SIZE + 1 : 0}–{Math.min((currentPage + 1) * PAGE_SIZE, sortedTransactions.length)} of {sortedTransactions.length} transactions
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
      
      <Sheet open={!!selectedTransaction} onOpenChange={(open) => !open && setSelectedTransaction(null)}>
        <SheetContent className="w-[400px] sm:w-[540px] border-l border-slate-200 dark:border-primary/20 bg-white dark:bg-background-dark overflow-y-auto">
          <SheetHeader className="border-b border-slate-200 dark:border-primary/10 pb-4 mb-6">
            <SheetTitle>Transaction Details</SheetTitle>
          </SheetHeader>
          
          {selectedTransaction && (
            <div className="space-y-8">
              <div className="text-center space-y-2">
                <div className="size-16 bg-primary/10 rounded-full flex items-center justify-center mx-auto mb-4 border border-primary/20">
                  <span className="material-symbols-outlined text-3xl text-primary">shopping_bag</span>
                </div>
                <h4 className="text-2xl font-bold">{selectedTransaction.description || selectedTransaction.merchant}</h4>
                <p className={`text-3xl font-bold ${(selectedTransaction.signed_amount ?? selectedTransaction.amount) < 0 ? 'text-red-500' : 'text-green-500'}`}>
                  {(selectedTransaction.signed_amount ?? selectedTransaction.amount) < 0 ? '-' : '+'}${Math.abs(selectedTransaction.signed_amount ?? selectedTransaction.amount).toFixed(2)}
                </p>
                <p className="text-sm text-slate-500">{selectedTransaction.posting_date}</p>
              </div>

              <div className="grid grid-cols-2 gap-6 bg-slate-50 dark:bg-primary/5 p-4 rounded-xl border border-slate-200 dark:border-primary/10">
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Status</p>
                  <p className="text-sm font-semibold flex items-center gap-1.5 mt-1">
                    <span className="size-2 rounded-full bg-green-500"></span> {selectedTransaction.status}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Account</p>
                  <p className="text-sm font-semibold mt-1">{ACCOUNT_NAMES[selectedTransaction.account_id] || selectedTransaction.account_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Institution</p>
                  <p className="text-sm font-semibold mt-1">{selectedTransaction.institution_id}</p>
                </div>
                <div>
                  <p className="text-[10px] uppercase font-bold text-slate-500 tracking-wider">Category</p>
                  <p className="text-sm font-semibold mt-1">{selectedTransaction.category}</p>
                </div>
              </div>

              <div className="space-y-4">
                <label className="block text-sm font-bold text-slate-700 dark:text-slate-300">Reclassify Category</label>
                <Select value={selectedTransaction.category} onValueChange={handleCategoryChange}>
                  <SelectTrigger className="w-full bg-slate-50 dark:bg-primary/5">
                    <SelectValue placeholder="Select Category" />
                  </SelectTrigger>
                  <SelectContent>
                    {CATEGORIES.map(cat => (
                      <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-[10px] text-slate-500">Changes will be applied to this transaction only. To create a rule, visit Settings.</p>
              </div>

              <div className="space-y-3">
                <label className="block text-sm font-bold text-slate-700 dark:text-slate-300">Receipt Image</label>
                <div className="aspect-video w-full rounded-xl border-2 border-dashed border-slate-200 dark:border-primary/20 flex flex-col items-center justify-center gap-2 hover:bg-primary/5 cursor-pointer transition-colors group">
                  <span className="material-symbols-outlined text-slate-400 group-hover:text-primary transition-colors">add_a_photo</span>
                  <span className="text-xs text-slate-500 font-medium">Click to upload receipt</span>
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
