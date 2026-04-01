/**
 * ViewSelector — dropdown that switches between Mine / Partner / Household views.
 *
 * Only renders when multi-user mode is enabled and owners are configured.
 */

import { useView, type ViewMode } from "../../context/ViewContext";
import "./ViewSelector.css";

export default function ViewSelector() {
  const { view, setView, multiUserEnabled, owners, loading } = useView();

  if (loading || !multiUserEnabled || owners.length < 2) return null;

  const options: { value: ViewMode; label: string; icon: string }[] = [
    { value: "ours", label: "Household", icon: "🏠" },
  ];

  owners.forEach((o) => {
    const mode = o.id as ViewMode;
    options.push({ value: mode, label: o.display_name, icon: "👤" });
  });

  return (
    <div className="view-selector">
      <div className="view-selector__pills">
        {options.map((opt) => (
          <button
            key={opt.value}
            className={`view-selector__pill${view === opt.value ? " view-selector__pill--active" : ""}`}
            onClick={() => setView(opt.value)}
            title={`View ${opt.label} data`}
          >
            <span className="view-selector__icon">{opt.icon}</span>
            <span className="view-selector__label">{opt.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
