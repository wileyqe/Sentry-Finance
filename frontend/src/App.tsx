import { BrowserRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import DashboardPage from "./pages/DashboardPage";
import TransactionsPage from "./pages/TransactionsPage";
import ReportsPage from "./pages/ReportsPage";
import AccountsPage from "./pages/AccountsPage";
import InvestmentsPage from "./pages/InvestmentsPage";
import BudgetsPage from "./pages/BudgetsPage";

function App() {
  return (
    <Router>
      <div className="flex h-screen w-full bg-white dark:bg-[#050505] text-slate-900 dark:text-slate-100 antialiased overflow-hidden selection:bg-emerald-500/30">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 bg-white dark:bg-[#050505] overflow-hidden relative">
          <Header />
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/transactions" element={<TransactionsPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/accounts" element={<AccountsPage />} />
              <Route path="/investments" element={<InvestmentsPage />} />
              <Route path="/budgets" element={<BudgetsPage />} />
            </Routes>
        </div>
      </div>
    </Router>
  );
}

export default App;
