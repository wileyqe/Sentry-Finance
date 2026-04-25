import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import NotificationPopover from "@/components/Notifications/NotificationPopover";
import ThemeToggle from "@/components/ui/ThemeToggle";

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
    <header className="h-16 border-b border-border flex items-center justify-between px-6 bg-background/80 backdrop-blur-sm sticky top-0 z-10 shrink-0">
      {/* Page title */}
      <div className="flex items-center gap-3">
        <div className="size-8 rounded-lg bg-primary/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary text-[18px]">{meta.icon}</span>
        </div>
        <div>
          <h2 className="text-[15px] font-bold text-foreground leading-tight">{meta.label}</h2>
          {meta.description && (
            <p className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider leading-none mt-0.5">{meta.description}</p>
          )}
        </div>
      </div>

      {/* Right side */}
      <div className="flex items-center gap-3">
        {/* Date pill */}
        <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-raised dark:bg-surface-raised border border-border">
          <span className="material-symbols-outlined text-muted-foreground text-[13px]">calendar_today</span>
          <span className="text-[11px] font-medium text-muted-foreground">{dateStr}</span>
        </div>

        {/* Search */}
        <div className="relative hidden md:block">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-[15px]" aria-hidden="true">search</span>
          <input
            className="w-52 pl-9 pr-4 py-2 bg-surface-raised dark:bg-surface-raised border border-border rounded-xl text-[13px] outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary/50 transition-all duration-200 placeholder:text-muted-foreground dark:text-foreground"
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
        <Button
          variant="outline"
          size="icon-lg"
          aria-label="Refresh all accounts"
          title="Refresh all accounts"
          onClick={handleRefresh}
          disabled={refreshing}
          className={`relative rounded-xl ${
            refreshing
              ? "bg-primary/10 dark:bg-primary/15 border-primary/50 text-primary cursor-not-allowed"
              : "text-muted-foreground hover:text-primary hover:border-primary/30 hover:bg-primary/10 dark:hover:bg-primary/10"
          }`}
        >
          <span
            className={`material-symbols-outlined text-[18px]${refreshing ? " animate-spin" : ""}`}
          >
            sync
          </span>
          {/* Ripple ring while refreshing */}
          {refreshing && (
            <span className="absolute inset-0 rounded-xl ring-2 ring-[var(--primary)]/40 animate-ping pointer-events-none" />
          )}
        </Button>

        {/* Theme toggle */}
        <ThemeToggle />

        {/* Notifications */}
        <NotificationPopover
          open={showNotifications}
          onToggle={() => setShowNotifications((v) => !v)}
          onClose={() => setShowNotifications(false)}
        />
      </div>
    </header>
  );
};

export default Header;
