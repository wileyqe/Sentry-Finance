/**
 * CreditScorePopup — Dashboard drill-in for the Credit Scores card.
 *
 * Renders a chart of each tracked credit score's trajectory over a
 * selectable timeframe. Anchored to the card it springs from: the
 * popup scales up around the card's center so it visually "comes
 * out of" the card. Closes on backdrop click, Escape, or the ✕ button.
 */

import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Area, AreaChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chartColor, rechartsAxisTickStyle, rechartsTooltipItemStyle, rechartsTooltipLabelStyle, rechartsTooltipStyle } from "@/lib/chartStyle";
import { useOwnerApi } from "@/lib/useOwnerApi";
import { useView } from "@/context/ViewContext";
import { institutionDisplayName } from "@/lib/institutionNames";
import { MONTH_ABBR } from "@/lib/dateUtils";

interface Props {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLDivElement | null>;
}

interface HistoryRow {
  score: number;
  score_type: string;
  source: string;
  institution_id: string;
  score_date: string; // YYYY-MM-DD
  owner_id?: string | null;
}

const TIMEFRAMES: { label: string; months: number }[] = [
  { label: "3M", months: 3 },
  { label: "6M", months: 6 },
  { label: "1Y", months: 12 },
  { label: "2Y", months: 24 },
  { label: "All", months: 120 },
];

const POPUP_WIDTH = 520;
const POPUP_HEIGHT = 420;
const VIEWPORT_MARGIN = 8;

function clampRect(cx: number, cy: number, w: number, h: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const effW = Math.min(w, vw - VIEWPORT_MARGIN * 2);
  const effH = Math.min(h, vh - VIEWPORT_MARGIN * 2);
  const minCx = VIEWPORT_MARGIN + effW / 2;
  const maxCx = vw - VIEWPORT_MARGIN - effW / 2;
  const minCy = VIEWPORT_MARGIN + effH / 2;
  const maxCy = vh - VIEWPORT_MARGIN - effH / 2;
  return {
    cx: Math.min(Math.max(cx, minCx), maxCx),
    cy: Math.min(Math.max(cy, minCy), maxCy),
    w: effW,
    h: effH,
  };
}

function seriesLabelFor(
  row: HistoryRow,
  ownerNameById: Record<string, string>
): string {
  const inst = row.institution_id
    ? institutionDisplayName(row.institution_id)
    : row.source;
  const ownerName = row.owner_id ? ownerNameById[row.owner_id.toLowerCase()] : null;
  return ownerName ? `${ownerName} · ${inst}` : `${inst}`;
}

function formatDateTick(raw: string): string {
  // raw is "YYYY-MM-DD". Render as "Mar 26" (month + 2-digit year).
  const [y, m] = raw.split("-");
  const monthIdx = Math.max(0, Math.min(11, parseInt(m, 10) - 1));
  const yy = y?.slice(-2) ?? "";
  return `${MONTH_ABBR[monthIdx]} ${yy}`;
}

