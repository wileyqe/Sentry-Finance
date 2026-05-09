import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { addToastListener, type Toast } from "@/lib/toast";

const ICON_MAP: Record<string, string> = {
  success: "check_circle",
  error: "error",
  info: "info",
  warning: "warning",
};

const COLOR_MAP: Record<string, string> = {
  success: "text-gain",
  error: "text-loss",
  info: "text-slate-500",
  warning: "text-amber-500",
};

export default function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    return addToastListener((t) => {
      setToasts((prev) => [...prev, t]);
      if (t.duration > 0 && Number.isFinite(t.duration)) {
        setTimeout(() => dismiss(t.id), t.duration);
      }
    });
  }, [dismiss]);

  const runAction = useCallback(
    async (toast: Toast, action: NonNullable<Toast["actions"]>[number]) => {
      await action.onClick();
      if (action.dismissOnClick !== false) {
        dismiss(toast.id);
      }
    },
    [dismiss]
  );

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
            className="pointer-events-auto flex items-start gap-3 px-4 py-3 rounded-lg bg-popover text-popover-foreground border border-border shadow-lg max-w-sm"
          >
            <span className={`material-symbols-outlined text-lg mt-0.5 ${COLOR_MAP[t.type]}`}>
              {ICON_MAP[t.type]}
            </span>
            <div className="min-w-0 flex-1">
              <span className="block text-sm text-slate-700 dark:text-slate-200 break-words">
                {t.message}
              </span>
              {t.actions && t.actions.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {t.actions.map((action) => (
                    <button
                      key={action.label}
                      onClick={() => void runAction(t, action)}
                      className={
                        action.variant === "primary"
                          ? "focus-ring px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
                          : "focus-ring px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                      }
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="focus-ring text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors mt-0.5"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
