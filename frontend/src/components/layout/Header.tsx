import { useState } from "react";
import { useLocation } from "react-router-dom";

const PAGE_META: Record<string, { label: string; icon: string; description: string }> = {
  dashboard:    { label: "Dashboard",    icon: "dashboard",      description: "Your financial overview" },
  transactions: { label: "Transactions", icon: "receipt_long",   description: "All account activity" },
  reports:      { label: "Reports",      icon: "assessment",     description: "Insights & cash flow" },
  accounts:     { label: "Accounts",     icon: "account_balance",description: "Balances & net worth" },
  budgets:      { label: "Budgets",      icon: "pie_chart",      description: "Spending limits & goals" },
  investments:  { label: "Investments",  icon: "trending_up",    description: "Portfolio performance" },
};

const now = new Date();
const dateStr = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

const Header = () => {
  const location = useLocation();
  const path = location.pathname.substring(1) || "dashboard";
  const meta = PAGE_META[path] ?? { label: path.charAt(0).toUpperCase() + path.slice(1), icon: "circle", description: "" };

  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = () => {
    if (refreshing) return;
    setRefreshing(true);
    // TODO: call backend refresh endpoint when live data is connected
    // e.g. fetch("/api/refresh-all", { method: "POST" })
    setTimeout(() => setRefreshing(false), 1500);
  };

  return (
    <header className="h-16 border-b border-slate-200 dark:border-slate-800/80 flex items-center justify-between px-6 bg-white/80 dark:bg-[#060608]/90 backdrop-blur-sm sticky top-0 z-10 shrink-0">
      {/* Page title */}
      <div className="flex items-center gap-3">
        <div className="size-8 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-emerald-500 text-[18px]">{meta.icon}</span>
        </div>
        <div>
          <h2 className="text-[15px] font-bold text-slate-900 dark:text-slate-50 leading-tight">{meta.label}</h2>
          {meta.description && (
            <p className="text-[10px] text-slate-400 font-medium uppercase tracking-wider leading-none mt-0.5">{meta.description}</p>
          )}
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3">
        {/* Date pill */}
        <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50">
          <span className="material-symbols-outlined text-slate-400 text-[13px]">calendar_today</span>
          <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">{dateStr}</span>
        </div>

        {/* Search */}
        <div className="relative hidden md:block">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[15px]">search</span>
          <input
            className="w-52 pl-9 pr-4 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50 rounded-xl text-[13px] outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all duration-200 placeholder:text-slate-400 dark:text-slate-200"
            placeholder="Search..."
            type="text"
          />
        </div>

        {/* ── Refresh All Accounts ─────────────────────────────────────── */}
        <button
          aria-label="Refresh all accounts"
          title="Refresh all accounts"
          onClick={handleRefresh}
          disabled={refreshing}
          className={`
            relative size-9 flex items-center justify-center rounded-xl
            border transition-all duration-150
            ${refreshing
              ? "bg-emerald-50 dark:bg-emerald-500/15 border-emerald-400/50 text-emerald-500 cursor-not-allowed"
              : "bg-slate-50 dark:bg-slate-800/60 border-slate-200 dark:border-slate-700/50 text-slate-500 dark:text-slate-400 hover:text-emerald-500 hover:border-emerald-500/30 hover:bg-emerald-50 dark:hover:bg-emerald-500/10"
            }
          `}
        >
          <span
            className={`material-symbols-outlined text-[18px]${refreshing ? " animate-spin" : ""}`}
          >
            sync
          </span>
          {/* Ripple ring while refreshing */}
          {refreshing && (
            <span className="absolute inset-0 rounded-xl ring-2 ring-emerald-400/40 animate-ping pointer-events-none" />
          )}
        </button>

        {/* Notifications */}
        <button
          aria-label="Notifications"
          className="relative size-9 flex items-center justify-center rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50 text-slate-500 dark:text-slate-400 hover:text-emerald-500 hover:border-emerald-500/30 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 transition-all duration-150"
        >
          <span className="material-symbols-outlined text-[18px]">notifications</span>
          {/* Unread dot */}
          <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-emerald-500" />
        </button>
      </div>
    </header>
  );
};

export default Header;
