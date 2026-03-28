/**
 * Offline / API-unreachable banner.
 * Shown at the top of the app when the backend is down.
 */

import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";

export default function ApiStatus() {
  const [offline, setOffline] = useState(false);
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    const check = () => {
      fetch("http://127.0.0.1:8000/api/health", { method: "GET" })
        .then((r) => {
          setOffline(!r.ok);
        })
        .catch(() => {
          setOffline(true);
        });
    };

    // Initial check after a short delay (avoid flash on startup)
    const initTimer = setTimeout(check, 1500);
    // Poll every 10s
    intervalRef.current = window.setInterval(check, 10000);

    return () => {
      clearTimeout(initTimer);
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return (
    <AnimatePresence>
      {offline && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden"
        >
          <div className="flex items-center gap-3 px-6 py-2 bg-amber-50 dark:bg-amber-950/30 border-b border-amber-200 dark:border-amber-800/40">
            <span className="material-symbols-outlined text-sm text-amber-600 dark:text-amber-400">cloud_off</span>
            <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
              Backend unreachable — data may be stale
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
