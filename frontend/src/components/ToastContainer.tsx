import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { addToastListener, type Toast } from "@/lib/toast";

const ICON_MAP: Record<string, string> = {
  success: "check_circle",
  error: "error",
  info: "info",
};

const COLOR_MAP: Record<string, string> = {
  success: "text-gain",
  error: "text-loss",
  info: "text-slate-500",
};

export default function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    return addToastListener((t) => {
      setToasts((prev) => [...prev, t]);
      setTimeout(() => dismiss(t.id), t.duration);
    });
  }, [dismiss]);

  return (
    <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-lg bg-popover text-popover-foreground border border-border shadow-lg max-w-sm"
          >
            <span className={`material-symbols-outlined text-lg ${COLOR_MAP[t.type]}`}>
              {ICON_MAP[t.type]}
            </span>
            <span className="text-sm text-slate-700 dark:text-slate-200 flex-1">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="focus-ring text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
