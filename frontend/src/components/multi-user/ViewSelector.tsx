/**
 * ViewSelector — top-of-dashboard chip group that switches between owner
 * views and the household roll-up.
 *
 * 3-button layout for the current single-user dev phase:
 *   [ Quintin ]  [ Household ]  [ Amy ]
 *
 * Quintin is "me" and the default view; Amy is a structural placeholder
 * (no synthetic data attached). Household is the unfiltered roll-up.
 *
 * Display labels are pulled from `useView().owners` so renames in
 * Settings flow through immediately. The slot order — primary owner,
 * household, secondary owner — is intentional for the dev phase; when
 * a third owner ships, this will become a fully owners-driven render.
 *
 * Renders unconditionally — multi-user mode no longer gates visibility,
 * since the chip switcher IS the multi-user UX entrypoint.
 */

import { useView, type ViewMode } from "../../context/ViewContext";
import "./ViewSelector.css";

interface ChipDef {
  value: ViewMode;
  label: string;
  icon: string;
}

export default function ViewSelector() {
  const { view, setView, owners } = useView();

  const ownerById = Object.fromEntries(owners.map((o) => [o.id, o]));
  const quintin = ownerById["quintin"];
  const amy = ownerById["amy"];

  const chips: ChipDef[] = [
    quintin && {
      value: "quintin" as ViewMode,
      label: quintin.display_name,
      icon: "👤",
    },
    { value: "ours" as ViewMode, label: "Household", icon: "🏠" },
    amy && {
      value: "amy" as ViewMode,
      label: amy.display_name,
      icon: "👤",
    },
  ].filter(Boolean) as ChipDef[];

  return (
    <div className="view-selector">
      <div className="view-selector__pills">
        {chips.map((opt) => {
          const isActive = view === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              className={`view-selector__pill${isActive ? " view-selector__pill--active" : ""}`}
              onClick={() => setView(opt.value)}
              title={`View ${opt.label} data`}
              aria-pressed={isActive}
            >
              <span className="view-selector__icon">{opt.icon}</span>
              <span className="view-selector__label">{opt.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
