/**
 * DocumentDrop — Drag-and-drop document ingestion zone.
 *
 * States:
 *   idle       — waiting for drop
 *   uploading  — file uploaded, awaiting parse result
 *   preview    — showing ParseResult for user confirmation
 *   committing — committing to DB
 *   success    — committed, showing summary
 *   error      — parse or commit failed
 */

import { useState, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "@/lib/toast";

const API_BASE = "http://127.0.0.1:8000";
const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50 MB

const PARSER_LABELS: Record<string, string> = {
  tsp_statement: "TSP Statement",
  mypay_ras: "myPay RAS",
  unknown: "Unknown Document",
};

function snakeToTitle(s: string): string {
  return s
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

type DropState = "idle" | "uploading" | "preview" | "committing" | "success" | "error";

interface UploadResult {
  file_id: string;
  filename: string;
  parser_type: string;
  preview: Record<string, any>;
  warnings: string[];
  can_commit: boolean;
}


interface DocumentDropProps {
  /** Called after a successful commit so the parent can refetch history */
  onCommitSuccess?: () => void;
}

export default function DocumentDrop({ onCommitSuccess }: DocumentDropProps) {
  const [state, setState] = useState<DropState>("idle");
  const [dragOver, setDragOver] = useState(false);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const resetToIdle = useCallback(() => {
    setState("idle");
    setDragOver(false);
    setUploadResult(null);
    setErrorMessage("");
  }, []);

  const handleFile = useCallback(async (file: File) => {
    // Client-side size guard
    if (file.size > MAX_UPLOAD_BYTES) {
      setState("error");
      setErrorMessage(`File too large (${(file.size / 1024 / 1024).toFixed(1)} MB). Maximum is 50 MB.`);
      return;
    }

    setState("uploading");
    setErrorMessage("");

    try {
      const fd = new FormData();
      fd.append("file", file);

      const res = await fetch(`${API_BASE}/api/documents/upload`, {
        method: "POST",
        body: fd,
        // Do NOT set Content-Type — browser sets it with boundary
      });

      if (!res.ok) {
        let detail = `Upload failed (HTTP ${res.status})`;
        try {
          const body = await res.json();
          detail = body.detail || detail;
        } catch { /* response wasn't JSON */ }
        throw new Error(detail);
      }

      const data: UploadResult = await res.json();
      setUploadResult(data);
      setState("preview");
    } catch (err: any) {
      setState("error");
      setErrorMessage(err.message || "Upload failed");
    }
  }, []);

  const handleCommit = useCallback(async () => {
    if (!uploadResult) return;

    setState("committing");
    try {
      const res = await fetch(`${API_BASE}/api/documents/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: uploadResult.file_id }),
      });

      if (!res.ok) {
        let detail = `Commit failed (HTTP ${res.status})`;
        try {
          const body = await res.json();
          detail = body.detail || detail;
        } catch { /* response wasn't JSON */ }
        throw new Error(detail);
      }

      await res.json();
      setState("success");
      toast("Document imported successfully", "success");
      onCommitSuccess?.();

      // Auto-reset after showing success briefly
      setTimeout(resetToIdle, 2500);
    } catch (err: any) {
      setState("error");
      setErrorMessage(err.message || "Commit failed");
      toast(err.message || "Commit failed", "error");
    }
  }, [uploadResult, onCommitSuccess, resetToIdle]);

  // ── Drag events ─────────────────────────────────────────────────
  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (state === "idle") setDragOver(true);
  };

  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);

    if (state !== "idle") return;
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  const onFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    // Reset input so the same file can be selected again
    e.target.value = "";
  };

  // ── Commit button label ─────────────────────────────────────────
  const commitLabel = uploadResult
    ? `Import ${PARSER_LABELS[uploadResult.parser_type] || uploadResult.parser_type}`
    : "Confirm & Import";

  return (
    <>
      {/* Drop Zone */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => state === "idle" && inputRef.current?.click()}
        className={`relative rounded-xl border-2 border-dashed transition-all duration-200 cursor-pointer ${
          dragOver
            ? "border-[var(--chart-c2)]/60 bg-[var(--chart-c2)]/10 scale-[1.01]"
            : state === "error"
            ? "border-[var(--color-loss)]/40 bg-loss-subtle"
            : state === "success"
            ? "border-[var(--color-gain)]/40 bg-gain-subtle"
            : "border-border hover:border-[var(--muted-foreground)]/40 hover:bg-muted/30"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.xlsx"
          className="hidden"
          onChange={onFileInput}
        />

        <div className="flex flex-col items-center justify-center py-10 px-6 gap-3">
          {/* ── Idle ─────────────────────────────── */}
          {state === "idle" && (
            <>
              <span className="material-symbols-outlined text-4xl text-muted-foreground">
                cloud_upload
              </span>
              <div className="text-center">
                <p className="text-sm font-medium text-foreground">
                  Drop a PDF or XLSX file here
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  or click to browse · TSP statements, myPay RAS
                </p>
              </div>
            </>
          )}

          {/* ── Uploading ────────────────────────── */}
          {state === "uploading" && (
            <>
              <div className="h-8 w-8 rounded-full border-2 border-[var(--primary)] border-t-transparent animate-spin" />
              <p className="text-sm font-medium text-muted-foreground">
                Parsing document…
              </p>
            </>
          )}

          {/* ── Committing ───────────────────────── */}
          {state === "committing" && (
            <>
              <div className="h-8 w-8 rounded-full border-2 border-[var(--chart-c2)] border-t-transparent animate-spin" />
              <p className="text-sm font-medium text-muted-foreground">
                Importing data…
              </p>
            </>
          )}

          {/* ── Success ──────────────────────────── */}
          {state === "success" && (
            <>
              <span className="material-symbols-outlined text-4xl text-gain">
                check_circle
              </span>
              <p className="text-sm font-medium text-gain">
                Document imported successfully
              </p>
            </>
          )}

          {/* ── Error ────────────────────────────── */}
          {state === "error" && (
            <>
              <span className="material-symbols-outlined text-4xl text-loss">
                error
              </span>
              <p className="text-sm font-medium text-loss">{errorMessage}</p>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  resetToIdle();
                }}
                className="mt-1 text-xs text-[var(--chart-c2)] hover:opacity-80 underline transition-colors"
              >
                Try again
              </button>
            </>
          )}
        </div>
      </div>

      {/* ── Preview Modal ────────────────────────────────────────────── */}
      <AnimatePresence>
        {state === "preview" && uploadResult && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
            onClick={(e) => {
              if (e.target === e.currentTarget) {
                resetToIdle();
              }
            }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 8 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="card-l1 w-full max-w-lg mx-4 overflow-hidden"
            >
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-border">
                <div className="flex items-center gap-3">
                  <span className="material-symbols-outlined text-lg text-[var(--chart-c2)]">
                    description
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Document Preview
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-[260px]">
                      {uploadResult.filename}
                    </p>
                  </div>
                </div>
                {/* Parser type pill */}
                <span
                  className={`inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full ${
                    uploadResult.parser_type === "unknown"
                      ? "bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
                      : "bg-gain-subtle text-gain"
                  }`}
                >
                  <span className="material-symbols-outlined text-[14px]">
                    {uploadResult.parser_type === "unknown" ? "help" : "verified"}
                  </span>
                  {PARSER_LABELS[uploadResult.parser_type] || uploadResult.parser_type}
                </span>
              </div>

              {/* Body */}
              <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
                {!uploadResult.can_commit ? (
                  /* Two blocked states:
                     (a) parser_type === "unknown": no parser recognized
                         the file at all.
                     (b) parser_type is real but a silent-failure guard
                         tripped — the parser recognized the document
                         but could not extract the core dollar fields.
                         The blocking warning (prefixed "⚠ BLOCK:") in
                         the warnings list explains what went wrong. */
                  uploadResult.parser_type === "unknown" ? (
                    <div className="flex items-start gap-3 p-4 rounded-lg bg-[var(--color-warning)]/10 border border-[var(--color-warning)]/30">
                      <span className="material-symbols-outlined text-[var(--color-warning)] mt-0.5">
                        warning
                      </span>
                      <p className="text-sm text-[var(--color-warning)]">
                        Document type not recognized. Check that this is a TSP statement or supported file.
                      </p>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3 p-4 rounded-lg bg-loss-subtle border border-[var(--color-loss)]/30">
                      <span className="material-symbols-outlined text-loss mt-0.5">
                        report
                      </span>
                      <div className="text-sm text-loss">
                        <p className="font-semibold mb-1">
                          Commit blocked — parser could not extract core data
                        </p>
                        <p className="text-xs opacity-90">
                          The document was recognized as{" "}
                          <strong>
                            {PARSER_LABELS[uploadResult.parser_type] ||
                              uploadResult.parser_type}
                          </strong>
                          , but required fields are missing. The blocking
                          warning below explains what's wrong. Re-upload
                          only after the parser is updated.
                        </p>
                      </div>
                    </div>
                  )
                ) : (
                  /* Preview table */
                  <div className="rounded-lg border border-border overflow-hidden">
                    <table className="w-full text-sm">
                      <tbody>
                        {Object.entries(uploadResult.preview).map(([key, value]) => (
                          <tr
                            key={key}
                            className="border-b border-border last:border-b-0"
                          >
                            <td className="px-4 py-2.5 text-muted-foreground font-medium whitespace-nowrap bg-muted/30 w-[40%]">
                              {snakeToTitle(key)}
                            </td>
                            <td className="px-4 py-2.5 text-foreground text-numeric">
                              {typeof value === "object" && value !== null ? (
                                <div className="space-y-1">
                                  {Object.entries(value).map(([k, v]) => (
                                    <div key={k} className="flex justify-between text-xs">
                                      <span className="text-muted-foreground">{snakeToTitle(k)}</span>
                                      <span className="font-medium">{String(v)}</span>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                String(value)
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Warnings */}
                {uploadResult.warnings.length > 0 && (
                  <div className="space-y-2">
                    {uploadResult.warnings.map((w, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2 text-xs text-[var(--color-warning)]"
                      >
                        <span className="material-symbols-outlined text-sm mt-px">warning</span>
                        <span>{w}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border bg-muted/30">
                <button
                  onClick={resetToIdle}
                  className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground rounded-lg hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCommit}
                  disabled={!uploadResult.can_commit}
                  className={`inline-flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-lg transition-all duration-150 ${
                    uploadResult.can_commit
                      ? "bg-primary hover:bg-[var(--primary-hover)] text-primary-foreground shadow-sm hover:shadow-md active:scale-[0.98]"
                      : "bg-muted text-muted-foreground cursor-not-allowed"
                  }`}
                >
                  <span className="material-symbols-outlined text-[16px]">download_done</span>
                  {commitLabel}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
