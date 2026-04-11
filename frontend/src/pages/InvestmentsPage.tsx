/**
 * Investments — Tab container with sticky navigation bar.
 *
 * Manages tab (Overview/Holdings/Allocation), timeframe, and account
 * filter state. Renders the active tab component with those props.
 */

import { useState, useMemo } from "react";
import { useView } from "../context/ViewContext";
import { useAccounts } from "@/lib/accounts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { motion } from "framer-motion";
import InvestmentsOverview from "./InvestmentsOverview";
import InvestmentsHoldings from "./InvestmentsHoldings";
import InvestmentsAllocation from "./InvestmentsAllocation";

/* ── Animation (shared pattern) ───────────────────────────────────────────── */

const springTransition: any = { type: "spring", stiffness: 300, damping: 30 };
const containerVariants = { hidden: { opacity: 0 }, visible: { opacity: 1, transition: { staggerChildren: 0.05 } } };
const itemVariants = { hidden: { opacity: 0, y: 10 }, visible: { opacity: 1, y: 0, transition: springTransition } };

/* ── Constants ────────────────────────────────────────────────────────────── */

type InvestmentsTab = "overview" | "holdings" | "allocation";
type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

const TABS: { value: InvestmentsTab; label: string }[] = [
  { value: "overview",   label: "Overview" },
  { value: "holdings",   label: "Holdings" },
  { value: "allocation", label: "Allocation" },
];

const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "All"];

/* ── Component ────────────────────────────────────────────────────────────── */

export default function InvestmentsPage() {
  useView();
  const { accounts } = useAccounts();

  const [activeTab, setActiveTab] = useState<InvestmentsTab>("overview");
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");
  const [accountFilter, setAccountFilter] = useState("all");

  // Only show investment/retirement accounts in the filter dropdown
  const investmentAccounts = useMemo(
    () => accounts.filter((a) => a.type === "investment" || a.type === "retirement"),
    [accounts]
  );

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar"
    >

      {/* ── Sticky Nav Bar ──────────────────────────────────────────────── */}
      <motion.div
        variants={itemVariants}
        className="sticky top-0 z-20 bg-background border-b border-border px-12 py-3 flex items-center justify-between gap-4"
      >
        {/* Left: Title + Tab pills */}
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-bold tracking-tight">Investments</h1>

          <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5">
            {TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => setActiveTab(tab.value)}
                className={`px-4 py-1.5 rounded-full text-[12.5px] font-semibold transition-all duration-150 ${
                  activeTab === tab.value
                    ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Right: Timeframe pills + Account filter */}
        <div className="flex items-center gap-3">
          {/* Timeframe pills */}
          <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf}
                onClick={() => setTimeframe(tf)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                  timeframe === tf
                    ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Account filter */}
          <Select
            value={accountFilter}
            onValueChange={(val: string | null) => {
              if (val) setAccountFilter(val);
            }}
          >
            <SelectTrigger className="w-[180px] h-8 text-xs font-semibold bg-white dark:bg-slate-800">
              <SelectValue placeholder="All Accounts" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Accounts</SelectItem>
              {investmentAccounts.map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </motion.div>

      {/* ── Tab Content ─────────────────────────────────────────────────── */}
      <motion.div variants={itemVariants} className="flex-1 px-12 py-6">
        {activeTab === "overview" && (
          <InvestmentsOverview timeframe={timeframe} accountFilter={accountFilter} />
        )}
        {activeTab === "holdings" && (
          <InvestmentsHoldings timeframe={timeframe} accountFilter={accountFilter} />
        )}
        {activeTab === "allocation" && (
          <InvestmentsAllocation timeframe={timeframe} accountFilter={accountFilter} />
        )}
      </motion.div>
    </motion.div>
  );
}
