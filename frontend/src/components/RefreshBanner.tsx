/**
 * Refresh status banner — subscribes to /api/refresh/events SSE stream
 * and shows a thin status bar when a refresh is in progress.
 *
 * The backend SSE stream emits typed events (`event: <topic>\ndata: ...`),
 * so listeners must use `addEventListener("<topic>", ...)` — the bare
 * `onmessage` handler only catches events without an `event:` field and
 * therefore never fires for refresh lifecycle topics. Topic constants
 * are mirrored from `backend/sse_topics.py` via `lib/sseTopics.ts`.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { SSE_TOPICS } from "@/lib/sseTopics";

interface RefreshBannerProps {
  /** Called when a refresh completes so pages can refetch */
  onRefreshComplete?: () => void;
}

// Refresh-session states that mean "still working" — banner stays visible.
const ACTIVE_STATES = new Set([
  "EVALUATING_STALENESS",
  "AUTH_REQUIRED",
  "FETCHING_CREDENTIALS",
  "RUNNING",
  "WAITING_FOR_USER",
  "RETRY_BACKOFF",
]);

export default function RefreshBanner({ onRefreshComplete }: RefreshBannerProps) {
  const [active, setActive] = useState(false);
  const [message, setMessage] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (eventSourceRef.current) return;

    const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
    eventSourceRef.current = es;

    // Each SSE message arrives as `{ type, data, timestamp }` JSON.
    // Helper to extract the inner payload safely.
    const parse = (event: MessageEvent): any | null => {
      try {
        const msg = JSON.parse(event.data);
        return msg?.data ?? msg;
      } catch {
        return null;
      }
    };

    // Session lifecycle: show banner while state is non-terminal.
    es.addEventListener(SSE_TOPICS.STATE_CHANGE, (event) => {
      const payload = parse(event as MessageEvent);
      const state = payload?.state;
      if (!state) return;
      if (ACTIVE_STATES.has(state)) {
        setActive(true);
        setMessage("Syncing accounts...");
      }
    });

    es.addEventListener(SSE_TOPICS.INSTITUTION_STARTED, (event) => {
      const payload = parse(event as MessageEvent);
      setActive(true);
      setMessage(`Syncing ${payload?.institution || ""}...`);
    });

    es.addEventListener(SSE_TOPICS.INSTITUTION_COMPLETE, (event) => {
      const payload = parse(event as MessageEvent);
      setMessage(`${payload?.institution || ""} updated`);
    });

    es.addEventListener(SSE_TOPICS.INSTITUTION_RETRY, (event) => {
      const payload = parse(event as MessageEvent);
      setMessage(`Retrying ${payload?.institution || ""}...`);
    });

    es.addEventListener(SSE_TOPICS.INSTITUTION_FAILED, (event) => {
      const payload = parse(event as MessageEvent);
      setMessage(`${payload?.institution || ""} failed`);
    });

    es.addEventListener(SSE_TOPICS.REFRESH_COMPLETE, (event) => {
      const payload = parse(event as MessageEvent);
      const status = payload?.status;
      if (status === "success") {
        setMessage("Sync complete");
      } else if (status === "partial_success") {
        setMessage("Sync finished with some errors");
      } else if (status === "timeout") {
        setMessage("Sync timed out");
      } else {
        setMessage("Sync finished with errors");
      }
      setTimeout(() => {
        setActive(false);
        onRefreshComplete?.();
      }, 2000);
    });

    es.addEventListener(SSE_TOPICS.SESSION_TIMEOUT, () => {
      setMessage("Sync timed out");
      setTimeout(() => {
        setActive(false);
        onRefreshComplete?.();
      }, 2000);
    });

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
