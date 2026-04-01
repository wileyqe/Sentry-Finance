/**
 * useOwnerApi — view-aware wrapper around useApi.
 *
 * Automatically appends `owner_id=<id>` to the query path based on
 * the active view from ViewContext.  When the view is "ours" (household),
 * no owner_id is added and the backend returns unfiltered data.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useOwnerApi<T>("/api/reports/spending?start_date=...");
 *
 * The hook re-fetches whenever the view changes.
 */

import { useMemo } from "react";
import { useView } from "../context/ViewContext";
import { useApi } from "./api";

/**
 * Appends owner_id to a URL path, handling existing query strings.
 */
function appendOwner(path: string, ownerId: string | null): string {
  if (!ownerId) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}owner_id=${encodeURIComponent(ownerId)}`;
}

export function useOwnerApi<T = any>(
  path: string | null,
  opts?: { skip?: boolean; fallback?: T }
) {
  const { ownerParam } = useView();

  const resolvedPath = useMemo(
    () => (path ? appendOwner(path, ownerParam) : null),
    [path, ownerParam]
  );

  return useApi<T>(resolvedPath, opts);
}
