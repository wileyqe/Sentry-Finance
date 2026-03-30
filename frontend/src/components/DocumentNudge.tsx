/**
 * DocumentNudge — Persistent banner for overdue Tier 3 document drops.
 *
 * Polls GET /api/documents/pending-nudges on mount and hourly.
 * Shows a fixed banner above the toast container when nudges exist.
 * User can dismiss for today (stores until-midnight in localStorage).
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { apiFetch } from "@/lib/api";

interface Nudge {
  institution: string;
  display_name: string;
  message: string;
}

const NUDGE_DISMISS_KEY = "nudge_dismissed_until";
const POLL_INTERVAL_MS = 60 * 60 * 1000; // 1 hour

function isDismissed(): boolean {
  const until = localStorage.getItem(NUDGE_DISMISS_KEY);
  if (!until) return false;
  return new Date(until) > new Date();
}

function dismissForToday() {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(0, 0, 0, 0);
  localStorage.setItem(NUDGE_DISMISS_KEY, tomorrow.toISOString());
}

export default function DocumentNudge() {
  const [nudges, setNudges] = useState<Nudge[]>([]);
  const [dismissed, setDismissed] = useState(isDismissed());
  const intervalRef = useRef<number | null>(null);
  const navigate = useNavigate();

  const fetchNudges = useCallback(() => {
    if (isDismissed()) {
      setDismissed(true);
      return;
    }
    apiFetch<{ nudges: Nudge[] }>("/api/documents/pending-nudges")
      .then((res) => setNudges(res.nudges || []))
      .catch(() => setNudges([]));
  }, []);

  useEffect(() => {
    fetchNudges();
    intervalRef.current = window.setInterval(fetchNudges, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchNudges]);

  const handleDismiss = useCallback(() => {
    dismissForToday();
    setDismissed(true);
  }, []);

  const handleDropFile = useCallback(() => {
    navigate("/documents");
  }, [navigate]);

  const visible = !dismissed && nudges.length > 0;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ y: 80, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 80, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
          className="fixed bottom-20 left-1/2 -translate-x-1/2 z-[9998] w-full max-w-xl px-4"
        >
          {nudges.map((nudge) => (
            <div
              key={nudge.institution}
              className="flex items-center gap-4 px-5 py-3.5 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/50 shadow-lg backdrop-blur-sm"
            >
              <span className="material-symbols-outlined text-amber-500 text-xl shrink-0">
                notifications_active
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                  {nudge.display_name}
                </p>
                <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5 truncate">
                  {nudge.message}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <button
                  onClick={handleDropFile}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-colors shadow-sm"
                >
                  <span className="material-symbols-outlined text-[14px]">upload_file</span>
                  Drop File
                </button>
                <button
                  onClick={handleDismiss}
                  className="text-xs text-amber-500 dark:text-amber-400 hover:text-amber-700 dark:hover:text-amber-200 underline underline-offset-2 transition-colors whitespace-nowrap"
                >
                  Dismiss for today
                </button>
              </div>
            </div>
          ))}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