export default function CreditScorePopup({ open, onClose, anchorRef }: Props) {
  const { owners } = useView();
  const [months, setMonths] = useState(6);
  const [geom, setGeom] = useState<{ cx: number; cy: number; w: number; h: number } | null>(null);

  // Reset to the 6M default each time the popup opens.
  useEffect(() => {
    if (open) setMonths(6);
  }, [open]);

  // Capture the card's bounding rect + clamp the popup frame to the viewport
  // right before paint. Re-run on resize/scroll so the popup stays anchored
  // even as the layout shifts underneath it.
  useLayoutEffect(() => {
    if (!open) return;
    const recompute = () => {
      const el = anchorRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      setGeom(clampRect(r.left + r.width / 2, r.top + r.height / 2, POPUP_WIDTH, POPUP_HEIGHT));
    };
    recompute();
    window.addEventListener("resize", recompute);
    window.addEventListener("scroll", recompute, true);
    const ro = new ResizeObserver(recompute);
    if (anchorRef.current) ro.observe(anchorRef.current);
    ro.observe(document.documentElement);
    return () => {
      window.removeEventListener("resize", recompute);
      window.removeEventListener("scroll", recompute, true);
      ro.disconnect();
    };
  }, [open, anchorRef]);

  // Escape closes. Only mounted while open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Only fetch while open. Null path short-circuits useApi so the closed
  // popup doesn't keep the network warm.
  const path = open ? `/api/metrics/credit-scores?history_months=${months}` : null;
  const { data, loading } = useOwnerApi<{ latest: any[]; history: HistoryRow[] }>(path);
  const history = data?.history ?? [];

  const ownerNameById = useMemo(() => {
    const m: Record<string, string> = {};
    for (const o of owners) m[o.id.toLowerCase()] = o.display_name;
    return m;
  }, [owners]);

  const { chartData, seriesKeys, yMin, yMax } = useMemo(() => {
    if (history.length === 0) {
      return { chartData: [], seriesKeys: [] as string[], yMin: 0, yMax: 0 };
    }
    const byDate: Record<string, Record<string, number | string>> = {};
    const keys = new Set<string>();
    let min = Infinity;
    let max = -Infinity;
    for (const row of history) {
      const key = seriesLabelFor(row, ownerNameById);
      keys.add(key);
      const bucket = byDate[row.score_date] || (byDate[row.score_date] = { date: row.score_date });
      bucket[key] = row.score;
      if (row.score < min) min = row.score;
      if (row.score > max) max = row.score;
    }
    const rows = Object.values(byDate).sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    );
    // Pad the y-axis so small deltas remain readable.
    const yMin = Math.max(300, Math.floor(min - 20));
    const yMax = Math.min(850, Math.ceil(max + 20));
    return { chartData: rows, seriesKeys: Array.from(keys), yMin, yMax };
  }, [history, ownerNameById]);

  // Pre-format the date column so the x-axis reads "Oct 25" etc.
  const displayData = useMemo(
    () => chartData.map((r) => ({ ...r, date: formatDateTick(String(r.date)) })),
    [chartData]
  );

  if (!geom) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
          className="fixed inset-0 z-[9000] bg-slate-900/10 dark:bg-slate-950/30"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: "absolute",
              left: geom.cx,
              top: geom.cy,
              width: geom.w,
              height: geom.h,
              transform: "translate(-50%, -50%)",
            }}
          >
            <motion.div
              role="dialog"
              aria-label="Credit scores trajectory"
              initial={{ scale: 0.85, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              transition={{ type: "spring", stiffness: 300, damping: 28 }}
              className="w-full h-full rounded-lg bg-popover text-popover-foreground border border-border shadow-2xl flex flex-col overflow-hidden"
            >
            {/* Header */}
            <div className="flex items-center justify-between px-5 pt-4 pb-3 border-b border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[18px] text-slate-600 dark:text-slate-300">
                  speed
                </span>
                <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                  Credit Score Trajectory
                </h3>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close credit scores chart"
                className="w-7 h-7 rounded-md flex items-center justify-center text-slate-500 hover:text-slate-800 dark:hover:text-slate-100 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <span className="material-symbols-outlined text-[18px]">close</span>
              </button>
            </div>

            {/* Timeframe pills */}
            <div className="px-5 pt-3 pb-2">
              <div className="inline-flex items-center gap-1 p-1 rounded-full bg-slate-100 dark:bg-slate-800">
                {TIMEFRAMES.map((tf) => {
                  const active = tf.months === months;
                  return (
                    <button
                      key={tf.label}
                      type="button"
                      onClick={() => setMonths(tf.months)}
                      className={`px-2.5 py-1 rounded-full text-[11px] font-semibold transition-colors ${
                        active
                          ? "bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-100 shadow-sm"
                          : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                      }`}
                    >
                      {tf.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Chart body */}
            <div className="flex-1 px-3 pb-4 pt-1 min-h-0">
              {loading && history.length === 0 ? (
                <div className="h-full flex items-center justify-center text-xs text-slate-400">
                  Loading…
                </div>
              ) : seriesKeys.length === 0 ? (
                <div className="h-full flex items-center justify-center text-sm text-slate-400 italic">
                  No scores available
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={displayData} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                    <defs>
                      {seriesKeys.map((key, i) => (
                        <linearGradient key={key} id={`cs-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={chartColor(i)} stopOpacity={0.28} />
                          <stop offset="100%" stopColor={chartColor(i)} stopOpacity={0.02} />
                        </linearGradient>
                      ))}
                    </defs>
                    <XAxis dataKey="date" tick={rechartsAxisTickStyle()} axisLine={false} tickLine={false} />
                    <YAxis
                      width={36}
                      tick={rechartsAxisTickStyle()}
                      axisLine={false}
                      tickLine={false}
                      domain={[yMin, yMax]}
                    />
                    <Tooltip
                      contentStyle={rechartsTooltipStyle()}
                      labelStyle={rechartsTooltipLabelStyle()}
                      itemStyle={rechartsTooltipItemStyle()}
                    />
                    {seriesKeys.length > 1 && (
                      <Legend
                        wrapperStyle={{ fontSize: "0.75rem", color: "var(--muted-foreground)" }}
                        iconType="circle"
                      />
                    )}
                    {seriesKeys.map((key, i) => (
                      <Area
                        key={key}
                        type="monotone"
                        dataKey={key}
                        stroke={chartColor(i)}
                        strokeWidth={2}
                        fill={`url(#cs-grad-${i})`}
                        isAnimationActive
                      />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
            </motion.div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}
