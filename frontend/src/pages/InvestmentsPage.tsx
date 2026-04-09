import { useView } from "../context/ViewContext";

/**
 * Investments — empty-state shell (P13 rebuild).
 *
 * The previous 912-line page (performance / holdings / allocation /
 * contributions-vs-performance tabs) was removed as part of the
 * ground-up rebuild.  No data sources are wired to this page yet.
 *
 * Route, sidebar entry, and header page meta are intentionally kept so
 * the rebuild can land incrementally without breaking navigation.
 */
export default function InvestmentsPage() {
  // View context is still consumed so the owner chip on the header
  // continues to function, even though this page has no data to filter.
  useView();

  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <span className="material-symbols-outlined text-6xl text-slate-400 mb-4">
        trending_up
      </span>
      <h1 className="text-2xl font-semibold text-slate-200 mb-2">
        Investments
      </h1>
      <p className="max-w-md text-sm text-slate-400">
        The investments view is being rebuilt from the ground up.
        No data sources are connected yet.
      </p>
    </div>
  );
}
