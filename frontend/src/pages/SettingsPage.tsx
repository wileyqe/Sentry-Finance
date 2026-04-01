import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../lib/api";

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

/* ── Component ──────────────────────────────────────────────── */

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, any> | null>(null);
  const [refreshPolicy, setRefreshPolicy] = useState<Record<string, RefreshPolicyEntry> | null>(null);
  const [overrides, setOverrides] = useState<Record<string, number>>({});
  const [owners, setOwners] = useState<any[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [archival, setArchival] = useState(36);

  const fetchAll = useCallback(() => {
    Promise.all([
      apiFetch("/api/settings").catch(() => null),
      apiFetch("/api/settings/refresh-policy").catch(() => null),
      apiFetch("/api/owners").catch(() => ({ owners: [] })),
    ]).then(([s, rp, ow]) => {
      if (s) {
        setSettings(s);
        setOverrides(s.refresh_intervals || {});
        setArchival(s.archival_months || 36);
      }
      if (rp) setRefreshPolicy(rp);
      setOwners(ow?.owners || []);
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

  if (!settings) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto space-y-6">
          <div className="h-8 w-48 rounded-lg bg-slate-200 dark:bg-slate-800 animate-pulse" />
          {[1,2,3].map(i => (
            <div key={i} className="card-l1 h-32 animate-pulse bg-slate-100 dark:bg-slate-800/50" />
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
        <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 flex items-center gap-3">
          <span className="material-symbols-outlined text-[28px] text-slate-400">settings</span>
          Settings
        </h1>

        {/* ── Section 1: Multi-User Mode ────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-purple-500">group</span>
            Multi-User Mode
          </h2>
          {owners.length < 2 ? (
            <p className="text-sm text-slate-400 italic">
              <span className="material-symbols-outlined text-[14px] mr-1 align-middle">info</span>
              Add a partner in the Accounts page to enable household mode.
            </p>
          ) : (
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">Enable Household Mode</p>
                <p className="text-xs text-slate-400 mt-0.5">Show a view selector in the sidebar (Mine / Partner / Household)</p>
              </div>
              <button
                onClick={() => patch("multi_user_enabled", !multiUserEnabled)}
                className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                  multiUserEnabled ? "bg-emerald-500" : "bg-slate-300 dark:bg-slate-600"
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
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-sky-500">sync</span>
            Refresh Policy
          </h2>
          {refreshPolicy ? (
            <div className="space-y-1">
              <div className="grid grid-cols-[1fr_120px_120px_80px] gap-3 text-xs font-bold text-slate-400 uppercase tracking-wider pb-2 border-b border-slate-200 dark:border-slate-700">
                <span>Institution</span>
                <span className="text-center">Base Interval</span>
                <span className="text-center">Override (hrs)</span>
                <span />
              </div>
              {Object.entries(refreshPolicy).map(([inst, config]) => (
                <div key={inst} className="grid grid-cols-[1fr_120px_120px_80px] gap-3 items-center py-2.5 border-b border-slate-100 dark:border-slate-800">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200 capitalize">{inst}</span>
                  <span className="text-sm text-center text-slate-500">{config.refresh_interval_hours}h</span>
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
                    className="text-sm text-center border border-slate-200 dark:border-slate-700 rounded-lg px-2 py-1.5 bg-white dark:bg-slate-800 w-full"
                  />
                  <button
                    onClick={() => {
                      setOverrides(prev => {
                        const next = { ...prev };
                        delete next[inst];
                        return next;
                      });
                    }}
                    className="text-xs text-slate-400 hover:text-red-500 transition-colors"
                    title="Reset to default"
                  >
                    Reset
                  </button>
                </div>
              ))}
              <button
                onClick={() => patch("refresh_intervals", overrides)}
                disabled={saving === "refresh_intervals"}
                className="mt-3 px-4 py-2 text-sm font-semibold rounded-lg bg-emerald-500 text-white hover:bg-emerald-600 transition-colors disabled:opacity-50"
              >
                {saving === "refresh_intervals" ? "Saving…" : "Save Overrides"}
              </button>
            </div>
          ) : (
            <p className="text-sm text-slate-400">Loading refresh policy…</p>
          )}
        </div>

        {/* ── Section 3: Notification Preferences ───────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-amber-500">notifications</span>
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
                  <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">{label}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{desc}</p>
                </div>
                <button
                  onClick={() => toggleNotif(key)}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out ${
                    notifPrefs[key] ? "bg-emerald-500" : "bg-slate-300 dark:bg-slate-600"
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
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-emerald-500">description</span>
            Expected Documents
          </h2>

          {/* Monthly */}
          <div className="mb-4">
            <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Monthly</p>
            <div className="flex flex-wrap gap-2">
              {monthlyDocs.map(doc => (
                <span key={doc} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100 dark:bg-slate-800 text-sm text-slate-700 dark:text-slate-300">
                  {doc.replace(/_/g, " ")}
                  <button
                    onClick={() => {
                      const updated = monthlyDocs.filter(d => d !== doc);
                      patch("expected_monthly_docs", updated);
                    }}
                    className="text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                </span>
              ))}
              {monthlyDocs.length === 0 && <span className="text-sm text-slate-400 italic">None configured</span>}
            </div>
          </div>

          {/* Annual */}
          <div>
            <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">Annual (Tax Documents)</p>
            <div className="flex flex-wrap gap-2">
              {annualDocs.map(doc => (
                <span key={doc} className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100 dark:bg-slate-800 text-sm text-slate-700 dark:text-slate-300">
                  {doc.replace(/_/g, " ").toUpperCase()}
                  <button
                    onClick={() => {
                      const updated = annualDocs.filter(d => d !== doc);
                      patch("expected_annual_docs", updated);
                    }}
                    className="text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <span className="material-symbols-outlined text-[14px]">close</span>
                  </button>
                </span>
              ))}
              {annualDocs.length === 0 && <span className="text-sm text-slate-400 italic">None configured</span>}
            </div>
          </div>
        </div>

        {/* ── Section 5: Data Retention ──────────────────────── */}
        <div className="card-l1 p-6">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-3 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-red-400">delete_sweep</span>
            Data Retention
          </h2>
          <div className="flex items-center gap-4">
            <div>
              <p className="text-sm text-slate-700 dark:text-slate-200 font-medium">Keep transaction history for</p>
              <p className="text-xs text-slate-400 mt-0.5">Transactions older than this are archived on refresh</p>
            </div>
            <div className="flex items-center gap-2 ml-auto">
              <input
                type="number"
                min={6}
                max={120}
                value={archival}
                onChange={(e) => setArchival(parseInt(e.target.value) || 36)}
                className="w-20 text-sm text-center border border-slate-200 dark:border-slate-700 rounded-lg px-2 py-1.5 bg-white dark:bg-slate-800"
              />
              <span className="text-sm text-slate-500">months</span>
              <button
                onClick={() => patch("archival_months", archival)}
                disabled={saving === "archival_months"}
                className="px-3 py-1.5 text-sm font-semibold rounded-lg bg-emerald-500 text-white hover:bg-emerald-600 transition-colors disabled:opacity-50"
              >
                {saving === "archival_months" ? "…" : "Save"}
              </button>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
