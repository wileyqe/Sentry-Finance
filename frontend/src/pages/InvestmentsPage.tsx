/**
 * Investments — Tab container with sticky navigation bar.
 *
 * Manages tab (Overview/Holdings/Allocation), timeframe, and account
 * filter state. Renders the active tab component with those props.
 */

import { useMemo } from "react";
import { useView } from "../context/ViewContext";
import { useAccounts } from "@/lib/accounts";
import { useSessionState } from "@/hooks/useSessionState";
// Select removed — replaced by toggle chips for account filtering
import SyntheticBadge from "@/components/ui/SyntheticBadge";
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

  const [activeTab, setActiveTab] = useSessionState<InvestmentsTab>("investments:activeTab", "overview");
  const [timeframe, setTimeframe] = useSessionState<Timeframe>("investments:timeframe", "3M");
  const [accountFilter, setAccountFilter] = useSessionState("investments:accountFilter", "all");
  const [xrayMode, setXrayMode] = useSessionState<boolean>("investments:xrayMode", false);

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
        {/* Left: Tab pills (page title lives in global Header) */}
        <div className="flex items-center gap-6">
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

        {/* Right: X-Ray toggle + Timeframe pills + Account chips */}
        <div className="flex items-center gap-3">
          {/* X-Ray mode toggle */}
          <div className="flex items-center gap-0.5 bg-slate-100 dark:bg-slate-800/60 rounded-full p-0.5">
            <button
              onClick={() => setXrayMode(false)}
              className={`px-3 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 ${
                !xrayMode
                  ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              Holdings
            </button>
            <button
              onClick={() => setXrayMode(true)}
              className={`px-3 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 flex items-center gap-1 ${
                xrayMode
                  ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <span className="material-symbols-outlined text-[13px]">radiology</span>
              X-Ray
            </button>
          </div>

          {/* Timeframe pills — hidden on Holdings (always current snapshot) */}
          {activeTab !== "holdings" && (
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
          )}

          {/* Account filter chips (multi-select) */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setAccountFilter("all")}
              className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 border ${
                accountFilter === "all"
                  ? "bg-foreground text-background border-foreground"
                  : "bg-transparent text-muted-foreground border-border hover:text-foreground hover:border-foreground/50"
              }`}
            >
              All
            </button>
            {investmentAccounts.map((a) => (
              <button
                key={a.id}
                onClick={() => setAccountFilter(accountFilter === a.id ? "all" : a.id)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-all duration-150 border flex items-center gap-1 ${
                  accountFilter === a.id
                    ? "bg-foreground text-background border-foreground"
                    : "bg-transparent text-muted-foreground border-border hover:text-foreground hover:border-foreground/50"
                }`}
              >
                {a.name.replace(/\s*(Synthetic|Brokerage|Uniformed Services)\s*/gi, "").trim() || a.name}
                {!!a.is_synthetic && <SyntheticBadge compact />}
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      {/* ── Tab Content ─────────────────────────────────────────────────── */}
      <motion.div variants={itemVariants} className="flex-1 px-12 py-6">
        {activeTab === "overview" && (
          <InvestmentsOverview timeframe={timeframe} accountFilter={accountFilter} xrayMode={xrayMode} />
        )}
        {activeTab === "holdings" && (
          <InvestmentsHoldings timeframe={timeframe} accountFilter={accountFilter} />
        )}
        {activeTab === "allocation" && (
          <InvestmentsAllocation timeframe={timeframe} accountFilter={accountFilter} xrayMode={xrayMode} />
        )}
      </motion.div>
    </motion.div>
  );
}
