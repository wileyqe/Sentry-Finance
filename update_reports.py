
import re

with open('frontend/src/pages/ReportsPage.tsx', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Imports
code = code.replace(
    'import CustomReportsTab from "../components/CustomReportsTab";',
    'import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";'
)

# 2. State & Hooks block
def state_repl(match):
    return '''export default function ReportsPage() {
  const [timeframe, setTimeframe] = useState("Last 3 Months");
  const [accountIdFilter, setAccountIdFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [merchantFilter, setMerchantFilter] = useState<string>("");
  const [tagFilter, setTagFilter] = useState<string>("");

  const [flowData, setFlowData] = useState<any>(null);
  const [transactions, setTransactions] = useState<any[]>([]);
  const [activeFilter, setActiveFilter] = useState<{ name: string; side: string } | null>(null);
  const [editingTxId, setEditingTxId] = useState<string | null>(null);
  const txListRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(1000);
  const chartContainerRef = useRef<HTMLDivElement>(null);

  // Responsive width
  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      for (const e of entries) setContainerWidth(e.contentRect.width);
    });
    if (chartContainerRef.current) obs.observe(chartContainerRef.current);
    return () => obs.disconnect();
  }, []);

  // Fetch flow data
  const fetchFlow = useCallback(() => {
    const months = TF_MAP[timeframe] || 1;
    let url = `http://127.0.0.1:8000/api/reports/flow?months=${months}`;
    if (accountIdFilter) url += `&account_id=${accountIdFilter}`;
    fetch(url)
      .then(r => r.json())
      .then(setFlowData)
      .catch(console.error);
  }, [timeframe, accountIdFilter]);
  useEffect(() => { fetchFlow(); }, [fetchFlow]);

  // Fetch transactions for the period
  const fetchTransactions = useCallback(() => {
    const months = TF_MAP[timeframe] || 1;
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    const sd = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-01`;
    const ed = `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`;
    let url = `http://127.0.0.1:8000/api/transactions?limit=1000&start_date=${sd}&end_date=${ed}`;
    if (accountIdFilter) url += `&account_id=${accountIdFilter}`;
    fetch(url)
      .then(r => r.json())
      .then(d => setTransactions(d.transactions || []))
      .catch(console.error);
  }, [timeframe, accountIdFilter]);
  useEffect(() => { fetchTransactions(); }, [fetchTransactions]);

  /* ── Build Sankey node data ─────────────────────────────────────────────── */'''

code = re.sub(r'export default function ReportsPage\(\) \{[\s\S]*?/\* ── Build Sankey node data ──+ \*/', state_repl, code)

# 3. filteredTx block
filteredTx_new = '''  /* ── Filtered transactions ──────────────────────────────────────────────── */
  const filteredTx = useMemo(() => {
    return transactions.filter(tx => {
      // 1. Sankey filter
      if (activeFilter) {
        if (activeFilter.name === "Savings") return false;
        const amt = tx.signed_amount ?? tx.amount;
        if (activeFilter.side === "income") {
          if (!(amt >= 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Other Income")))) return false;
        } else {
          if (!(amt < 0 && (tx.category === activeFilter.name || (!tx.category && activeFilter.name === "Uncategorized")))) return false;
        }
      }

      // 2. Category filter
      if (categoryFilter && tx.category !== categoryFilter) return false;

      // 3. Merchant filter
      if (merchantFilter) {
        const q = merchantFilter.toLowerCase();
        const desc = (tx.description || tx.merchant || "").toLowerCase();
        if (!desc.includes(q)) return false;
      }

      // 4. Tag filter
      if (tagFilter) {
        const q = tagFilter.toLowerCase();
        const desc = (tx.description || tx.merchant || tx.raw_description || "").toLowerCase();
        if (!desc.includes(`#${q}`) && !desc.includes(q)) return false;
      }

      return true;
    });
  }, [transactions, activeFilter, categoryFilter, merchantFilter, tagFilter]);

  // Auto-scroll when filter changes'''

# Target up to `// Auto-scroll when filter changes` precisely
code = re.sub(r'  /\* ── Filtered transactions ──+ \*/[\s\S]*?// Auto-scroll when filter changes', filteredTx_new, code)


# 4. Use `months` in timeLabel so we don't get the 'months is not defined' error
timeLabel_repl = '''  /* ── Timeframe label ────────────────────────────────────────────────────── */
  const timeLabel = useMemo(() => {
    const months = TF_MAP[timeframe] || 1;
    const end = new Date();
    const start = new Date();
    start.setMonth(start.getMonth() - months);
    const fmtDate = (d: Date) => `${d.toLocaleString("en-US", { month: "short" })} ${d.getDate()}, ${d.getFullYear()}`;
    return `${fmtDate(start)} – ${fmtDate(end)}`;
  }, [timeframe]);'''

code = re.sub(r'  /\* ── Timeframe label ──+ \*/[\s\S]*?\}, \[timeframe\]\);', timeLabel_repl, code)


# 5. UI replacements — Top level return
ui_repl = '''  const hasActiveFilters = accountIdFilter || categoryFilter || merchantFilter || tagFilter || timeframe !== "Last 3 Months";

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background-light dark:bg-background-dark overflow-auto custom-scrollbar">

      {/* ── Page header with Filter Bar ──────────────────────────────────── */}
      <div className="px-6 py-4 flex flex-col gap-4 border-b border-slate-100 dark:border-slate-800 sticky top-0 bg-background-light dark:bg-background-dark z-10">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold">Cash Flow Reports</h2>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Timeframe Filter */}
          <Select value={timeframe} onValueChange={(val) => { setTimeframe(val); setActiveFilter(null); }}>
            <SelectTrigger className="w-[160px] h-9 text-xs font-semibold bg-white dark:bg-slate-800">
              <SelectValue placeholder="Timeframe" />
            </SelectTrigger>
            <SelectContent>
              {Object.keys(TF_MAP).map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
            </SelectContent>
          </Select>

          {/* Account Filter */}
          <Select value={accountIdFilter || "ALL"} onValueChange={(val: string) => { setAccountIdFilter(val === "ALL" ? "" : val); setActiveFilter(null); }}>
            <SelectTrigger className="w-[200px] h-9 text-xs font-semibold bg-white dark:bg-slate-800">
              <SelectValue placeholder="All Accounts" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Accounts</SelectItem>
              {Object.entries(ACCOUNT_NAMES).map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}
            </SelectContent>
          </Select>

          {/* Category Filter */}
          <Select value={categoryFilter || "ALL"} onValueChange={(val: string) => { setCategoryFilter(val === "ALL" ? "" : val); }}>
            <SelectTrigger className="w-[180px] h-9 text-xs font-semibold bg-white dark:bg-slate-800">
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Categories</SelectItem>
              {CATEGORIES.map(cat => <SelectItem key={cat} value={cat}>{cat}</SelectItem>)}
            </SelectContent>
          </Select>

          {/* Merchant Input */}
          <div className="relative">
            <span className="material-symbols-outlined text-sm text-slate-400 absolute left-3 top-1/2 -translate-y-1/2">storefront</span>
            <input 
              type="text"
              placeholder="Merchant..."
              value={merchantFilter}
              onChange={(e) => setMerchantFilter(e.target.value)}
              className="pl-9 pr-4 h-9 bg-white dark:bg-slate-800 border border-slate-200 dark:border-primary/20 rounded-md text-xs font-semibold outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[160px]"
            />
          </div>

          {/* Tags Input */}
          <div className="relative">
            <span className="material-symbols-outlined text-sm text-slate-400 absolute left-3 top-1/2 -translate-y-1/2">sell</span>
            <input 
              type="text"
              placeholder="Tags (e.g. vacation)"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              className="pl-9 pr-4 h-9 bg-white dark:bg-slate-800 border border-slate-200 dark:border-primary/20 rounded-md text-xs font-semibold outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20 transition-all w-[180px]"
            />
          </div>

          {/* Clear Filters */}
          {hasActiveFilters && (
            <button 
              className="flex items-center gap-1 px-3 h-9 text-xs font-semibold text-slate-500 hover:text-red-500 transition-colors bg-slate-50 dark:bg-slate-800/50 rounded-md border border-slate-200 dark:border-slate-700"
              onClick={() => {
                setTimeframe("Last 3 Months");
                setAccountIdFilter("");
                setCategoryFilter("");
                setMerchantFilter("");
                setTagFilter("");
                setActiveFilter(null);
              }}
            >
              <span className="material-symbols-outlined text-xs">close</span>
              Clear
            </button>
          )}

        </div>
      </div>

      {/* ── Summary cards row ──────────────────────────────────────────────── */}'''

code = re.sub(r'  return \(\s*<div className="flex-1 flex flex-col min-w-0[^\n]*\n[\s\S]*?/\* ── Summary cards row ──+ \*/', ui_repl, code)

# 6. Delete old Cash flow tag checks and Custom Reports
# 6A. Remove the `      {reportTab === "custom_reports" && ( ... )}` chunk entirely
code = re.sub(r'      \{\/\* ── Custom Reports Tab ──+ \*/\}\n      \{reportTab === "custom_reports" && \(\n        <div className="pt-4">\n          <CustomReportsTab timeframe=\{timeframe\} />\n        </div>\n      \)\}\n\n', '', code)

# 6B. Remove the `      {reportTab === "cash_flow" && (` logic completely without destroying the contents
code = re.sub(r'      \{\/\* ── Cash Flow Tab ──+ \*/\}\n      \{reportTab === "cash_flow" && \(\n      <>\n', '', code)

# 6C. Cleanup the ending brackets from the cash flow tab checks.
code = code.replace('      </>\n      )}\n    </div>\n  );\n}\n', '    </div>\n  );\n}\n')


o_b = code.count('{')
c_b = code.count('}')
o_p = code.count('(')
c_p = code.count(')')
o_br = code.count('[')
c_br = code.count(']')
print(f'AST check: {{ }} => {o_b} {c_b} | () => {o_p} {c_p} | [] => {o_br} {c_br}')


with open('frontend/src/pages/ReportsPage.tsx', 'w', encoding='utf-8') as f:
    f.write(code)
