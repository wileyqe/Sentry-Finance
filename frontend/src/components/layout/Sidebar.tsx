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
        className="absolute -right-3 top-7 size-6 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-full flex items-center justify-center text-slate-400 hover:text-emerald-500 shadow-sm z-30 transition-colors duration-150"
      >
        <span className="material-symbols-outlined text-[14px]">
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
                >
                  {icon}
                </span>
                {!isCollapsed && (
                  <span className={`text-[13.5px] font-medium whitespace-nowrap ${isActive ? "font-semibold" : ""}`}>
                    {label}
                  </span>
                )}
                {isActive && !isCollapsed && (
                  <div className="ml-auto size-1.5 rounded-full bg-emerald-500" />
                )}
              </div>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className={`p-2 border-t border-slate-100 dark:border-slate-800/60 flex flex-col gap-1`}>
        {/* Settings */}
        <a
          href="#"
          title="Settings"
          className={`flex items-center ${isCollapsed ? "justify-center" : "gap-3"} rounded-xl px-3 py-2.5 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-all duration-150 group`}
        >
          <span className="material-symbols-outlined text-[20px] shrink-0 group-hover:rotate-45 transition-transform duration-300">settings</span>
          {!isCollapsed && <span className="text-[13.5px] font-medium">Settings</span>}
        </a>

        {/* User profile */}
        <div
          className={`flex items-center ${isCollapsed ? "justify-center" : "gap-3"} rounded-xl px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors duration-150 cursor-pointer group`}
        >
          <div className="size-8 shrink-0 rounded-full ring-2 ring-emerald-500/30 overflow-hidden bg-slate-200">
            <img
              alt="User Avatar"
              className="w-full h-full object-cover"
              src="https://lh3.googleusercontent.com/aida-public/AB6AXuAj4LOCsdljFE2d2m2I18SQbmAlLza8SAlBFUcXEvnlWAk6AIJVvlocEnVO6gg-x5OBUmeOxG4aDZS2eg2GLvXdNgHkUymXvii_t-rV23MlNJy3pmySTl_dFRuuua8k0oV1YEyhbjx4I9NWV5yoh8j09iHKal3E8EQFxVEHhq6tRmNOUNt0eX47VCAQoZaeAoZJ5Hkg4WFJVe3vGJ8L8AJnWAxPWpEmWzzFDxSEo0VB5MxCqeI5SMWTiXSdAMg53CuUCgpKp1nE0SU"
            />
          </div>
          {!isCollapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-semibold text-slate-800 dark:text-slate-100 truncate">Alex Morgan</p>
              <p className="text-[10px] text-slate-400 uppercase tracking-wider">Admin</p>
            </div>
          )}
          {!isCollapsed && (
            <span className="material-symbols-outlined text-slate-300 text-[16px] group-hover:text-slate-500 transition-colors shrink-0">more_vert</span>
          )}
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
