import { useView } from "../context/ViewContext";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";
import { motion } from "framer-motion";

/**
 * Investments — P13-T05 (wiring).
 *
 * Fetches `/api/investments/holdings` and renders a portfolio
 * summary card per account plus a per-ETF holdings grid.
 * Activity and performance tabs are deferred to a future task.
 */

interface Holding {
  ticker: string;
  shares: string;
  price: number | null;
  market_value: number | null;
  allocation_pct: number;
}

interface InvestmentAccount {
  account_id: string;
  name: string;
  institution_id: string;
  total_value: number;
  holdings: Holding[];
  last_scraped: string | null;
}

const TICKER_COLORS: Record<string, string> = {
  VOO: "oklch(0.52 0.12 240)",
  IJH: "oklch(0.52 0.13 155)",
  IJR: "oklch(0.50 0.10 40)",
  IXUS: "oklch(0.50 0.08 300)",
};
const DEFAULT_COLOR = "oklch(0.52 0.10 200)";

const containerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.25 } },
};

function EmptyShell() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <span className="material-symbols-outlined text-6xl text-slate-400 mb-4">
        trending_up
      </span>
      <h1 className="text-2xl font-semibold text-slate-200 mb-2">
        Investments
      </h1>
      <p className="max-w-md text-sm text-slate-400">
        No investment accounts seeded yet. The investments view is
        being rebuilt from the ground up — data sources will land one
        at a time.
      </p>
    </div>
  );
}

function formatShares(s: string): string {
  const n = parseFloat(s);
  if (isNaN(n)) return s;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 5,
  });
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function InvestmentsPage() {
  useView();

  const { data, loading, error } = useOwnerApi<{ accounts: InvestmentAccount[] }>(
    "/api/investments/holdings"
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-slate-400">
        Loading investment accounts…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-loss">
        Could not load investment accounts.
      </div>
    );
  }

  const accounts = (data?.accounts ?? []).filter(
    (a) => a.holdings.length > 0 || a.total_value > 0
  );

  if (accounts.length === 0) {
    return <EmptyShell />;
  }

  return (
    <motion.div
      variants={containerVariants}
      initial="hidden"
      animate="visible"
      className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar relative p-12"
    >
      <h1 className="text-2xl font-semibold text-slate-200 mb-6">
        Investments
      </h1>

      {accounts.map((acct) => (
        <div key={acct.account_id} className="mb-8">
          {/* Account summary card */}
          <motion.div variants={itemVariants} className="card-l1 p-6 mb-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <span className="material-symbols-outlined text-3xl text-sky-400">
                  trending_up
                </span>
                <div>
                  <div className="text-lg font-semibold text-slate-200">
                    {acct.name}
                  </div>
                  <div className="text-xs uppercase tracking-wide text-slate-400">
                    {institutionDisplayName(acct.institution_id)}
                  </div>
                </div>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-slate-200">
                  {formatCurrency(acct.total_value)}
                </div>
                {acct.last_scraped && (
                  <div className="text-xs text-slate-500 mt-1">
                    Updated {formatDate(acct.last_scraped)}
                  </div>
                )}
              </div>
            </div>
          </motion.div>

          {/* Holdings grid */}
          {acct.holdings.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
              {acct.holdings.map((h) => {
                const color = TICKER_COLORS[h.ticker] || DEFAULT_COLOR;
                return (
                  <motion.div
                    key={h.ticker}
                    variants={itemVariants}
                    className="card-l1 p-5 flex flex-col gap-3"
                  >
                    <div className="flex items-center justify-between">
                      <span
                        className="text-lg font-bold"
                        style={{ color }}
                      >
                        {h.ticker}
                      </span>
                      <span className="text-xs text-slate-500">
                        {h.allocation_pct}%
                      </span>
                    </div>

                    <div className="space-y-1 text-sm">
                      <div className="flex justify-between text-slate-400">
                        <span>Shares</span>
                        <span className="text-slate-200">{formatShares(h.shares)}</span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>Price</span>
                        <span className="text-slate-200">
                          {h.price != null ? formatCurrency(h.price) : "—"}
                        </span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>Value</span>
                        <span className="font-semibold text-slate-200">
                          {h.market_value != null ? formatCurrency(h.market_value) : "—"}
                        </span>
                      </div>
                    </div>

                    {/* Allocation bar */}
                    <div className="h-1.5 rounded-full bg-slate-700/50 overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${Math.max(h.allocation_pct, 2)}%`,
                          backgroundColor: color,
                        }}
                      />
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>
      ))}
    </motion.div>
  );
}
