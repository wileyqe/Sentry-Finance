import { useState, useEffect, useCallback } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import ErrorBoundary from "./components/ErrorBoundary";
import ToastContainer from "./components/ToastContainer";
import RefreshBanner from "./components/RefreshBanner";
import ApiStatus from "./components/ApiStatus";
import { AccountsContext, buildAccountNames, type AccountInfo } from "./lib/accounts";
import { apiFetch } from "./lib/api";
import DashboardPage from "./pages/DashboardPage";
import TransactionsPage from "./pages/TransactionsPage";
import ReportsPage from "./pages/ReportsPage";
import AccountsPage from "./pages/AccountsPage";
import InvestmentsPage from "./pages/InvestmentsPage";
import BudgetsPage from "./pages/BudgetsPage";
import CashFlowPage from "./pages/CashFlowPage";

// Animated routes wrapper
function AnimatedRoutes() {
  const location = useLocation();
  return (
    <div key={location.pathname} className="page-enter flex-1 flex flex-col min-w-0 overflow-hidden">
      <ErrorBoundary>
        <Routes location={location}>
          <Route path="/" element={<Navigate to="/dashboard" />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/transactions" element={<TransactionsPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/investments" element={<InvestmentsPage />} />
          <Route path="/budgets" element={<BudgetsPage />} />
          <Route path="/cash-flow" element={<CashFlowPage />} />
        </Routes>
      </ErrorBoundary>
    </div>
  );
}

function App() {
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchAccountsAndCategories = useCallback(() => {
    setLoading(true);
    Promise.all([
      apiFetch("/api/accounts").catch(() => ({ accounts: [] })),
      apiFetch("/api/categories").catch(() => ({ categories: [] })),
    ]).then(([accData, catData]) => {
      const accts = (accData.accounts || []).map((a: any) => ({
        id: a.id,
        name: a.name,
        institution_id: a.institution_id,
        type: a.type,
        last4: a.last4 || "",
      }));
      setAccounts(accts);
      // Categories from API: array of { category, count } objects or string[]
      const cats = (catData.categories || []).map((c: any) =>
        typeof c === "string" ? c : c.category
      );
      setCategories(cats.length > 0 ? cats : [
        "Income", "Mortgage", "Transfer", "Groceries", "Dining", "Shopping",
        "Entertainment", "Travel", "Utilities", "Auto", "Medical", "Insurance",
        "Home Improvement", "Uncategorized",
      ]);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    fetchAccountsAndCategories();
  }, [fetchAccountsAndCategories]);

  const accountNames = buildAccountNames(accounts);

  return (
    <AccountsContext.Provider value={{ accounts, accountNames, categories, loading }}>
      <Router>
        <div className="flex h-screen w-full bg-background text-foreground antialiased overflow-hidden selection:bg-emerald-500/20">
          <Sidebar />
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            <ApiStatus />
            <RefreshBanner onRefreshComplete={fetchAccountsAndCategories} />
            <Header />
            <AnimatedRoutes />
          </div>
        </div>
        <ToastContainer />
      </Router>
    </AccountsContext.Provider>
  );
}

export default App;
