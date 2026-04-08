/**
 * ViewSelector — top-of-dashboard chip group that switches between owner
 * views and the household roll-up.
 *
 * Hard-coded to a 3-button layout for the current single-user dev phase:
 *   [ Quintin ]  [ Household ]  [ Amy ]
 *
 * Quintin is "me" and the default view; Amy is a structural placeholder
 * (no synthetic data attached). Household is the unfiltered roll-up.
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

// Visual order: Quintin (left), Household (center), Amy (right).
// Hardcoded for now; revisit if/when more owners come online.
const CHIPS: ChipDef[] = [
  { value: "quintin", label: "Quintin", icon: "👤" },
  { value: "ours",    label: "Household", icon: "🏠" },
  { value: "amy",     label: "Amy", icon: "👤" },
];

export default function ViewSelector() {
  const { view, setView } = useView();

  return (
    <div className="view-selector">
      <div className="view-selector__pills">
        {CHIPS.map((opt) => {
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
