/**
 * NotificationPopover — the Phase 16 notification feed for the header bell.
 *
 * Subscribes to the SSE stream at /api/refresh/events and refreshes the
 * unread-count badge whenever a `notification` event arrives — no polling.
 * Fetches the feed lazily on open. On open, marks all unread → read so
 * the badge drops to zero.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, useApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { SSE_TOPICS } from "@/lib/sseTopics";

// ── Types ─────────────────────────────────────────────────────────────────────

type Severity = "info" | "warning" | "critical";
type NotifType =
  | "refresh_failure"
  | "budget_alert"
  | "bill_due_soon"
  | "bill_overdue"
  | "doc_drop_nudge"
  | "apy_rate_change"
  | "recurring_price_mutation";

interface Notification {
  id: number;
  type: NotifType;
  severity: Severity;
  title: string;
  body?: string;
  link?: string;
  created_at: string;
  read_at?: string;
  dismissed_at?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_ICON: Record<NotifType, string> = {
  refresh_failure:          "sync_problem",
  budget_alert:             "pie_chart",
  bill_due_soon:            "schedule",
  bill_overdue:             "alarm",
  doc_drop_nudge:           "description",
  apy_rate_change:          "percent",
  recurring_price_mutation: "price_change",
};

const SEVERITY_CLASS: Record<Severity, string> = {
  info:     "text-muted-foreground",
  warning:  "text-warning",
  critical: "text-loss",
};

function timeAgo(isoUtc: string): string {
  const diffMs = Date.now() - new Date(isoUtc + (isoUtc.endsWith("Z") ? "" : "Z")).getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

// ── Badge counter ─────────────────────────────────────────────────────────────

function useUnreadCount() {
  const [count, setCount] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch<{ count: number }>("/api/notifications/unread-count");
      setCount(res.count ?? 0);
    } catch {
      // non-fatal — badge stays at last known value
    }
  }, []);

  // Initial fetch + SSE subscription. Replaces the 60s poll: the bell
  // re-queries unread count whenever a `notification` topic event arrives.
  useEffect(() => {
    refresh();

    const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
    let reconnectTimer: number | null = null;

    es.addEventListener(SSE_TOPICS.NOTIFICATION, () => {
      refresh();
    });

    es.onerror = () => {
      es.close();
      // Best-effort reconnect; if the backend is down the next refresh
      // will surface it through the existing /unread-count failure path.
      reconnectTimer = window.setTimeout(refresh, 5000);
    };

    return () => {
      es.close();
      if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    };
  }, [refresh]);

  return { count, setCount, refresh };
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
}

export default function NotificationPopover({ open, onToggle, onClose }: Props) {
  const { count, setCount, refresh: refreshBadge } = useUnreadCount();

  // Fetch feed lazily — only when popover is open.
  const { data, loading, refetch } = useApi<{ notifications: Notification[] }>(
    "/api/notifications",
    { skip: !open, fallback: { notifications: [] } }
  );

  // Local optimistic state for dismissed items.
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  // On open: mark all read + zero badge.
  const markedRef = useRef(false);
  useEffect(() => {
    if (!open) {
      markedRef.current = false;
      return;
    }
    if (markedRef.current) return;
    markedRef.current = true;
    apiFetch("/api/notifications/mark-read", { method: "POST" })
      .then(() => setCount(0))
      .catch(() => {});
  }, [open, setCount]);

  // When popover closes, refresh the badge to pick up any server-side changes.
  const prevOpen = useRef(open);
  useEffect(() => {
    if (prevOpen.current && !open) refreshBadge();
    prevOpen.current = open;
  }, [open, refreshBadge]);

  const handleDismiss = useCallback(
    async (id: number) => {
      setDismissed((prev) => new Set([...prev, id]));
      try {
        await apiFetch("/api/notifications/dismiss", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: [id] }),
        });
      } catch {
        // revert optimistic update on failure
        setDismissed((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    },
    []
  );

  const visibleItems = (data?.notifications ?? []).filter(
    (n) => !dismissed.has(n.id)
  );

  return (
    <>
      {/* Bell button with badge */}
      <div className="relative">
        <Button
          variant="outline"
          size="icon-lg"
          aria-label="Notifications"
          onClick={onToggle}
          className="rounded-xl text-muted-foreground hover:text-primary hover:border-primary/30 hover:bg-primary/10 dark:hover:bg-primary/10"
        >
          <span className="material-symbols-outlined text-[18px]">
            {count > 0 ? "notifications_active" : "notifications"}
          </span>
          {count > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 bg-loss text-white text-[10px] font-bold rounded-full flex items-center justify-center leading-none">
              {count > 99 ? "99+" : count}
            </span>
          )}
        </Button>

        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={onClose} />
            <div className="absolute right-0 top-11 w-80 bg-card text-foreground border border-border rounded-xl shadow-lg z-50 overflow-hidden">
              {/* Header */}
              <div className="px-4 py-3 border-b border-border flex items-center justify-between">
                <h4 className="text-sm font-semibold text-foreground">Notifications</h4>
                {visibleItems.length > 0 && (
                  <button
                    onClick={() => refetch()}
                    className="text-[11px] text-muted-foreground hover:text-primary transition-colors"
                  >
                    Refresh
                  </button>
                )}
              </div>

              {/* Feed */}
              <div className="max-h-[380px] overflow-y-auto">
                {loading && (
                  <div className="flex items-center justify-center py-8">
                    <span className="material-symbols-outlined text-xl text-muted-foreground animate-spin">
                      sync
                    </span>
                  </div>
                )}

                {!loading && visibleItems.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-8 px-4">
                    <span className="material-symbols-outlined text-2xl text-muted-foreground mb-2">
                      notifications_off
                    </span>
                    <p className="text-sm text-muted-foreground">No notifications</p>
                  </div>
                )}

                {!loading &&
                  visibleItems.map((n) => (
                    <NotifRow
                      key={n.id}
                      notif={n}
                      onDismiss={() => handleDismiss(n.id)}
                      onClose={onClose}
                    />
                  ))}
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── Individual row ────────────────────────────────────────────────────────────

