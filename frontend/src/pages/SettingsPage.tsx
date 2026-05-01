import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";
import { institutionDisplayName } from "@/lib/institutionNames";
import { useView } from "../context/ViewContext";
import { Skeleton } from "@/components/Skeleton";

/* ── Types ──────────────────────────────────────────────────── */

interface NotificationPrefs {
  budget_alerts: boolean;
  staleness_alerts: boolean;
  document_nudges: boolean;
  bill_reminders: boolean;
}

interface RefreshPolicyEntry {
  refresh_interval_hours: number;
  [key: string]: any;
}

interface Owner {
  id: string;
  display_name: string;
  created_at?: string;
}

interface AccountOwnershipRow {
  id: string;
  institution_id: string;
  institution_name?: string;
  name: string;
  type: string;
  owner_id: string | null;
  is_synthetic?: boolean;
}

/* ── Component ──────────────────────────────────────────────── */

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [refreshPolicy, setRefreshPolicy] = useState<Record<string, RefreshPolicyEntry> | null>(null);
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [owners, setOwners] = useState<Owner[]>([]);
  const [ownershipAccounts, setOwnershipAccounts] = useState<AccountOwnershipRow[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [archival, setArchival] = useState(36);
  const { refetchOwners } = useView();
  const [ownerNameDrafts, setOwnerNameDrafts] = useState<Record<string, string>>({});
  const [ownerSavingId, setOwnerSavingId] = useState<string | null>(null);
  const [ownerErrors, setOwnerErrors] = useState<Record<string, string>>({});
  const [accountOwnerSavingId, setAccountOwnerSavingId] = useState<string | null>(null);
  const [accountOwnerErrors, setAccountOwnerErrors] = useState<Record<string, string>>({});

  const fetchAll = useCallback(() => {
    Promise.all([
      apiFetch("/api/settings").catch(() => null),
      apiFetch("/api/settings/refresh-policy").catch(() => null),
      apiFetch("/api/owners").catch(() => ({ owners: [] })),
      apiFetch("/api/accounts/ownership").catch(() => ({ accounts: [] })),
    ]).then(([s, rp, ow, accountOwnership]) => {
      if (s) {
        setSettings(s);
        setOverrides(s.refresh_intervals || {});
        setArchival(s.archival_months || 36);
      }
      if (rp) setRefreshPolicy(rp);
      const ownerList = ow?.owners || [];
      setOwners(ownerList);
      setOwnerNameDrafts(
        Object.fromEntries(ownerList.map((o: any) => [o.id, o.display_name])),
      );
      setOwnershipAccounts(accountOwnership?.accounts || []);
    });
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  /* ── Patch helper ─────────────────────────────────────────── */

  const patch = async (key: string, value: any) => {
    setSaving(key);
    try {
      await apiFetch(`/api/settings/${key}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value }),
      });
      setSettings(prev => prev ? { ...prev, [key]: value } : prev);
    } catch {}
    setSaving(null);
  };

  /* ── Owner rename ─────────────────────────────────────────── */

  const saveOwnerName = async (ownerId: string) => {
    const next = (ownerNameDrafts[ownerId] || "").trim();
    if (!next) {
      setOwnerErrors(prev => ({ ...prev, [ownerId]: "Name cannot be empty" }));
      return;
    }
    if (next.length > 50) {
      setOwnerErrors(prev => ({ ...prev, [ownerId]: "Max 50 characters" }));
      return;
    }
    setOwnerSavingId(ownerId);
    setOwnerErrors(prev => {
      const { [ownerId]: _, ...rest } = prev;
      return rest;
    });
    try {
      await apiFetch(`/api/owners/${ownerId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: next }),
      });
      // Optimistic local update for the Settings page itself…
      setOwners(prev =>
        prev.map(o => (o.id === ownerId ? { ...o, display_name: next } : o)),
      );
      // …and refresh the global ViewContext so the dashboard chips update.
      refetchOwners();
    } catch (e: any) {
      setOwnerErrors(prev => ({
        ...prev,
        [ownerId]: e?.message || "Save failed",
      }));
    }
    setOwnerSavingId(null);
  };

  const saveAccountOwner = async (accountId: string, ownerId: string) => {
    const nextOwnerId = ownerId || null;
    setAccountOwnerSavingId(accountId);
    setAccountOwnerErrors(prev => {
      const { [accountId]: _, ...rest } = prev;
      return rest;
    });
    try {
      const result = await apiFetch<{ owner_id: string | null }>(
        `/api/accounts/${encodeURIComponent(accountId)}/owner`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ owner_id: nextOwnerId }),
        },
      );
      setOwnershipAccounts(prev =>
        prev.map(account =>
          account.id === accountId
            ? { ...account, owner_id: result.owner_id ?? null }
            : account,
        ),
      );
    } catch (e: any) {
      setAccountOwnerErrors(prev => ({
        ...prev,
        [accountId]: e?.message || "Save failed",
      }));
    }
    setAccountOwnerSavingId(null);
  };

  if (!settings) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          <Skeleton className="h-8 w-48 rounded-lg" />
          {[1,2,3].map(i => (
            <Skeleton key={i} className="h-32 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  const notifPrefs: NotificationPrefs = settings.notification_preferences || {
    budget_alerts: true, staleness_alerts: true, document_nudges: true, bill_reminders: true,
  };
  const multiUserEnabled = settings.multi_user_enabled === true;
  const monthlyDocs: string[] = settings.expected_monthly_docs || [];
  const annualDocs: string[] = settings.expected_annual_docs || [];

  const toggleNotif = (key: keyof NotificationPrefs) => {
    const updated = { ...notifPrefs, [key]: !notifPrefs[key] };
    patch("notification_preferences", updated);
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* ── Header ───────────────────────────────────────── */}
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-3">
          <span className="material-symbols-outlined text-[28px] text-muted-foreground">settings</span>
          Settings
        </h1>

        {/* ── Section: Owners (rename) ──────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-indigo-500">badge</span>
            Owners
          </h2>
          <p className="text-xs text-muted-foreground mb-4">
            Rename how each household member appears in the dashboard view selector.
            Owner IDs are immutable — only the display name can change here.
          </p>
          {owners.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">No owners configured.</p>
          ) : (
            <div className="space-y-4">
              {owners.map(o => {
                const draft = ownerNameDrafts[o.id] ?? o.display_name;
                const dirty = draft.trim() !== (o.display_name || "").trim();
                const err = ownerErrors[o.id];
                const busy = ownerSavingId === o.id;
                return (
                  <div key={o.id} className="space-y-1">
                    <div className="flex items-center gap-3">
                      <input
                        type="text"
                        value={draft}
                        maxLength={50}
                        disabled={busy}
                        onChange={(e) =>
                          setOwnerNameDrafts(prev => ({ ...prev, [o.id]: e.target.value }))
                        }
                        className="flex-1 text-sm border border-border rounded-lg px-3 py-2 bg-card"
                      />
                      <button
                        onClick={() => saveOwnerName(o.id)}
                        disabled={!dirty || busy}
                        className="px-3 py-1.5 text-sm font-semibold rounded-lg bg-primary hover:bg-[var(--primary-hover)] text-primary-foreground transition-colors disabled:opacity-40"
                      >
                        {busy ? "…" : "Save"}
                      </button>
                    </div>
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground">
                      <span>ID: {o.id} (immutable)</span>
                      {err && <span className="text-loss">{err}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Section: Account ownership ────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-teal-500">account_tree</span>
            Account Ownership
          </h2>
          {ownershipAccounts.length === 0 ? (
            <p className="text-sm text-muted-foreground italic">No active accounts configured.</p>
          ) : (
            <div className="space-y-2">
              {ownershipAccounts.map(account => {
                const busy = accountOwnerSavingId === account.id;
                const err = accountOwnerErrors[account.id];
                return (
                  <div
                    key={account.id}
                    className="grid grid-cols-1 gap-2 py-3 border-b border-border last:border-0 sm:grid-cols-[minmax(0,1fr)_190px] sm:items-center"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">{account.name}</p>
                        {account.is_synthetic && (
                          <span className="shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded bg-violet-500/10 text-violet-500">
                            Demo
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground flex items-center gap-2 min-w-0">
                        <span className="truncate">{account.institution_name || institutionDisplayName(account.institution_id)}</span>
                        <span>•</span>
                        <span className="capitalize">{account.type.replace(/_/g, " ")}</span>
                        {err && (
                          <>
                            <span>•</span>
                            <span className="text-loss">{err}</span>
                          </>
                        )}
                      </p>
                    </div>
                    <select
                      value={account.owner_id ?? ""}
                      disabled={busy}
                      onChange={(e) => saveAccountOwner(account.id, e.target.value)}
                      className="bg-card border border-border rounded-lg px-3 h-9 text-xs font-semibold outline-none cursor-pointer disabled:opacity-50"
                    >
                      <option value="">Household/shared</option>
                      {owners.map(owner => (
                        <option key={owner.id} value={owner.id}>{owner.display_name}</option>
                      ))}
                    </select>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Section 1: Multi-User Mode ────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-purple-500">group</span>
            Multi-User Mode
          </h2>
          {owners.length < 2 ? (
            <p className="text-sm text-muted-foreground italic">
              <span className="material-symbols-outlined text-[14px] mr-1 align-middle">info</span>
              Add a partner in the Accounts page to enable household mode.
            </p>
          ) : (
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-foreground font-medium">Enable Household Mode</p>
                <p className="text-xs text-muted-foreground mt-0.5">Show a view selector in the sidebar (Mine / Partner / Household)</p>
              </div>
              <button
                onClick={() => patch("multi_user_enabled", !multiUserEnabled)}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                  multiUserEnabled ? "bg-primary" : "bg-muted dark:bg-muted"
                }`}
              >
                <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                  multiUserEnabled ? "translate-x-5" : "translate-x-0"
                }`} />
              </button>
            </div>
          )}
        </div>

        {/* ── Section 2: Refresh Policy ─────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-sky-500">sync</span>
            Refresh Policy
          </h2>
          {refreshPolicy ? (
            <div className="space-y-1 overflow-x-auto">
              <div className="grid grid-cols-[1fr_100px_100px_72px] gap-2 text-xs font-bold text-muted-foreground uppercase tracking-wider pb-2 border-b border-border min-w-0">
                <span>Institution</span>
                <span className="text-center">Base Interval</span>
                <span className="text-center">Override (hrs)</span>
                <span />
              </div>
              {Object.entries(refreshPolicy).map(([inst, config]) => (
                <div key={inst} className="grid grid-cols-[1fr_100px_100px_72px] gap-2 items-center py-2.5 border-b border-border min-w-0">
                  <span className="text-sm font-medium text-foreground">{institutionDisplayName(inst)}</span>
                  <span className="text-sm text-center text-muted-foreground">{config.refresh_interval_hours}h</span>
                  <input
                    type="number"
                    min={1}
                    value={overrides[inst] ?? ""}
                    placeholder="—"
                    onChange={(e) => {
                      const val = e.target.value ? parseInt(e.target.value) : undefined;
                      setOverrides(prev => {
                        const next = { ...prev };
                        if (val) next[inst] = val; else delete next[inst];
                        return next;
                      });
                    }}
                    className="text-sm text-center border border-border rounded-lg px-2 py-1.5 bg-card w-full"
                  />
                  <button
                    onClick={() => {
                      setOverrides(prev => {
                        const next = { ...prev };
                        delete next[inst];
                        return next;
                      });
                    }}
                    className="text-xs text-muted-foreground hover:text-[var(--color-loss)] transition-colors"
                    title="Reset to default"
                  >
                    Reset
                  </button>
                </div>
              ))}
              <button
                onClick={() => patch("refresh_intervals", overrides)}
                disabled={saving === "refresh_intervals"}
                className="mt-3 px-4 py-2 text-sm font-semibold rounded-lg bg-primary hover:bg-[var(--primary-hover)] text-primary-foreground transition-colors disabled:opacity-50"
              >
                {saving === "refresh_intervals" ? "Saving…" : "Save Overrides"}
              </button>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Loading refresh policy…</p>
          )}
        </div>

        {/* ── Section 3: Notification Preferences ───────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-[var(--color-warning)]">notifications</span>
            Notification Preferences
          </h2>
          <div className="space-y-4">
            {([
              { key: "budget_alerts" as const, label: "Budget Alerts", desc: "Notify when spending exceeds budget targets" },
              { key: "staleness_alerts" as const, label: "Staleness Alerts", desc: "Warn when institution data is getting stale" },
              { key: "document_nudges" as const, label: "Document Nudges", desc: "Remind to upload monthly/annual documents" },
              { key: "bill_reminders" as const, label: "Bill Reminders", desc: "Upcoming and overdue bill notifications" },
            ]).map(({ key, label, desc }) => (
              <div key={key} className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-foreground font-medium">{label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                </div>
                <button
                  onClick={() => toggleNotif(key)}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                    notifPrefs[key] ? "bg-primary" : "bg-muted dark:bg-muted"
                  }`}
                >
                  <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                    notifPrefs[key] ? "translate-x-5" : "translate-x-0"
                  }`} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* ── Section 4: Expected Documents ──────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-primary">description</span>
            Expected Documents
          </h2>

          {/* Monthly */}
          <div className="mb-4">
            <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">Monthly</p>
            <div className="flex flex-wrap gap-2">
              {monthlyDocs.map(doc => (
                <span key={doc} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-raised dark:bg-surface-raised text-sm text-foreground">
                  {doc.replace(/_/g, " ")}
                  <button
                    onClick={() => {
                      const updated = monthlyDocs.filter(d => d !== doc);
                      patch("expected_monthly_docs", updated);
                    }}
                    className="text-muted-foreground hover:text-[var(--color-loss)] transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                </span>
              ))}
              {monthlyDocs.length === 0 && <span className="text-sm text-muted-foreground italic">None configured</span>}
            </div>
          </div>

          {/* Annual */}
          <div>
            <p className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-2">Annual (Tax Documents)</p>
            <div className="flex flex-wrap gap-2">
              {annualDocs.map(doc => (
                <span key={doc} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-raised dark:bg-surface-raised text-sm text-foreground">
                  {doc.replace(/_/g, " ").toUpperCase()}
                  <button
                    onClick={() => {
                      const updated = annualDocs.filter(d => d !== doc);
                      patch("expected_annual_docs", updated);
                    }}
                    className="text-muted-foreground hover:text-[var(--color-loss)] transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                </span>
              ))}
              {annualDocs.length === 0 && <span className="text-sm text-muted-foreground italic">None configured</span>}
            </div>
          </div>
        </div>

        {/* ── Section 5: Data Retention ──────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-[var(--color-loss)]">delete_sweep</span>
            Data Retention
          </h2>
          <div className="flex items-center gap-4">
            <div>
              <p className="text-sm text-foreground font-medium">Keep transaction history for</p>
              <p className="text-xs text-muted-foreground mt-0.5">Transactions older than this are archived on refresh</p>
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <input
                type="number"
                min={6}
                max={120}
                value={archival}
                onChange={(e) => setArchival(parseInt(e.target.value) || 36)}
                className="w-20 text-sm text-center border border-border rounded-lg px-2 py-1.5 bg-card"
              />
              <span className="text-sm text-muted-foreground">months</span>
              <button
                onClick={() => patch("archival_months", archival)}
                disabled={saving === "archival_months"}
                className="px-3 py-1.5 text-sm font-semibold rounded-lg bg-primary hover:bg-[var(--primary-hover)] text-primary-foreground transition-colors disabled:opacity-50"
              >
                {saving === "archival_months" ? "…" : "Save"}
              </button>
            </div>
          </div>
        </div>

        {/* ── Section: Data Sources ──────────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-violet-500">science</span>
            Data Sources
          </h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-foreground font-medium">Show Synthetic Data</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                When off, dashboards and reports hide demo/seeded data.
                Synthetic accounts are marked with a violet "Demo" badge.
              </p>
            </div>
            <button
              onClick={() => patch("show_synthetic_data", !(settings.show_synthetic_data !== false))}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                settings.show_synthetic_data !== false ? "bg-primary" : "bg-muted dark:bg-muted"
              }`}
            >
              <span className={`pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
                settings.show_synthetic_data !== false ? "translate-x-5" : "translate-x-0"
              }`} />
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
