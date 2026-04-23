import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

const PAGE_META: Record<string, { label: string; icon: string; description: string }> = {
  "dashboard":       { label: "Dashboard",       icon: "dashboard",       description: "Your financial overview" },
  "transactions":    { label: "Transactions",    icon: "receipt_long",    description: "All account activity" },
  "reports":         { label: "Reports",         icon: "assessment",      description: "Insights & cash flow" },
  "accounts":        { label: "Accounts",        icon: "account_balance", description: "Balances & net worth" },
  "budgets":         { label: "Budgets",         icon: "pie_chart",       description: "Spending limits & goals" },
  "investments":     { label: "Investments",     icon: "trending_up",     description: "Portfolio performance" },
  "cash-flow":       { label: "Cash Flow",       icon: "swap_horiz",      description: "Income vs. spending trends" },
  "review/monthly":  { label: "Monthly Review",  icon: "calendar_month",  description: "Month-over-month analysis" },
  "review/yearly":   { label: "Yearly Wrap-Up",  icon: "event_note",      description: "Annual financial summary" },
  "settings":        { label: "Settings",        icon: "settings",        description: "App configuration" },
  "documents":       { label: "Documents",       icon: "description",     description: "Upload & manage documents" },
};

const now = new Date();
const dateStr = now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

const Header = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const path = location.pathname.substring(1) || "dashboard";
  // Try full path first (e.g. "review/monthly"), then first segment only
  const meta = PAGE_META[path]
    ?? PAGE_META[path.split("/")[0]]
    ?? { label: path.charAt(0).toUpperCase() + path.slice(1), icon: "circle", description: "" };

  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showNotifications, setShowNotifications] = useState(false);

  useEffect(() => {
    if (!showNotifications) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowNotifications(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showNotifications]);

  const handleRefresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    try {
      // Dev mode: advance the rolling synthetic dataset by one day.
      // The seeder also re-runs the post-commit pipeline so derived
      // metrics, recurring detection, and reconciliation refresh
      // alongside the new transactions. Replace this with a real
      // refresh-all entrypoint when live institutions are wired.
      const res = await fetch("/api/dev/advance-dummy-data", { method: "POST" });
      if (!res.ok) throw new Error(`refresh failed (${res.status})`);
      // Force a hard reload so every useOwnerApi caller refetches.
      // (The backend also broadcasts a refresh_complete SSE event for
      // any subscribers, but a window reload is the simplest way to
      // pull the new dataset everywhere consistently.)
      window.location.reload();
    } catch (e) {
      console.error("refresh failed", e);
      setRefreshing(false);
    }
    // Note: on success the page reloads, so we never clear `refreshing`.
  };

  return (
    <header className="h-16 border-b border-slate-200 dark:border-slate-800/80 flex items-center justify-between px-6 bg-background/80 backdrop-blur-sm sticky top-0 z-10 shrink-0">
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
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-[15px]" aria-hidden="true">search</span>
          <input
            className="w-52 pl-9 pr-4 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50 rounded-xl text-[13px] outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/50 transition-all duration-200 placeholder:text-slate-400 dark:text-slate-200"
            placeholder="Search..."
            aria-label="Search transactions"
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && searchQuery.trim()) {
                navigate(`/transactions?search=${encodeURIComponent(searchQuery.trim())}`);
                setSearchQuery("");
              }
            }}
          />
        </div>

        {/* ── Refresh All Accounts ─────────────────────────────────────── */}
        <button
          aria-label="Refresh all accounts"
          title="Refresh all accounts"
          onClick={handleRefresh}
          disabled={refreshing}
          className={`
            focus-ring relative size-9 flex items-center justify-center rounded-xl
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
        <div className="relative">
          <button
            aria-label="Notifications"
            onClick={() => setShowNotifications(!showNotifications)}
            className="focus-ring relative size-9 flex items-center justify-center rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/50 text-slate-500 dark:text-slate-400 hover:text-emerald-500 hover:border-emerald-500/30 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 transition-all duration-150"
          >
            <span className="material-symbols-outlined text-[18px]">notifications</span>
          </button>
          {showNotifications && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowNotifications(false)} />
              <div className="absolute right-0 top-11 w-72 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg z-50 overflow-hidden">
                <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800">
                  <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Notifications</h4>
                </div>
                {/*
                  TODO: Wire to a real notification feed.
                  Tracked in docs/ROADMAP.md → "Notification feed"
                  action item. Decide producers (refresh failures,
                  threshold breaches, upcoming bills) before populating.
                */}
                <div className="flex flex-col items-center justify-center py-8 px-4">
                  <span className="material-symbols-outlined text-2xl text-slate-300 dark:text-slate-600 mb-2">notifications_off</span>
                  <p className="text-sm text-slate-400">No notifications</p>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;
