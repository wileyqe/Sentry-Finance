import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import Header from "./components/layout/Header";
import DashboardPage from "./pages/DashboardPage";
import TransactionsPage from "./pages/TransactionsPage";
import ReportsPage from "./pages/ReportsPage";
import AccountsPage from "./pages/AccountsPage";
import InvestmentsPage from "./pages/InvestmentsPage";
import BudgetsPage from "./pages/BudgetsPage";

// Animated routes wrapper
function AnimatedRoutes() {
  const location = useLocation();
  return (
    <div key={location.pathname} className="page-enter flex-1 flex flex-col min-w-0 overflow-hidden">
      <Routes location={location}>
        <Route path="/" element={<Navigate to="/dashboard" />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/accounts" element={<AccountsPage />} />
        <Route path="/investments" element={<InvestmentsPage />} />
        <Route path="/budgets" element={<BudgetsPage />} />
      </Routes>
    </div>
  );
}

function App() {
  return (
    <Router>
      <div className="flex h-screen w-full bg-background text-foreground antialiased overflow-hidden selection:bg-emerald-500/20">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Header />
          <AnimatedRoutes />
        </div>
      </div>
    </Router>
  );
}

export default App;
