/**
 * ViewContext — Multi-user view state management.
 *
 * Provides current view, the resolved owner_id param,
 * and the list of configured owners. Persists active view to localStorage.
 *
 * ViewMode is `"ours"` (the household / unfiltered view) OR any owner_id
 * string returned by `/api/owners`. The legacy `"mine"` / `"theirs"`
 * pivots have been removed — every owner is now a discrete view.
 */

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { apiFetch } from "../lib/api";

/** Either the household view, or a specific owner_id. */
export type ViewMode = "ours" | string;

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

const DEFAULT_VIEW: ViewMode = "quintin";

const ViewContext = createContext<ViewContextValue>({
  view: DEFAULT_VIEW,
  setView: () => {},
  ownerParam: DEFAULT_VIEW,
  multiUserEnabled: false,
  owners: [],
  loading: true,
  refetchOwners: () => {},
});

const STORAGE_KEY = "sentry:active_view";

export function ViewProvider({ children }: { children: ReactNode }) {
  const [view, setViewInternal] = useState<ViewMode>(() => {
    try {
      return (localStorage.getItem(STORAGE_KEY) as ViewMode) || DEFAULT_VIEW;
    } catch {
      return DEFAULT_VIEW;
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

  // Defensive fallback: if the persisted view points at an owner that no
  // longer exists (deleted/archived in a future feature, or YAML defaults
  // diverged from the DB), reset to the household roll-up so the dashboard
  // never gets stuck on an invalid filter.
  useEffect(() => {
    if (loading) return;
    const validIds = new Set<string>(["ours", ...owners.map((o) => o.id)]);
    if (!validIds.has(view)) {
      setView("ours");
    }
  }, [loading, owners, view, setView]);

  // Resolve ownerParam from the active view: "ours" → no filter,
  // anything else → the owner_id string.
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
