import { useCallback, useEffect, useRef } from "react";
import { apiFetch } from "../lib/api";
import { SSE_TOPICS } from "../lib/sseTopics";
import { toast } from "../lib/toast";

type CredentialActionChoice = "change_now" | "remind_later";

interface CredentialActionRequest {
  action_id: string;
  institution: string;
  action: string;
  title?: string;
  prompt?: string;
}

function institutionLabel(institution: string) {
  return institution.toLowerCase() === "mypay"
    ? "myPay"
    : institution.toUpperCase();
}

export default function CredentialActionToasts() {
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const seenActionIds = useRef<Set<string>>(new Set());

  const respond = useCallback(
    async (request: CredentialActionRequest, choice: CredentialActionChoice) => {
      await apiFetch("/api/credential-actions/respond", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action_id: request.action_id,
          choice,
        }),
      });
    },
    []
  );

  const launchCredentialStore = useCallback(async (institution: string) => {
    await apiFetch("/api/credential-actions/launch-credential-store", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ institution }),
    });
    toast("Credential Manager prompt opened.", "info", 6000);
  }, []);

  const handlePasswordChange = useCallback(
    (request: CredentialActionRequest) => {
      const label = institutionLabel(request.institution);
      const message =
        request.prompt ||
        `${label} is asking for a password change during refresh.`;

      toast(message, "warning", 0, [
        {
          label: "Change now",
          variant: "primary",
          onClick: async () => {
            try {
              await respond(request, "change_now");
              toast(
                `${label} is waiting in the browser. Update the stored password when the site accepts the new one.`,
                "warning",
                0,
                [
                  {
                    label: "Update stored password",
                    variant: "primary",
                    onClick: async () => {
                      try {
                        await launchCredentialStore(request.institution);
                      } catch (err: any) {
                        toast(
                          err?.message || "Could not open Credential Manager prompt.",
                          "error"
                        );
                      }
                    },
                  },
                ]
              );
            } catch (err: any) {
              toast(err?.message || "That password prompt expired.", "error");
            }
          },
        },
        {
          label: "Remind me later",
          variant: "secondary",
          onClick: async () => {
            try {
              await respond(request, "remind_later");
              toast(`${label} refresh will continue.`, "info");
            } catch (err: any) {
              toast(err?.message || "That password prompt expired.", "error");
            }
          },
        },
      ]);
    },
    [launchCredentialStore, respond]
  );

  const handleCredentialAction = useCallback(
    (request: CredentialActionRequest) => {
      if (!request.action_id || !request.institution || !request.action) {
        return;
      }
      if (seenActionIds.current.has(request.action_id)) {
        return;
      }
      seenActionIds.current.add(request.action_id);

      if (request.action === "password_change") {
        handlePasswordChange(request);
        return;
      }

      toast(
        request.prompt ||
          `${institutionLabel(request.institution)} needs a credential action.`,
        "warning",
        0,
        [
          {
            label: "Continue",
            variant: "primary",
            onClick: async () => {
              try {
                await respond(request, "remind_later");
              } catch (err: any) {
                toast(err?.message || "That credential prompt expired.", "error");
              }
            },
          },
        ]
      );
    },
    [handlePasswordChange, respond]
  );

  const connect = useCallback(() => {
    if (eventSourceRef.current) return;

    const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
    eventSourceRef.current = es;

    es.addEventListener(SSE_TOPICS.CREDENTIAL_ACTION_REQUIRED, (event) => {
      try {
        const msg = JSON.parse((event as MessageEvent).data);
        const payload = msg?.data ?? msg;
        handleCredentialAction(payload as CredentialActionRequest);
      } catch {
        // ignore malformed SSE payloads
      }
    });

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      reconnectTimer.current = window.setTimeout(connect, 5000);
    };
  }, [handleCredentialAction]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  return null;
}
