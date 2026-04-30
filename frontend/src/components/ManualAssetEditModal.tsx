/**
 * ManualAssetEditModal — Inline editor for home and vehicle valuations.
 *
 * Append-only: every submission writes a new row dated ``as_of``.
 * Corrections happen by submitting a newer dated row, not by editing
 * an existing one. This matches the real_estate / vehicle_valuations
 * table conventions on the backend.
 *
 * Pre-fill logic by kind:
 *   vehicle      → GET /api/vehicles/{id}/suggested_value (depreciation
 *                  heuristic; no free public KBB/Edmunds API as of 2026).
 *   real_estate  → most-recent row from ``/api/accounts`` manual_assets
 *                  (typically sourced from NFCU HomeSquad or a prior
 *                  manual override).
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiFetch, useMutation } from "../lib/api";
import { formatCurrency } from "@/lib/formatCurrency";
import { useRuntimeContext } from "@/context/RuntimeContext";

export type ManualAssetKind = "vehicle" | "real_estate";

interface VehicleAsset {
  id: string;
  make: string;
  model: string;
  year: number;
  purchase_price?: number | null;
  purchase_date?: string | null;
  latest_value?: number | null;
  latest_value_as_of?: string | null;
  latest_value_source?: string | null;
}

interface RealEstateAsset {
  id: number;
  name: string;
  estimated_value: number;
  as_of: string;
  source: string;
}

type Asset = VehicleAsset | RealEstateAsset;

interface Props {
  kind: ManualAssetKind;
  asset: Asset | null;
  onClose: () => void;
  onSaved: () => void;
}

interface SuggestedValueResponse {
  suggested_value: number;
  basis: {
    purchase_price: number;
    purchase_date: string | null;
    age_years: number;
    depreciation_curve: string;
  };
}

export default function ManualAssetEditModal({ kind, asset, onClose, onSaved }: Props) {
  const { referenceDate } = useRuntimeContext();
  const [value, setValue] = useState<string>("");
  const [asOf, setAsOf] = useState<string>(referenceDate);
  const [suggestion, setSuggestion] = useState<SuggestedValueResponse | null>(null);
  const [submit, mut] = useMutation<{ status: string }>("POST");

  // Reset + pre-fill when the asset changes.
  useEffect(() => {
    if (!asset) return;
    setAsOf(referenceDate);
    if (kind === "real_estate") {
      const re = asset as RealEstateAsset;
      setValue(re.estimated_value ? re.estimated_value.toFixed(0) : "");
      setSuggestion(null);
      return;
    }
    // vehicle: pre-fill from latest valuation; also fetch suggested value
    const v = asset as VehicleAsset;
    setValue(v.latest_value != null ? v.latest_value.toFixed(0) : "");
    setSuggestion(null);
    apiFetch<SuggestedValueResponse>(
      `/api/vehicles/${encodeURIComponent(v.id)}/suggested_value?as_of=${referenceDate}`
    )
      .then((r) => {
        setSuggestion(r);
        // If no existing valuation, pre-fill with the suggestion.
        if (v.latest_value == null) {
          setValue(r.suggested_value.toFixed(0));
        }
      })
      .catch(() => {
        /* endpoint 404 / network — leave suggestion null */
      });
  }, [asset, kind, referenceDate]);

  if (!asset) return null;

  const title =
    kind === "vehicle"
      ? `${(asset as VehicleAsset).year} ${(asset as VehicleAsset).make} ${(asset as VehicleAsset).model}`
      : (asset as RealEstateAsset).name;

  const sourceLabel =
    kind === "vehicle"
      ? (asset as VehicleAsset).latest_value_source
      : (asset as RealEstateAsset).source;

  const sourceAsOf =
    kind === "vehicle"
      ? (asset as VehicleAsset).latest_value_as_of
      : (asset as RealEstateAsset).as_of;

  const parsedValue = Number(value);
  const validValue = Number.isFinite(parsedValue) && parsedValue > 0;
  const validDate = /^\d{4}-\d{2}-\d{2}$/.test(asOf);
  const canSubmit = validValue && validDate && !mut.loading;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const path =
      kind === "vehicle"
        ? `/api/vehicles/${encodeURIComponent((asset as VehicleAsset).id)}/valuations`
        : `/api/real_estate/${(asset as RealEstateAsset).id}/valuations`;
    const res = await submit(path, {
      estimated_value: parsedValue,
      as_of: asOf,
      source: "manual",
    });
    if (res) {
      onSaved();
      onClose();
    }
  };

  const handleUseSuggestion = () => {
    if (suggestion) setValue(suggestion.suggested_value.toFixed(0));
  };

  return (
    <AnimatePresence>
      {asset && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[9000] flex items-center justify-center"
          style={{ backgroundColor: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
          onClick={onClose}
        >
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: 10 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 10 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="w-full max-w-md mx-4 card-l1 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-slate-200 dark:border-primary/10 flex items-center gap-3">
              <span
                aria-hidden="true"
                className="material-symbols-outlined text-2xl text-primary"
              >
                {kind === "vehicle" ? "directions_car" : "home"}
              </span>
              <div className="flex-1">
                <h3 className="font-semibold text-base text-slate-900 dark:text-white">
                  {title}
                </h3>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Update estimated value
                </p>
              </div>
            </div>

            <div className="px-6 py-5 space-y-5">
              {/* Source badge */}
              {sourceLabel && sourceAsOf && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-medium">
                    Source: {sourceLabel}
                  </span>
                  <span className="text-muted-foreground">
                    updated {sourceAsOf}
                  </span>
                </div>
              )}

              {/* Depreciation suggestion (vehicle only) */}
              {kind === "vehicle" && suggestion && (
                <div className="rounded-lg border border-slate-200 dark:border-primary/10 px-4 py-3 bg-slate-50/50 dark:bg-slate-800/30">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-medium text-muted-foreground">
                      Suggested value
                    </span>
                    <button
                      type="button"
                      onClick={handleUseSuggestion}
                      className="text-xs font-semibold text-primary hover:underline"
                    >
                      Use suggested
                    </button>
                  </div>
                  <div className="text-lg font-bold text-numeric text-slate-900 dark:text-white">
                    {formatCurrency(suggestion.suggested_value)}
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-1 leading-snug">
                    Based on {formatCurrency(suggestion.basis.purchase_price)}{" "}
                    purchase, {suggestion.basis.age_years.toFixed(1)}y ago.{" "}
                    {suggestion.basis.depreciation_curve}.
                  </p>
                  <p className="text-[11px] text-muted-foreground mt-1 leading-snug italic">
                    We can&apos;t pull a free official KBB/Edmunds value automatically.
                    If you&apos;ve checked one, paste the number below.
                  </p>
                </div>
              )}

              {/* Value input */}
              <label className="block">
                <span className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Estimated value ($)
                </span>
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="1"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  placeholder="0"
                  className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-primary/10 bg-background text-foreground text-numeric focus:outline-none focus-ring"
                />
              </label>

              {/* As-of date */}
              <label className="block">
                <span className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  As of
                </span>
                <input
                  type="date"
                  value={asOf}
                  onChange={(e) => setAsOf(e.target.value)}
                  className="w-full px-3 py-2 rounded-md border border-slate-200 dark:border-primary/10 bg-background text-foreground focus:outline-none focus-ring"
                />
              </label>

              {mut.error && (
                <p className="text-xs text-loss">
                  {mut.error instanceof Error
                    ? mut.error.message
                    : String(mut.error)}
                </p>
              )}

              <p className="text-[11px] text-muted-foreground leading-snug">
                Submissions are append-only — each save writes a new dated
                valuation. To correct a mistake, submit a newer dated row.
              </p>
            </div>

            <div className="px-6 py-4 border-t border-slate-200 dark:border-primary/10 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="focus-ring px-4 py-1.5 rounded-md text-sm text-muted-foreground hover:text-foreground transition-colors"
                disabled={mut.loading}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={!canSubmit}
                className="focus-ring px-4 py-1.5 rounded-md text-sm font-semibold bg-primary text-primary-foreground hover:bg-primary/80 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {mut.loading ? "Saving…" : "Save"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
