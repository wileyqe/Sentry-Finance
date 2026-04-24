/**
 * Refresh status banner — subscribes to /api/refresh/events SSE stream
 * and shows a thin status bar when a refresh is in progress.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";

interface RefreshEvent {
  type: string;
  institution?: string;
  status?: string;
  message?: string;
}

interface RefreshBannerProps {
  /** Called when a refresh completes so pages can refetch */
  onRefreshComplete?: () => void;
}

export default function RefreshBanner({ onRefreshComplete }: RefreshBannerProps) {
  const [active, setActive] = useState(false);
  const [message, setMessage] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (eventSourceRef.current) return;

    const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data: RefreshEvent = JSON.parse(event.data);
        if (data.type === "session_started") {
          setActive(true);
          setMessage("Syncing accounts...");
        } else if (data.type === "institution_progress") {
          setMessage(`Syncing ${data.institution || ""}...`);
        } else if (data.type === "institution_completed") {
          setMessage(`${data.institution || ""} updated`);
        } else if (
          data.type === "session_completed" ||
          data.type === "session_failed"
        ) {
          setMessage(data.type === "session_completed" ? "Sync complete" : "Sync finished with errors");
          setTimeout(() => {
            setActive(false);
            onRefreshComplete?.();
          }, 2000);
        }
      } catch {
        // ignore non-JSON (keepalive comments)
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      // Reconnect after 5s
      reconnectTimer.current = window.setTimeout(connect, 5000);
    };
  }, [onRefreshComplete]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          className="overflow-hidden"
        >
          <div className="flex items-center gap-3 px-6 py-2 bg-primary/10 dark:bg-primary/15 border-b border-primary/20 dark:border-primary/30">
            <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
            <span className="text-xs font-medium text-primary">
              {message}
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
