import { useState } from "react";
import { NavLink } from "react-router-dom";

const Sidebar = () => {
  const [isCollapsed, setIsCollapsed] = useState(false);

  const getLinkClass = ({ isActive }: { isActive: boolean }) => {
    return `flex items-center ${isCollapsed ? 'justify-center' : 'gap-3'} px-3 py-2 rounded-lg transition-colors ${
      isActive
        ? "bg-primary/10 text-primary"
        : "text-slate-600 dark:text-slate-400 hover:bg-primary/5 hover:text-primary"
    }`;
  };

  const getIconClass = ({ isActive }: { isActive: boolean }) => {
    return `material-symbols-outlined text-[20px] shrink-0 ${isActive ? "fill-[1]" : ""}`;
  };

  return (
    <aside className={`${isCollapsed ? 'w-20' : 'w-64'} flex-shrink-0 border-r border-slate-200 dark:border-primary/10 bg-white dark:bg-background-dark flex flex-col transition-all duration-300 relative`}>
      
      {/* Toggle Button */}
      <button 
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="absolute -right-3 top-6 size-6 bg-white dark:bg-background-dark border border-slate-200 dark:border-primary/20 rounded-full flex items-center justify-center text-slate-500 hover:text-primary shadow-sm z-20"
      >
        <span className="material-symbols-outlined text-sm">{isCollapsed ? 'chevron_right' : 'chevron_left'}</span>
      </button>

      <div className={`p-6 flex items-center ${isCollapsed ? 'justify-center' : 'gap-3'}`}>
        <div className="size-10 shrink-0 bg-primary/20 rounded-lg flex items-center justify-center text-primary">
          <span className="material-symbols-outlined font-bold">account_balance_wallet</span>
        </div>
        {!isCollapsed && (
          <div className="overflow-hidden">
            <h1 className="text-lg font-bold leading-tight tracking-tight whitespace-nowrap">WealthPro</h1>
            <p className="text-xs text-slate-500 dark:text-primary/60 font-medium whitespace-nowrap">Premium Finance</p>
          </div>
        )}
      </div>
      
      <nav className={`flex-1 ${isCollapsed ? 'px-3' : 'px-4'} space-y-2`}>
        <NavLink to="/dashboard" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Dashboard">dashboard</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Dashboard</span>}
            </>
          )}
        </NavLink>
        <NavLink to="/transactions" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Transactions">receipt_long</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Transactions</span>}
            </>
          )}
        </NavLink>
        <NavLink to="/reports" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Reports">assessment</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Reports</span>}
            </>
          )}
        </NavLink>
        <NavLink to="/accounts" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Accounts">account_balance</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Accounts</span>}
            </>
          )}
        </NavLink>
        <NavLink to="/budgets" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Budgets">pie_chart</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Budgets</span>}
            </>
          )}
        </NavLink>
        <NavLink to="/investments" className={getLinkClass}>
          {({ isActive }) => (
            <>
              <span className={getIconClass({ isActive })} title="Investments">trending_up</span>
              {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Investments</span>}
            </>
          )}
        </NavLink>
      </nav>
      
      <div className={`p-4 border-t border-slate-200 dark:border-primary/10 ${isCollapsed ? 'flex flex-col items-center' : ''}`}>
        <a className={`flex items-center ${isCollapsed ? 'justify-center' : 'gap-3'} px-3 py-2 text-slate-600 dark:text-slate-400 hover:bg-primary/5 hover:text-primary rounded-lg transition-colors w-full`} href="#" title="Settings">
          <span className="material-symbols-outlined text-[20px] shrink-0">settings</span>
          {!isCollapsed && <span className="text-sm font-medium whitespace-nowrap">Settings</span>}
        </a>
        <div className={`mt-4 flex items-center ${isCollapsed ? 'justify-center' : 'gap-3 px-3'}`}>
          <div className="size-8 shrink-0 rounded-full bg-slate-800 border border-primary/30 flex items-center justify-center overflow-hidden">
            <img alt="User Avatar" className="w-full h-full object-cover" src="https://lh3.googleusercontent.com/aida-public/AB6AXuAj4LOCsdljFE2d2m2I18SQbmAlLza8SAlBFUcXEvnlWAk6AIJVvlocEnVO6gg-x5OBUmeOxG4aDZS2eg2GLvXdNgHkUymXvii_t-rV23MlNJy3pmySTl_dFRuuua8k0oV1YEyhbjx4I9NWV5yoh8j09iHKal3E8EQFxVEHhq6tRmNOUNt0eX47VCAQoZaeAoZJ5Hkg4WFJVe3vGJ8L8AJnWAxPWpEmWzzFDxSEo0VB5MxCqeI5SMWTiXSdAMg53CuUCgpKp1nE0SU" />
          </div>
          {!isCollapsed && (
            <div className="flex-1 min-w-0 overflow-hidden">
              <p className="text-xs font-semibold truncate whitespace-nowrap">Alex Morgan</p>
              <p className="text-[10px] text-slate-500 whitespace-nowrap">Pro Member</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
