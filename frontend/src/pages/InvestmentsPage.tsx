import { useView } from "../context/ViewContext";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { formatCurrency } from "@/lib/formatCurrency";
import { institutionDisplayName } from "@/lib/institutionNames";

/**
 * Investments — P13-T02.
 *
 * First step of the ground-up rebuild: list any investment or
 * retirement accounts in the dev DB.  No holdings, no charts, no
 * tabs yet.  Each card shows the account name, institution, balance,
 * and a "Ready to receive funds" status when the balance is zero.
 *
 * If no investment accounts are seeded, the page falls back to the
 * P13-T01 empty-state shell so the route remains meaningful during
 * later rebuild iterations.
 *
 * Route, sidebar entry, and header page meta are unchanged from
 * P13-T01 — they were preserved through the strip.
 */

interface Account {
  id: string;
  name: string;
  type: string;
  institution_id: string;
  balance: number | null;
  balance_as_of: string | null;
  is_active: number;
}

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

export default function InvestmentsPage() {
  // View context is still consumed so the owner chip on the header
  // continues to function and filters the account list.
  useView();

  const { data, loading, error } = useOwnerApi<{ accounts: Account[] }>(
    "/api/accounts"
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
    (a) => a.type === "investment" || a.type === "retirement"
  );

  if (accounts.length === 0) {
    return <EmptyShell />;
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold text-slate-200 mb-2">
        Investments
      </h1>
      <p className="text-sm text-slate-400 mb-4">
        One account is connected. Further sources will land in
        subsequent rebuild tasks.
      </p>
      {accounts.map((acct) => (
        <div
          key={acct.id}
          className="card-l1 flex items-center justify-between p-6"
        >
          <div className="flex items-center gap-4">
            <span className="material-symbols-outlined text-3xl text-slate-400">
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
              {formatCurrency(acct.balance)}
            </div>
            <div className="text-xs text-slate-400 mt-1">
              {(acct.balance ?? 0) === 0
                ? "Ready to receive funds"
                : "Active"}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
