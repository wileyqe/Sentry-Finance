import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { apiFetch, type ApiError } from "@/lib/api";
import { todayIsoLocal } from "@/lib/dateUtils";

export interface BackendRuntimeContext {
  contract_version: string;
  runtime: {
    mode: string;
    process_id: number;
  };
  database: {
    path: string;
    path_hash: string;
    schema_version: number;
    live_fingerprint: string;
  };
  trusted_seed: {
    present: boolean;
    seed_version: string | null;
    end_date: string | null;
    reference_date: string | null;
    reference_datetime: string | null;
    years: number | null;
    generated_at: string | null;
    manifest_fingerprint: string | null;
    fingerprint_match: boolean;
  };
  clock: {
    source: string;
    reference_date: string;
    reference_datetime: string;
    fixed: boolean;
  };
  proof: {
    trusted_seed_ready: boolean;
    blocking_reasons: string[];
  };
}

interface RuntimeContextValue {
  context: BackendRuntimeContext | null;
  loading: boolean;
  error: ApiError | Error | null;
  referenceDate: string;
  ready: boolean;
  refresh: () => void;
}

const RuntimeContext = createContext<RuntimeContextValue | null>(null);

export function RuntimeProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<BackendRuntimeContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    apiFetch<BackendRuntimeContext>("/api/runtime/context")
      .then((data) => {
        if (!active) return;
        setContext(data);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setContext(null);
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const value = useMemo<RuntimeContextValue>(() => ({
    context,
    loading,
    error,
    referenceDate: context?.clock.reference_date ?? todayIsoLocal(),
    ready: !!context,
    refresh: () => setReloadKey((k) => k + 1),
  }), [context, loading, error]);

  return (
    <RuntimeContext.Provider value={value}>
      {children}
    </RuntimeContext.Provider>
  );
}

export function useRuntimeContext(): RuntimeContextValue {
  const value = useContext(RuntimeContext);
  if (!value) {
    throw new Error("useRuntimeContext must be used within RuntimeProvider");
  }
  return value;
}
