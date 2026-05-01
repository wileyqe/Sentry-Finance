import { useState, useEffect, useMemo } from "react";
import { apiFetch } from "../lib/api";
import { useView } from "../context/ViewContext";
import LifestyleCreepPanel from "../components/LifestyleCreepPanel";
import { formatCurrency } from "@/lib/formatCurrency";
import { formatCompactCurrency } from "@/lib/formatCompactCurrency";
import { Skeleton } from "@/components/Skeleton";
import { useRuntimeContext } from "@/context/RuntimeContext";
import { parseIsoDateLocal } from "@/lib/dateUtils";

/* ── Helpers ──────────────────────────────────────────────────────── */

const fmtPct = (n: number | null | undefined) =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`;

type WrapupStatus = "preliminary" | "revised" | "final";

const statusConfig: Record<WrapupStatus, { label: string; color: string; icon: string }> = {
  preliminary: { label: "Preliminary", color: "bg-[var(--color-warning)]/10 text-[var(--color-warning)]", icon: "hourglass_empty" },
  revised: { label: "Revised", color: "bg-[var(--chart-c2)]/10 text-[var(--chart-c2)]", icon: "edit_document" },
  final: { label: "Final", color: "bg-gain-subtle text-gain", icon: "verified" },
};

/* ── Component ────────────────────────────────────────────────────── */

export default function YearlyWrapUpPage() {
  const { ownerParam } = useView();
  const { referenceDate, ready: runtimeReady } = useRuntimeContext();
  const ownerSuffix = ownerParam ? `&owner_id=${ownerParam}` : '';
  const currentYear = parseIsoDateLocal(referenceDate).getFullYear();
  const yearOpts = useMemo(() => Array.from({ length: 5 }, (_, i) => currentYear - 1 - i), [currentYear]);
  const [year, setYear] = useState(yearOpts[0]);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lifestyleData, setLifestyleData] = useState<any>(null);
  const [showChecklist, setShowChecklist] = useState(false);
  const [showOverrides, setShowOverrides] = useState(false);

  useEffect(() => {
    if (!runtimeReady) return;
    setLoading(true);
    apiFetch(`/api/review/yearly?year=${year}${ownerSuffix}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));

    fetchLifestyle(2);
  }, [year, ownerSuffix, runtimeReady]);

  useEffect(() => {
    setYear(yearOpts[0]);
  }, [yearOpts]);

  const fetchLifestyle = (lookbackYears: number) => {
    apiFetch(`/api/lifestyle/creep?lookback_years=${lookbackYears}${ownerSuffix}`)
      .then(setLifestyleData)
      .catch(() => setLifestyleData(null));
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-6xl mx-auto space-y-6">
          <Skeleton className="h-8 w-60 rounded-lg" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        <span className="material-symbols-outlined mr-2">error</span>
        Failed to load yearly report
      </div>
    );
  }

  const status = (data.status || "preliminary") as WrapupStatus;
  const sc = statusConfig[status] || statusConfig.preliminary;
  const taxOverrides = data.tax_overrides || {};
  const checklist = data.tax_doc_checklist;

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* ── Header ───────────────────────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-foreground">
              {year} Annual Wrap-Up
            </h1>
            <span
              data-testid="yearly-wrapup-status"
              className={`inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full ${sc.color}`}
            >
              <span className="material-symbols-outlined text-[14px]">{sc.icon}</span>
              {sc.label}
            </span>
          </div>
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            className="text-sm border border-border rounded-lg px-3 py-1.5 bg-card text-foreground"
          >
            {yearOpts.map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>

        {/* ── Summary Strip ────────────────────────────────────────── */}
        <div className="grid grid-cols-4 gap-4">
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Total Income</p>
            <p className="stat-value text-gain" data-testid="yearly-wrapup-total-income">{formatCompactCurrency(data.total_income)}</p>
          </div>
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Total Spending</p>
            <p className="stat-value text-loss" data-testid="yearly-wrapup-total-spending">{formatCompactCurrency(data.total_spending)}</p>
          </div>
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Savings Rate</p>
            <p className="stat-value" data-testid="yearly-wrapup-savings-rate">{data.savings_rate?.toFixed(1) ?? "—"}%</p>
          </div>
          <div className="card-l1 p-5">
            <p className="stat-label mb-1">Net Interest Cost</p>
            <p
              data-testid="yearly-wrapup-net-interest-cost"
              className={`stat-value ${(data.interest?.net_cost ?? 0) > 0 ? "text-loss" : "text-gain"}`}
            >
              {formatCompactCurrency(data.interest?.net_cost ?? 0)}
            </p>
          </div>
        </div>

        {/* ── Tax Checklist (collapsible) ───────────────────────────── */}
        {checklist && (
          <div className="card-l1">
            <button
              onClick={() => setShowChecklist(!showChecklist)}
              className="section-header w-full"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className="material-symbols-outlined text-[18px] text-[var(--color-warning)]">task_alt</span>
                Tax Document Checklist
                <span className="chip-l2 ml-2" data-testid="yearly-wrapup-tax-doc-count">
                  {checklist.documents.filter((d: any) => d.received).length}/{checklist.documents.length}
                </span>
              </span>
              <span className="material-symbols-outlined text-[18px] text-muted-foreground transition-transform" style={{ transform: showChecklist ? "rotate(180deg)" : "none" }}>
                expand_more
              </span>
            </button>
            {showChecklist && (
              <div className="p-5 pt-0 space-y-2">
                {checklist.documents.map((doc: any) => (
                  <div key={doc.parser_type} className="flex items-center gap-3 text-sm py-1.5">
                    <span className={`material-symbols-outlined text-[18px] ${doc.received ? "text-gain" : "text-muted-foreground/50"}`}>
                      {doc.received ? "check_circle" : "radio_button_unchecked"}
                    </span>
                    <span className={doc.received ? "text-foreground" : "text-muted-foreground"}>
                      {doc.label}
                    </span>
                    {doc.received ? (
                      <span className="text-xs text-muted-foreground ml-auto">
                        {new Date(doc.committed_at).toLocaleDateString()}
                      </span>
                    ) : (
                      <a
                        href="/documents"
                        className="text-sm text-[var(--chart-c2)] hover:opacity-80 hover:underline ml-auto inline-flex items-center gap-1"
                      >
                        Drop File
                        <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                      </a>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Tax Overrides Diff Panel ──────────────────────────────── */}
        {Object.keys(taxOverrides).length > 0 && (
          <div className="card-l1">
            <button
              onClick={() => setShowOverrides(!showOverrides)}
              className="section-header w-full"
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                <span className="material-symbols-outlined text-[18px] text-[var(--chart-c2)]">difference</span>
                What Changed (Tax Overrides)
              </span>
              <span className="material-symbols-outlined text-[18px] text-muted-foreground transition-transform" style={{ transform: showOverrides ? "rotate(180deg)" : "none" }}>
                expand_more
              </span>
            </button>
            {showOverrides && (
              <div className="p-5 pt-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-label border-b border-border">
                      <th className="pb-2">Field</th>
                      <th className="pb-2 text-right">Preliminary</th>
                      <th className="pb-2 text-right">Authoritative</th>
                      <th className="pb-2 text-right">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(taxOverrides).map(([key, val]: [string, any]) => (
                      <tr key={key} className="border-b border-border">
                        <td className="py-2 font-medium text-foreground">
                          {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        </td>
                        <td className="py-2 text-right text-numeric text-muted-foreground line-through">
                          {val.preliminary != null ? formatCurrency(val.preliminary) : "—"}
                        </td>
                        <td className="py-2 text-right text-numeric font-semibold text-gain">{formatCurrency(val.authoritative)}</td>
                        <td className="py-2 text-right text-xs text-muted-foreground">{val.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Effective Tax Rate ────────────────────────────────────── */}
        {(() => {
          const eff = data.effective_tax;
          const preTax = data.pre_tax;
          if (!eff) return null;
          const dq = eff.data_quality || "missing";
          if (dq === "missing") {
            return (
              <div className="card-l1 p-5">
                <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px] text-[var(--chart-c7)]">request_quote</span>
                  Effective Tax Rate
                </h2>
                <p className="text-sm text-muted-foreground py-2">
                  Drop a myPay RAS to see your effective tax rate.{" "}
                  <a href="/documents" className="text-[var(--chart-c2)] hover:underline">
                    Drop file →
                  </a>
                </p>
              </div>
            );
          }
          const validation = eff.validation;
          return (
            <div className="card-l1 p-5">
              <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-[var(--chart-c7)]">request_quote</span>
                Effective Tax Rate
                {dq === "partial" && (
                  <span className="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded-md bg-[var(--color-warning)]/10 text-[var(--color-warning)]">
                    Partial — {eff.months_covered}/12 months
                  </span>
                )}
              </h2>
              <div className="grid grid-cols-4 gap-4">
                <div>
                  <p className="stat-label mb-1">Gross Income</p>
                  <p className="stat-value" data-testid="yearly-wrapup-effective-gross-income">{formatCompactCurrency(eff.gross_income)}</p>
                </div>
                <div>
                  <p className="stat-label mb-1">Federal Tax</p>
                  <p className="stat-value text-loss" data-testid="yearly-wrapup-effective-federal-tax">{formatCompactCurrency(eff.federal_tax)}</p>
                </div>
                <div>
                  <p className="stat-label mb-1">State Tax</p>
                  <p className="stat-value text-loss" data-testid="yearly-wrapup-effective-state-tax">{formatCompactCurrency(eff.state_tax)}</p>
                </div>
                <div>
                  <p className="stat-label mb-1">Effective Rate</p>
                  <p className="stat-value" data-testid="yearly-wrapup-effective-rate">{eff.effective_rate_pct.toFixed(1)}%</p>
                  {preTax && (
                    <p className="text-[10px] text-muted-foreground mt-1">
                      Pre-tax SR {preTax.savings_rate_pct.toFixed(1)}%
                    </p>
                  )}
                </div>
              </div>
              {validation && !validation.matches && (
                <div className="mt-4 p-3 rounded-lg bg-[var(--color-warning)]/10 border border-[var(--color-warning)]/30 text-xs text-[var(--color-warning)] flex items-start gap-2">
                  <span className="material-symbols-outlined text-[16px] mt-0.5">warning</span>
                  <div>
                    <p className="font-semibold">1099-R disagrees with payroll snapshots</p>
                    <p className="mt-0.5">
                      1099-R federal tax: <span className="text-numeric">{formatCurrency(validation.federal_tax_1099r)}</span>
                      {" · "}
                      Payroll sum: <span className="text-numeric">{formatCurrency(validation.federal_tax_payroll)}</span>
                      {" · "}
                      Delta: <span className="text-numeric font-semibold">{validation.delta >= 0 ? "+" : ""}{formatCurrency(validation.delta)}</span>
                    </p>
                  </div>
                </div>
              )}
              {validation && validation.matches && (
                <div className="mt-4 p-3 rounded-lg bg-gain-subtle border border-[var(--color-gain)]/30 text-xs text-gain flex items-center gap-2">
                  <span className="material-symbols-outlined text-[16px]">verified</span>
                  Validated against DFAS 1099-R
                </div>
              )}
            </div>
          );
        })()}

        {/* ── Income by Stream ──────────────────────────────────────── */}
        <div className="card-l1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-[var(--primary)]">payments</span>
            Income by Stream
          </h2>
          <div className="space-y-3">
            {(data.income_by_stream || []).filter((s: any) => s.total > 0).map((s: any) => {
              const pct = data.total_income > 0 ? (s.total / data.total_income) * 100 : 0;
              const slug = String(s.stream || 'unknown')
                .toLowerCase()
                .replace(/[^a-z0-9]+/g, '-')
                .replace(/(^-|-$)/g, '') || 'unknown';
              return (
                <div key={s.stream}>
                  <div className="flex items-center justify-between text-sm mb-1">
                    <span className="text-foreground font-medium">{s.stream}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-numeric text-foreground" data-testid={`yearly-wrapup-income-stream-${slug}`}>{formatCurrency(s.total)}</span>
                      {s.yoy_change_pct != null && (
                        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-md ${s.yoy_change_pct >= 0 ? "bg-gain-subtle text-gain" : "bg-loss-subtle text-loss"}`}>
                          {fmtPct(s.yoy_change_pct)}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="h-2 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full bg-[var(--color-gain)]" style={{ width: `${Math.min(pct, 100)}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Spending by Category ──────────────────────────────────── */}
        <div className="card-l1 p-5">
          <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-loss">shopping_cart</span>
            Spending by Category
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-label border-b border-border">
                  <th className="pb-2">Category</th>
                  <th className="pb-2 text-right">Total</th>
                  <th className="pb-2 text-right">% of Spend</th>
                  <th className="pb-2 text-right">Prior Year</th>
                  <th className="pb-2 text-right">YoY</th>
                </tr>
              </thead>
              <tbody>
                {(data.spending_by_category || []).slice(0, 12).map((c: any) => {
                  const slug = String(c.category || 'unknown')
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, '-')
                    .replace(/(^-|-$)/g, '') || 'unknown';
                  return (
                    <tr key={c.category} className="border-b border-border">
                      <td className="py-2.5 font-medium text-foreground">{c.category}</td>
                      <td className="py-2.5 text-right text-numeric" data-testid={`yearly-wrapup-spending-category-${slug}`}>{formatCurrency(c.total)}</td>
                      <td className="py-2.5 text-right text-numeric text-muted-foreground">{c.pct_of_spending?.toFixed(1)}%</td>
                      <td className="py-2.5 text-right text-numeric text-muted-foreground">{c.prior_year != null ? formatCurrency(c.prior_year) : "—"}</td>
                      <td className={`py-2.5 text-right text-numeric font-semibold ${
                        c.yoy_change_pct == null ? "text-muted-foreground" :
                        c.yoy_change_pct > 0 ? "text-loss" : "text-gain"
                      }`}>
                        {fmtPct(c.yoy_change_pct)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Two-column: Interest + Investments ───────────────────── */}
        <div className="grid grid-cols-2 gap-4">
          {/* Interest */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--color-warning)]">savings</span>
              Interest Paid vs. Earned
            </h2>
            <div className="space-y-3">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Total Paid</span>
                <span className="text-numeric font-semibold text-loss" data-testid="yearly-wrapup-interest-paid">{formatCurrency(data.interest?.total_paid ?? 0)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Total Earned</span>
                <span className="text-numeric font-semibold text-gain" data-testid="yearly-wrapup-interest-earned">{formatCurrency(data.interest?.total_earned ?? 0)}</span>
              </div>
              <hr className="divider" />
              <div className="flex justify-between text-sm">
                <span className="text-foreground font-semibold">Net Cost</span>
                <span
                  data-testid="yearly-wrapup-interest-net-cost"
                  className={`text-numeric font-bold ${(data.interest?.net_cost ?? 0) > 0 ? "text-loss" : "text-gain"}`}
                >
                  {formatCurrency(data.interest?.net_cost ?? 0)}
                </span>
              </div>
            </div>
          </div>

          {/* Investment Performance */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--primary)]">trending_up</span>
              Investment Performance
            </h2>
            {(data.investment_performance || []).length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No investment data</p>
            ) : (
              <div className="space-y-3">
                {(data.investment_performance || []).map((ip: any) => (
                  <div key={ip.account_id} className="flex items-center justify-between text-sm">
                    <span className="text-foreground font-medium truncate max-w-[160px]">{ip.name}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-numeric text-muted-foreground">{formatCurrency(ip.end_value)}</span>
                      {ip.total_return_pct != null && (
                        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-md ${ip.total_return_pct >= 0 ? "bg-gain-subtle text-gain" : "bg-loss-subtle text-loss"}`}>
                          {fmtPct(ip.total_return_pct)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Debt Progress ─────────────────────────────────────────── */}
        {(data.debt_progress || []).length > 0 && (
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-loss">credit_card</span>
              Debt Progress
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-label border-b border-border">
                  <th className="pb-2">Account</th>
                  <th className="pb-2 text-right">Jan 1</th>
                  <th className="pb-2 text-right">Dec 31</th>
                  <th className="pb-2 text-right">Principal Paid</th>
                  <th className="pb-2 text-right">APR</th>
                </tr>
              </thead>
              <tbody>
                {(data.debt_progress || []).map((d: any) => (
                  <tr key={d.account_id} className="border-b border-border">
                    <td className="py-2.5 font-medium text-foreground">{d.name}</td>
                    <td className="py-2.5 text-right text-numeric text-muted-foreground">{formatCurrency(d.balance_jan1)}</td>
                    <td className="py-2.5 text-right text-numeric">{formatCurrency(d.balance_dec31)}</td>
                    <td className={`py-2.5 text-right text-numeric font-semibold ${d.principal_paid > 0 ? "text-gain" : "text-muted-foreground"}`}>
                      {formatCurrency(d.principal_paid)}
                    </td>
                    <td className="py-2.5 text-right text-numeric text-muted-foreground">{d.apr != null ? `${d.apr}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Three-column: Recurring / Goals / Lifestyle ──────────── */}
        <div className="grid grid-cols-3 gap-4">
          {/* Recurring Changes */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c4)]">autorenew</span>
              Recurring Changes
            </h2>
            {(() => {
              const rc = data.recurring_changes || { new: [], removed: [], price_changes: [] };
              const total = rc.new.length + rc.removed.length + rc.price_changes.length;
              if (total === 0) return <p className="text-sm text-muted-foreground text-center py-4">No changes</p>;
              return (
                <div className="space-y-2">
                  {rc.new.length > 0 && (
                    <div>
                      <p className="text-label mb-1 text-gain">New ({rc.new.length})</p>
                      {rc.new.slice(0, 5).map((n: any) => (
                        <div key={n.merchant} className="flex justify-between text-sm py-1">
                          <span className="text-muted-foreground truncate">{n.merchant}</span>
                          <span className="text-numeric text-muted-foreground">{formatCurrency(n.amount)}/mo</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {rc.removed.length > 0 && (
                    <div>
                      <p className="text-label mb-1 text-muted-foreground">Removed ({rc.removed.length})</p>
                      {rc.removed.slice(0, 5).map((r: any) => (
                        <div key={r.merchant} className="flex justify-between text-sm py-1 opacity-50">
                          <span className="text-muted-foreground truncate line-through">{r.merchant}</span>
                          <span className="text-numeric text-muted-foreground">{formatCurrency(r.last_amount)}/mo</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {rc.price_changes.length > 0 && (
                    <div>
                      <p className="text-label mb-1 text-[var(--color-warning)]">Price Changes ({rc.price_changes.length})</p>
                      {rc.price_changes.slice(0, 5).map((p: any) => (
                        <div key={p.merchant} className="flex justify-between text-sm py-1">
                          <span className="text-muted-foreground truncate">{p.merchant}</span>
                          <span className={`text-numeric text-xs font-semibold ${p.delta > 0 ? "text-loss" : "text-gain"}`}>
                            {p.delta > 0 ? "+" : ""}{formatCurrency(p.annualized_delta)}/yr
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}
          </div>

          {/* Goals */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c2)]">flag</span>
              Savings Goals
            </h2>
            {(data.goals_progress || []).length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No active goals</p>
            ) : (
              <div className="space-y-3">
                {(data.goals_progress || []).map((g: any) => (
                  <div key={g.name}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-foreground font-medium truncate">{g.name}</span>
                      {g.pct_funded >= 100 ? (
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-gain">
                          <span className="material-symbols-outlined text-[14px]">check_circle</span>
                          Completed
                        </span>
                      ) : (
                        <span className="text-numeric text-xs text-muted-foreground">{g.pct_funded.toFixed(0)}%</span>
                      )}
                    </div>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={`h-full rounded-full ${g.pct_funded >= 100 ? "bg-[var(--color-gain)]" : g.on_track ? "bg-[var(--color-gain)]" : "bg-[var(--color-warning)]"}`}
                        style={{ width: `${Math.min(g.pct_funded, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Lifestyle Creep */}
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c3)]">show_chart</span>
              Lifestyle Creep
            </h2>
            <LifestyleCreepPanel data={lifestyleData} compact onLookbackChange={fetchLifestyle} />
          </div>
        </div>

        {/* ── Full Lifestyle Creep (expanded table below) ──────────── */}
        {lifestyleData && !lifestyleData.insufficient_data && lifestyleData.categories?.length > 0 && (
          <div className="card-l1 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[var(--chart-c3)]">analytics</span>
              Lifestyle Creep — Full Analysis
            </h2>
            <LifestyleCreepPanel data={lifestyleData} onLookbackChange={fetchLifestyle} />
          </div>
        )}

      </div>
    </div>
  );
}
