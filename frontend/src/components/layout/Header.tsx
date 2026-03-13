import React from "react";
import { useLocation } from "react-router-dom";

const Header = () => {
  const location = useLocation();
  const path = location.pathname.substring(1);
  const title = path ? path.charAt(0).toUpperCase() + path.slice(1) : "Dashboard";

  return (
    <header className="h-16 border-b border-slate-200 dark:border-primary/10 flex items-center justify-between px-8 bg-white/50 dark:bg-background-dark/50 backdrop-blur-md sticky top-0 z-10 shrink-0">
      <h2 className="text-xl font-bold tracking-tight">{title}</h2>
      <div className="flex items-center gap-4">
        <div className="relative w-64">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 text-sm">search</span>
          <input className="w-full pl-10 pr-4 py-1.5 bg-slate-100 dark:bg-primary/5 border border-slate-200 dark:border-primary/20 rounded-lg text-sm focus:ring-1 focus:ring-primary focus:border-primary outline-none transition-all" placeholder={`Search ${path}...`} type="text"/>
        </div>
        <button className="size-10 flex items-center justify-center rounded-lg border border-slate-200 dark:border-primary/20 hover:bg-slate-50 dark:hover:bg-primary/10 transition-colors">
          <span className="material-symbols-outlined text-slate-500 dark:text-primary/70">notifications</span>
        </button>
      </div>
    </header>
  );
};

export default Header;
