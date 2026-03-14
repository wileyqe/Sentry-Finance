import { useLocation } from "react-router-dom";

const Header = () => {
  const location = useLocation();
  const path = location.pathname.substring(1);
  const title = path ? path.charAt(0).toUpperCase() + path.slice(1) : "Dashboard";

  return (
    <header className="h-20 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between px-12 bg-white dark:bg-[#050505] sticky top-0 z-10 shrink-0">
      <h2 className="text-2xl font-sans font-bold tracking-tight uppercase text-slate-900 dark:text-slate-100">{title}</h2>
      <div className="flex items-center gap-6">
        <div className="relative w-72">
          <span className="material-symbols-outlined absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-sm">search</span>
          <input className="w-full pl-12 pr-4 py-2 bg-slate-50 dark:bg-slate-900 border-2 border-transparent focus:border-emerald-500 rounded-none text-sm font-mono outline-none transition-all dark:text-slate-100 placeholder:text-slate-500 placeholder:uppercase placeholder:tracking-widest" placeholder={`Search ${path}...`} type="text"/>
        </div>
        <button className="size-10 flex items-center justify-center border-2 border-slate-200 dark:border-slate-800 hover:border-emerald-500 dark:hover:border-emerald-500 rounded-none bg-transparent transition-colors group">
          <span className="material-symbols-outlined text-slate-500 dark:text-slate-400 group-hover:text-emerald-500 transition-colors">notifications</span>
        </button>
      </div>
    </header>
  );
};

export default Header;
