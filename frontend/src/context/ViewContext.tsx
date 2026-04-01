/**
 * ViewContext — Multi-user view state management.
 *
 * Provides current view (mine/theirs/ours), the resolved owner_id param,
 * and the list of configured owners. Persists active view to localStorage.
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { apiFetch } from "../lib/api";

export type ViewMode = "ours" | "mine" | "theirs";

interface Owner {
  id: string;
  display_name: string;
  created_at?: string;
}

interface ViewContextValue {
  view: ViewMode;
  setView: (v: ViewMode) => void;
  /** Query param value to pass to &owner_id=. null = no filter. */
  ownerParam: string | null;
  multiUserEnabled: boolean;
  owners: Owner[];
  loading: boolean;
  refetchOwners: () => void;
}

const ViewContext = createContext<ViewContextValue>({
  view: "ours",
  setView: () => {},
  ownerParam: null,
  multiUserEnabled: false,
  owners: [],
  loading: true,
  refetchOwners: () => {},
});

const STORAGE_KEY = "sentry:active_view";

export function ViewProvider({ children }: { children: ReactNode }) {
  const [view, setViewInternal] = useState<ViewMode>(() => {
    try {
      return (localStorage.getItem(STORAGE_KEY) as ViewMode) || "ours";
    } catch {
      return "ours";
    }
  });
  const [multiUserEnabled, setMultiUserEnabled] = useState(false);
  const [owners, setOwners] = useState<Owner[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchState = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiFetch<{ enabled: boolean }>("/api/settings/multi-user-enabled").catch(() => ({ enabled: false })),
      apiFetch<{ owners: Owner[] }>("/api/owners").catch(() => ({ owners: [] })),
    ]).then(([mu, ow]) => {
      setMultiUserEnabled(mu.enabled);
      setOwners(ow.owners || []);
      setLoading(false);
    });
  }, []);

  useEffect(() => { fetchState(); }, [fetchState]);

  const setView = useCallback((v: ViewMode) => {
    setViewInternal(v);
    try { localStorage.setItem(STORAGE_KEY, v); } catch {}
  }, []);

  // Resolve ownerParam from the active view
  const ownerParam = view === "ours" ? null : view;

  return (
    <ViewContext.Provider
      value={{
        view,
        setView,
        ownerParam,
        multiUserEnabled,
        owners,
        loading,
        refetchOwners: fetchState,
      }}
    >
      {children}
    </ViewContext.Provider>
  );
}

export function useView() {
  return useContext(ViewContext);
}