function NotifRow({
  notif,
  onDismiss,
  onClose,
}: {
  notif: Notification;
  onDismiss: () => void;
  onClose: () => void;
}) {
  const icon = TYPE_ICON[notif.type] ?? "circle";
  const iconClass = SEVERITY_CLASS[notif.severity] ?? "text-muted-foreground";
  const isUnread = !notif.read_at;

  const handleClick = () => {
    if (notif.link) {
      onClose();
      window.location.href = notif.link;
    }
  };

  return (
    <div
      className={`group flex items-start gap-3 px-4 py-3 border-b border-border last:border-b-0 hover:bg-surface-raised transition-colors ${
        notif.link ? "cursor-pointer" : ""
      } ${isUnread ? "bg-primary/5" : ""}`}
      onClick={notif.link ? handleClick : undefined}
    >
      {/* Icon */}
      <span className={`material-symbols-outlined text-[18px] mt-0.5 shrink-0 ${iconClass}`}>
        {icon}
      </span>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <p className={`text-[13px] leading-snug ${isUnread ? "font-semibold" : "font-medium"} text-foreground truncate`}>
          {notif.title}
        </p>
        {notif.body && (
          <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">{notif.body}</p>
        )}
        <p className="text-[10px] text-muted-foreground mt-1">{timeAgo(notif.created_at)}</p>
      </div>

      {/* Dismiss */}
      <button
        aria-label="Dismiss"
        onClick={(e) => {
          e.stopPropagation();
          onDismiss();
        }}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground focus:opacity-100 focus-ring rounded"
      >
        <span className="material-symbols-outlined text-[16px]">close</span>
      </button>
    </div>
  );
}
