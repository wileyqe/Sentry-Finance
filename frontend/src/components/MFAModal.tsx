/**
 * MFAModal — Overlay for entering authenticator codes during automated refreshes.
 *
 * Subscribes to the SSE /api/refresh/events stream and listens for
 * "mfa_required" events. When triggered, displays a modal with a 6-digit
 * input field and submits the code to POST /api/mfa/submit.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { apiFetch } from "../lib/api";

interface MFARequest {
  institution: string;
  prompt: string;
}

export default function MFAModal() {
  const [mfaRequest, setMfaRequest] = useState<MFARequest | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (eventSourceRef.current) return;

    const es = new EventSource("http://127.0.0.1:8000/api/refresh/events");
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "mfa_required" && data.data) {
          setMfaRequest({
            institution: data.data.institution || "unknown",
            prompt: data.data.prompt || "Enter your authenticator code.",
          });
          setCode("");
          setError("");
          setSubmitting(false);
        }
      } catch {
        // ignore non-JSON (keepalive comments)
      }
    };

    es.onerror = () => {
      es.close();
      eventSourceRef.current = null;
      reconnectTimer.current = window.setTimeout(connect, 5000);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  // Focus the input when modal opens
  useEffect(() => {
    if (mfaRequest && inputRef.current) {
      inputRef.current.focus();
    }
  }, [mfaRequest]);

  const handleSubmit = async () => {
    if (!mfaRequest || code.length < 6) return;

    setSubmitting(true);
    setError("");

    try {
      await apiFetch("/api/mfa/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          institution: mfaRequest.institution,
          code: code,
        }),
      });
      // Dismiss modal on success
      setMfaRequest(null);
      setCode("");
    } catch (err: any) {
      setError(err?.message || "Failed to submit code. Please try again.");
      setSubmitting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && code.length >= 6) {
      handleSubmit();
    }
  };

  const institutionLabel = mfaRequest?.institution
    ? mfaRequest.institution.toUpperCase()
    : "";

  return (
    <AnimatePresence>
      {mfaRequest && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-[9999] flex items-center justify-center"
          style={{ backgroundColor: "rgba(0, 0, 0, 0.6)", backdropFilter: "blur(4px)" }}
        >
          <motion.div
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.9, opacity: 0, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="w-full max-w-md mx-4 rounded-lg shadow-2xl overflow-hidden"
            style={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
            }}
          >
            {/* Header */}
            <div
              className="px-6 py-4 flex items-center gap-3"
              style={{
                background: "linear-gradient(135deg, var(--primary-hover), var(--primary))",
                borderBottom: "1px solid rgba(255,255,255,0.1)",
              }}
            >
              <div className="w-10 h-10 rounded-full bg-white/20 flex items-center justify-center flex-shrink-0">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
              </div>
              <div>
                <h3 className="text-white font-semibold text-base">
                  {institutionLabel} Authentication
                </h3>
                <p className="text-white/80 text-xs">
                  Multi-factor verification required
                </p>
              </div>
            </div>

            {/* Body */}
            <div className="px-6 py-5 space-y-4">
              <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
                {mfaRequest.prompt}
              </p>

              <div>
                <label
                  htmlFor="mfa-code-input"
                  className="block text-xs font-medium mb-1.5"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  Authenticator Code
                </label>
                <input
                  ref={inputRef}
                  id="mfa-code-input"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  autoComplete="one-time-code"
                  autoFocus
                  value={code}
                  onChange={(e) => {
                    const val = e.target.value.replace(/\D/g, "").slice(0, 6);
                    setCode(val);
                    setError("");
                  }}
                  onKeyDown={handleKeyDown}
                  placeholder="000000"
                  disabled={submitting}
                  className="w-full px-4 py-3 rounded-xl text-center text-2xl text-numeric tracking-[0.5em] transition-all duration-200 focus-ring focus-visible:ring-2"
                  style={{
                    backgroundColor: "var(--background)",
                    border: error
                      ? "1px solid var(--color-loss)"
                      : "1px solid var(--border)",
                    color: "var(--foreground)",
                  }}
                />
              </div>

              {error && (
                <p className="text-xs text-loss flex items-center gap-1">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  {error}
                </p>
              )}
            </div>

            {/* Footer */}
            <div
              className="px-6 py-4 flex items-center justify-end gap-3"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <button
                onClick={() => setMfaRequest(null)}
                disabled={submitting}
                className="focus-ring px-4 py-2 text-sm rounded-lg transition-colors duration-150"
                style={{
                  color: "var(--muted-foreground)",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={code.length < 6 || submitting}
                className="focus-ring px-5 py-2 text-sm font-medium rounded-lg text-white transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
                style={{
                  background: code.length >= 6 && !submitting
                    ? "linear-gradient(135deg, var(--primary), var(--primary-hover))"
                    : "rgba(255,255,255,0.1)",
                }}
              >
                {submitting ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Submitting...
                  </span>
                ) : (
                  "Submit Code"
                )}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
