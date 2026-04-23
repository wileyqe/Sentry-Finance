import { useState } from "react";
import { NavLink } from "react-router-dom";

const NAV_LINKS = [
  { to: "/dashboard",    icon: "dashboard",         label: "Dashboard" },
  { to: "/transactions", icon: "receipt_long",       label: "Transactions" },
  { to: "/cash-flow",    icon: "waterfall_chart",    label: "Cash Flow" },
  { to: "/reports",      icon: "assessment",         label: "Reports" },
  { to: "/accounts",     icon: "account_balance",    label: "Accounts" },
  { to: "/budgets",      icon: "pie_chart",           label: "Budgets" },
  { to: "/investments",  icon: "trending_up",         label: "Investments" },
  { to: "/documents",    icon: "upload_file",         label: "Documents" },
  { to: "/review/monthly", icon: "event_note",         label: "Monthly Review" },
  { to: "/review/yearly",  icon: "emoji_events",        label: "Yearly Review" },
];

const Sidebar = () => {
  const [isCollapsed, setIsCollapsed] = useState(false);

  return (
    <aside
      className={`${
        isCollapsed ? "w-[72px]" : "w-60"
      } flex-shrink-0 border-r border-slate-200 dark:border-slate-800/80 bg-white dark:bg-[#060608] flex flex-col transition-all duration-300 ease-out relative z-20`}
    >
      {/* Collapse toggle */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        aria-label="Toggle sidebar"
        className="focus-ring absolute -right-3 top-7 size-6 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-full flex items-center justify-center text-slate-400 hover:text-emerald-500 shadow-sm z-30 transition-colors duration-150"
      >
        <span className="material-symbols-outlined text-[14px]" aria-hidden="true">
          {isCollapsed ? "chevron_right" : "chevron_left"}
        </span>
      </button>

      {/* Logo */}
      <div className={`flex items-center shrink-0 w-full transition-all duration-300 ${isCollapsed ? "justify-center h-16 px-4" : "justify-center py-6"}`}>
        <img
          src="/logo.png"
          alt="Sentry Finance Logo"
          className={`shrink-0 transition-all duration-300 shadow-sm border-[3px] border-[color:var(--color-loss)] rounded-none ${isCollapsed ? "w-8 h-8" : "w-40 h-40"}`}
        />
      </div>

      {/* Navigation */}
      <nav className={`flex-1 flex flex-col gap-0.5 px-2 pt-2 overflow-hidden`}>
        {NAV_LINKS.map(({ to, icon, label }) => (
          <NavLink key={to} to={to} title={label}>
            {({ isActive }) => (
              <div
                className={`flex items-center ${isCollapsed ? "justify-center" : "gap-3"} rounded-xl px-3 py-2.5 transition-all duration-150 group ${
                  isActive
                    ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                    : "text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800/60 hover:text-slate-800 dark:hover:text-slate-200"
                }`}
              >
                <span
                  className={`material-symbols-outlined text-[20px] shrink-0 transition-transform duration-150 ${
                    isActive ? "text-emerald-500" : "group-hover:scale-110"
                  }`}
                  aria-hidden="true"
                >
                  {icon}
                </span>
                {!isCollapsed && (
                  <span className={`text-[13.5px] font-medium whitespace-nowrap ${isActive ? "font-semibold" : ""}`}>
                    {label}
                  </span>
                )}
              </div>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className={`p-2 border-t border-slate-100 dark:border-slate-800/60 flex flex-col gap-1`}>
        {/* Settings */}
        <NavLink
          to="/settings"
          title="Settings"
          className={({ isActive }) =>
            `flex items-center ${isCollapsed ? "justify-center" : "gap-3"} rounded-xl px-3 py-2.5 transition-all duration-150 group ${
              isActive
                ? "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                : "text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/60"
            }`
          }
        >
          <span className="material-symbols-outlined text-[20px] shrink-0 group-hover:rotate-45 transition-transform duration-300" aria-hidden="true">settings</span>
          {!isCollapsed && <span className="text-[13.5px] font-medium">Settings</span>}
        </NavLink>

      </div>
    </aside>
  );
};

export default Sidebar;
