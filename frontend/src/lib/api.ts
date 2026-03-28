/**
 * Centralized API client and React hooks for data fetching.
 *
 * Replaces scattered fetch() calls with a single useApi() hook that
 * provides loading, error, and data states. All endpoints go through
 * apiFetch() which handles base URL, error parsing, and non-2xx responses.
 */

import { useState, useEffect, useCallback, useRef } from "react";

const API_BASE = "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Thin wrapper around fetch() that:
 * - Prepends API_BASE to relative paths
 * - Throws ApiError for non-2xx responses
 * - Parses JSON automatically
 */
export async function apiFetch<T = any>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

interface UseApiState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | Error | null;
}

interface UseApiReturn<T> extends UseApiState<T> {
  refetch: () => void;
}

/**
 * React hook for GET requests. Automatically fetches on mount and
 * when `path` changes. Returns { data, loading, error, refetch }.
 *
 * @param path  API path (e.g. "/api/accounts")
 * @param opts  Optional: `skip` to conditionally skip the fetch,
 *              `fallback` default value while loading
 */
export function useApi<T = any>(
  path: string | null,
  opts?: { skip?: boolean; fallback?: T }
): UseApiReturn<T> {
  const [state, setState] = useState<UseApiState<T>>({
    data: opts?.fallback ?? null,
    loading: !opts?.skip && path !== null,
    error: null,
  });
  const mountedRef = useRef(true);

  const doFetch = useCallback(() => {
    if (!path || opts?.skip) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    apiFetch<T>(path)
      .then((data) => {
        if (mountedRef.current) setState({ data, loading: false, error: null });
      })
      .catch((err) => {
        if (mountedRef.current)
          setState((s) => ({ ...s, loading: false, error: err }));
      });
  }, [path, opts?.skip]);

  useEffect(() => {
    mountedRef.current = true;
    doFetch();
    return () => {
      mountedRef.current = false;
    };
  }, [doFetch]);

  return { ...state, refetch: doFetch };
}

/**
 * Hook for mutating API calls (POST, PUT, PATCH, DELETE).
 * Returns [mutate, { loading, error, data }].
 */
export function useMutation<T = any>(
  method: "POST" | "PUT" | "PATCH" | "DELETE" = "POST"
) {
  const [state, setState] = useState<UseApiState<T>>({
    data: null,
    loading: false,
    error: null,
  });

  const mutate = useCallback(
    async (path: string, body?: any): Promise<T | null> => {
      setState({ data: null, loading: true, error: null });
      try {
        const data = await apiFetch<T>(path, {
          method,
          headers: body ? { "Content-Type": "application/json" } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        });
        setState({ data, loading: false, error: null });
        return data;
      } catch (err: any) {
        setState({ data: null, loading: false, error: err });
        return null;
      }
    },
    [method]
  );

  return [mutate, state] as const;
}
