/**
 * DocumentsPage — Dedicated page at /documents.
 *
 * Shows the DocumentDrop zone at the top and a history table of
 * recent document imports below.
 */

import { useState, useEffect, useCallback } from "react";
import DocumentDrop from "@/components/DocumentDrop";
import { EmptyState } from "@/components/ui/empty-state";
import { apiFetch } from "@/lib/api";

interface DocumentRecord {
  id: number;
  file_name: string;
  parser_type: string;
  file_size: number | null;
  dropped_at: string;
  committed_at: string | null;
  summary_json: string | null;
}

const PARSER_LABELS: Record<string, string> = {
  tsp_statement: "TSP Statement",
  mypay_ras: "myPay RAS",
  unknown: "Unknown",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso + (iso.includes("T") ? "" : "T00:00:00"));
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function formatSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = useCallback(() => {
    setLoading(true);
    apiFetch<{ documents: DocumentRecord[] }>("/api/documents/history?limit=50")
      .then((res) => setDocuments(res.documents || []))
      .catch(() => setDocuments([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-50 tracking-tight">
          Documents
        </h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Import statements and pay documents by dropping them here.
        </p>
      </div>

      {/* Drop zone */}
      <DocumentDrop onCommitSuccess={fetchHistory} />

      {/* History table */}
      <div className="card-l1 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700/60">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[18px] text-slate-400">history</span>
            <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Recent Imports
            </h2>
          </div>
          <span className="text-xs text-muted-foreground">{documents.length} document{documents.length !== 1 ? "s" : ""}</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-6 w-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          </div>
        ) : documents.length === 0 ? (
          <EmptyState
            icon={<span className="material-symbols-outlined">folder_open</span>}
            title="No documents imported yet"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700/60 bg-slate-50/50 dark:bg-slate-800/20">
                  <th className="text-left px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Date
                  </th>
                  <th className="text-left px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    File Name
                  </th>
                  <th className="text-left px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Type
                  </th>
                  <th className="text-left px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Size
                  </th>
                  <th className="text-left px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr
                    key={doc.id}
                    className="border-b border-slate-100 dark:border-slate-800/40 last:border-b-0 hover:bg-slate-50/50 dark:hover:bg-slate-800/20 transition-colors"
                  >
                    <td className="px-5 py-3 text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {formatDate(doc.dropped_at)}
                    </td>
                    <td className="px-5 py-3 text-slate-800 dark:text-slate-100 font-medium truncate max-w-[200px]">
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-[16px] text-slate-400 shrink-0">
                          {doc.file_name?.endsWith(".pdf") ? "picture_as_pdf" : "table_chart"}
                        </span>
                        <span className="truncate">{doc.file_name}</span>
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <span className="chip-l2">
                        {PARSER_LABELS[doc.parser_type] || doc.parser_type}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-slate-500 dark:text-slate-400 text-numeric whitespace-nowrap">
                      {formatSize(doc.file_size)}
                    </td>
                    <td className="px-5 py-3">
                      {doc.committed_at ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-gain">
                          <span className="material-symbols-outlined text-[14px]">check_circle</span>
                          Committed
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-yellow-600 dark:text-yellow-400">
                          <span className="material-symbols-outlined text-[14px]">schedule</span>
                          Pending
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
