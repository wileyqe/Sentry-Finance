import { useState, useEffect } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, PieChart, Pie, Cell } from "recharts";

const formatPercent = (val: number) => {
  if (val > 0) return { text: `+${val.toFixed(2)}%`, color: "text-gain" };
  if (val < 0) return { text: `${val.toFixed(2)}%`, color: "text-loss" };
  return { text: "0.00%", color: "text-neutral" };
};

// Desaturated chart palette — 6 hues from our design system
const COLORS = [
  'oklch(0.52 0.13 155)',  // emerald
  'oklch(0.52 0.12 240)',  // steel blue
  'oklch(0.52 0.11 290)',  // indigo
  'oklch(0.55 0.11 45)',   // amber
  'oklch(0.50 0.09 320)',  // mauve
  'oklch(0.50 0.08 90)',   // olive
];

const TIMEFRAMES = ["1W", "1M", "3M", "6M", "YTD", "1Y", "5Y"] as const;

// Map timeframe buttons to month counts for the performance API
const TF_MONTHS: Record<string, number> = {
  '1W': 1,
  '1M': 1,
  '3M': 3,
  '6M': 6,
  'YTD': 12,
  '1Y': 12,
  '5Y': 60,
};

export default function InvestmentsPage() {
  const [activeTab, setActiveTab] = useState("Investments");
  const [activeTimeframe, setActiveTimeframe] = useState("3M");
  const [accountFilter, setAccountFilter] = useState("all");
  const [holdings, setHoldings] = useState<any[]>([]);
  const [allHoldings, setAllHoldings] = useState<any[]>([]);
  const [sectorData, setSectorData] = useState<any[]>([]);
  const [allSectorData, setAllSectorData] = useState<any[]>([]);
  const [performanceCards, setPerformanceCards] = useState<any[]>([
    { title: "Your Portfolio", periodReturn: 0, latestReturn: 0, isPrimary: true },
    { title: "S&P 500", periodReturn: 12.8, latestReturn: 0.9 },
    { title: "US Stocks", periodReturn: 13.1, latestReturn: 1.1 },
    { title: "US Bonds", periodReturn: 2.1, latestReturn: -0.1 },
  ]);
  const [performanceData, setPerformanceData] = useState<any[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [showAddHolding, setShowAddHolding] = useState(false);
  const [newHolding, setNewHolding] = useState({ ticker: '', shares: '', price: '', account_id: 'fidelity_inv_001' });
  const [expandedHolding, setExpandedHolding] = useState<string | null>(null);

  const timeframeLabel = activeTimeframe === '1W' ? 'Past Week' : activeTimeframe === '1M' ? 'Past Month' : `Past ${activeTimeframe}`;

  // Fetch investment accounts for the filter dropdown
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/accounts")
      .then(res => res.json())
      .then(data => {
        if (data.accounts) {
          const invAccounts = data.accounts.filter((a: any) => a.type === 'investment' || a.type === 'retirement');
          setAccounts(invAccounts);
        }
      })
      .catch(console.error);
  }, []);

  // Fetch holdings
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/investments/holdings")
      .then(res => res.json())
      .then(data => {
        if (data.holdings) {
          const totalValue = data.holdings.reduce((sum: number, h: any) => sum + (h.market_value || 0), 0);
          const processed = data.holdings.map((h: any, i: number) => ({
            id: i,
            security: h.ticker,
            ticker: h.ticker,
            price: h.close_price || 0,
            quantity: h.shares || 0,
            past3m: h.past_3m_return || 0,
            value: h.market_value || 0,
            weight: totalValue > 0 ? ((h.market_value || 0) / totalValue * 100) : 0,
            account_id: h.account_id || '',
          }));
          setAllHoldings(processed);
        }
      })
      .catch(console.error);
  }, []);

  // Fetch allocation
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/investments/allocation")
      .then(res => res.json())
      .then(data => {
        if (data.by_sector) {
          setAllSectorData(data.by_sector.map((s: any) => ({
             name: s.sector,
             value: s.value
          })));
        }
      })
      .catch(console.error);
  }, []);

  // Fetch performance data when timeframe changes
  useEffect(() => {
    const months = TF_MONTHS[activeTimeframe] || 3;
    fetch(`http://127.0.0.1:8000/api/investments/performance?months=${months}`)
      .then(res => res.json())
      .then(data => {
        if (data.monthly_returns && data.monthly_returns.length > 0) {
          // Build cumulative performance chart data
          let cumPortfolio = 0;
          const chartData = data.monthly_returns.map((mr: any) => {
            cumPortfolio += (mr.return_pct || 0);
            return {
              date: mr.month,
              portfolio: Number(cumPortfolio.toFixed(2)),
              sp500: Number((cumPortfolio * 0.9).toFixed(2)), // Simulated benchmark
              bonds: Number((cumPortfolio * 0.15).toFixed(2)), // Simulated bonds
            };
          });
          // Prepend a zero point
          if (chartData.length > 0) {
            chartData.unshift({
              date: 'Start',
              portfolio: 0,
              sp500: 0,
              bonds: 0,
            });
          }
          setPerformanceData(chartData);
          
          // Update performance card with actual data
          const totalReturn = cumPortfolio;
          setPerformanceCards(prev => prev.map(card => 
            card.isPrimary 
              ? { ...card, periodReturn: totalReturn, latestReturn: data.monthly_returns[data.monthly_returns.length - 1]?.return_pct || 0 }
              : card
          ));
        }
      })
      .catch(console.error);
  }, [activeTimeframe]);

  // Apply account filter
  useEffect(() => {
    if (accountFilter === 'all') {
      setHoldings(allHoldings);
      setSectorData(allSectorData);
    } else {
      const filtered = allHoldings.filter(h => h.account_id === accountFilter);
      setHoldings(filtered);
      // Recalculate weights for filtered
      const totalVal = filtered.reduce((s, h) => s + h.value, 0);
      const reweighted = filtered.map(h => ({
        ...h,
        weight: totalVal > 0 ? (h.value / totalVal * 100) : 0,
      }));
      setHoldings(reweighted);


      // Keep sector data from API for now
      setSectorData(allSectorData);
    }
  }, [accountFilter, allHoldings, allSectorData]);

  const totalPortfolioValue = holdings.reduce((s, h) => s + h.value, 0);

  // Tab content rendering
  const renderInvestmentsTab = () => (
    <>
      {/* Performance Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {performanceCards.map((card, idx) => {
          const periodStyle = formatPercent(card.periodReturn);
          const latestStyle = formatPercent(card.latestReturn);
          return (
            <div 
              key={idx} 
              className={`rounded-xl p-5 border transition-all duration-200 ${
                card.isPrimary 
                  ? "bg-white dark:bg-slate-900/50 border-slate-300 dark:border-slate-700 ring-1 ring-slate-200 dark:ring-slate-700" 
                  : "bg-white dark:bg-slate-900/30 border-slate-200 dark:border-slate-800"
              }`}
            >
              <h3 className={`font-semibold mb-4 ${card.isPrimary ? 'text-base text-slate-900 dark:text-white' : 'text-sm text-slate-600 dark:text-slate-400'}`}>
                {card.title}
              </h3>
              <div className="flex items-center gap-6">
                <div>
                  <p className="text-label mb-1">
                    {timeframeLabel}
                  </p>
                  <p className={`text-xl font-bold ${periodStyle.color}`}>{periodStyle.text}</p>
                </div>
                <div>
                  <p className="text-label mb-1">{timeframeLabel === 'Past Week' ? 'Past Day' : 'Latest Month'}</p>
                  <p className={`text-xl font-bold ${latestStyle.color}`}>{latestStyle.text}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Backtested Performance Chart */}
        <div className="lg:col-span-2 bg-white dark:bg-slate-900/30 border border-slate-200 dark:border-slate-800 rounded-xl p-6 flex flex-col h-[400px]">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-6">
              <h3 className="text-label">Backtested Performance</h3>
              <div className="flex items-center gap-4 text-xs font-bold">
                <div className="flex items-center gap-2">
                  <span className="size-2.5 rounded-full" style={{ backgroundColor: 'oklch(0.52 0.13 155)' }}></span>
                  <span className="text-slate-900 dark:text-slate-100">Your Portfolio</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="size-2.5 rounded-full bg-slate-300 dark:bg-slate-500"></span>
                  <span className="text-slate-500">US Bonds</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="size-2.5 rounded-full" style={{ backgroundColor: 'oklch(0.52 0.12 240)' }}></span>
                  <span className="text-slate-500">S&P 500</span>
                </div>
              </div>
            </div>
            <button className="text-slate-400 hover:text-primary transition-colors">
              <span className="material-symbols-outlined text-lg">download</span>
            </button>
          </div>
          
          <div className="flex-1 w-full min-h-0">
            {performanceData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performanceData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#334155" opacity={0.15} />
                  <ReferenceLine y={0} stroke="#64748b" strokeWidth={1} opacity={0.5} />
                  <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} dy={10} minTickGap={30} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: '#94a3b8' }} tickFormatter={(val) => `${val}%`} />
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px', color: '#fff', fontSize: '12px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)' }}
                    formatter={(value: any, name: any) => [`${Number(value).toFixed(2)}%`, name]}
                  />
                  <Line type="monotone" dataKey="portfolio" name="Your Portfolio" stroke="oklch(0.52 0.13 155)" strokeWidth={2.5} dot={false} activeDot={{ r: 5, strokeWidth: 0, fill: 'oklch(0.52 0.13 155)' }} />
                  <Line type="monotone" dataKey="sp500" name="S&P 500" stroke="oklch(0.52 0.12 240)" strokeWidth={2} dot={false} strokeDasharray="5 5" opacity={0.8} />
                  <Line type="monotone" dataKey="bonds" name="US Bonds" stroke="oklch(0.50 0.08 90)" strokeWidth={1.5} dot={false} opacity={0.65} strokeDasharray="3 3" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex-1 h-full flex items-center justify-center text-slate-400 text-sm">
                <div className="flex flex-col items-center gap-2">
                  <span className="material-symbols-outlined text-3xl">show_chart</span>
                  <p>Loading performance data...</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Sector Allocation Chart */}
        <div className="lg:col-span-1 bg-white dark:bg-slate-900/30 border border-slate-200 dark:border-slate-800 rounded-xl p-6 flex flex-col h-[400px] overflow-hidden">
          <div className="flex items-center justify-between mb-2 shrink-0">
            <div className="flex items-center gap-2">
              <h3 className="text-label">Sector Allocation</h3>
              <span className="bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-[10px] px-2 py-0.5 rounded-full font-semibold">{sectorData.length} Sectors</span>
            </div>
            <span className="material-symbols-outlined text-sm text-slate-400">pie_chart</span>
          </div>
          <div className="flex-1 w-full relative min-h-0">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px', color: '#fff', fontSize: '12px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)', zIndex: 1000 }}
                  itemStyle={{ color: '#fff', fontWeight: 'bold' }}
                  formatter={(value: any, name: any) => [`$${value.toLocaleString()}`, name]}
                />
                <Pie
                  data={sectorData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                  stroke="none"
                >
                  {sectorData.map((_entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          {/* Legend / Breakdown */}
          <div className="mt-2 space-y-2 overflow-y-auto custom-scrollbar pr-2 h-32 border-t border-slate-200 dark:border-primary/10 pt-2 shrink-0">
            {sectorData.map((sector, idx) => {
              const sectorTotal = sectorData.reduce((s, sec) => s + sec.value, 0);
              const pct = sectorTotal > 0 ? ((sector.value / sectorTotal) * 100).toFixed(1) : '0.0';
              return (
                <div key={sector.name} className="flex items-center justify-between text-xs hover:bg-slate-50 dark:hover:bg-primary/5 rounded px-1 transition-colors">
                  <div className="flex items-center gap-2">
                    <span className="size-2.5 rounded-full" style={{ backgroundColor: COLORS[idx % COLORS.length] }}></span>
                    <span className="font-semibold text-slate-700 dark:text-slate-300 truncate w-32" title={sector.name}>{sector.name}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500">{pct}%</span>
                    <span className="font-bold text-slate-900 dark:text-slate-100">${(sector.value / 1000).toFixed(1)}k</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );

  const renderHoldingsTab = () => (
    <div className="bg-white dark:bg-slate-900/30 border border-slate-200 dark:border-slate-800 rounded-xl overflow-hidden flex flex-col">
      <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="font-bold text-lg">Holdings</h3>
          <span className="text-slate-500 text-xs font-semibold">
            {holdings.length} positions • ${totalPortfolioValue.toLocaleString(undefined, { minimumFractionDigits: 0 })}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <button 
            onClick={() => setShowAddHolding(true)}
            className="flex items-center gap-2 px-4 py-2 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity"
          >
            <span className="material-symbols-outlined text-sm">add</span>
            Add holding
          </button>
        </div>
      </div>
      <div className="overflow-x-auto custom-scrollbar">
        <table className="w-full text-left border-collapse min-w-[800px]">
          <thead className="bg-slate-50/80 dark:bg-primary/5">
            <tr>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 w-[25%]">Security</th>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 text-center">Account</th>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 text-right">Price</th>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 text-right">Quantity</th>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 text-right">Value</th>
              <th className="px-6 py-4 text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-primary/60 border-b border-slate-200 dark:border-primary/10 text-right">Weight</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-primary/5">
            {holdings.filter(h => h.ticker !== 'CASH' && h.ticker !== 'Cash').map((h) => {
              const isExpanded = expandedHolding === h.ticker;
              return (
              <>
              <tr key={h.id} className="group hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors cursor-pointer" onClick={() => setExpandedHolding(isExpanded ? null : h.ticker)}>
                <td className="px-6 py-3.5">
                  <div className="flex items-center gap-3">
                    <div className="size-8 rounded bg-slate-100 dark:bg-slate-800 flex items-center justify-center font-bold text-xs text-slate-600 dark:text-slate-300">
                      {h.ticker.substring(0,2)}
                    </div>
                    <div>
                      <p className="font-semibold text-sm text-slate-900 dark:text-slate-100">{h.security}</p>
                      <p className="text-xs text-slate-400">{h.ticker}</p>
                    </div>
                    <span className={`material-symbols-outlined text-xs text-slate-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>chevron_right</span>
                  </div>
                </td>
                <td className="px-6 py-3.5 text-center">
                  <span className="text-xs font-medium text-slate-500 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                    {h.account_id ? (h.account_id.includes('fidelity') ? 'Fidelity' : h.account_id.includes('acorns') ? 'Acorns' : h.account_id) : '—'}
                  </span>
                </td>
                <td className="px-6 py-3.5 text-right text-sm font-medium text-slate-700 dark:text-slate-300">
                  ${h.price.toFixed(2)}
                </td>
                <td className="px-6 py-3.5 text-right text-sm text-slate-500">
                  {h.quantity}
                </td>
                <td className="px-6 py-3.5 text-right text-sm font-semibold text-slate-900 dark:text-white">
                  ${h.value.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </td>
                <td className="px-6 py-3.5 text-right">
                  <div className="flex items-center justify-end gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                    {h.weight.toFixed(1)}%
                    <div className="w-12 h-1 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
                      <div className="bg-slate-500 h-full rounded-full" style={{ width: `${h.weight}%` }}></div>
                    </div>
                  </div>
                </td>
              </tr>
              {isExpanded && (
                <tr className="bg-slate-50/50 dark:bg-slate-800/30">
                  <td colSpan={6} className="px-6 py-3">
                    <div className="ml-11 border-l-2 border-slate-200 dark:border-slate-700 pl-4">
                      <p className="text-label mb-2">Tax Lots</p>
                      <div className="space-y-1.5">
                        <div className="grid grid-cols-5 gap-4 text-xs text-slate-400 font-semibold">
                          <span>Date Acquired</span><span>Shares</span><span>Cost Basis</span><span>Current Value</span><span>Gain/Loss</span>
                        </div>
                        {/* Simulated tax lots based on holding data */}
                        {[...Array(Math.min(3, Math.max(1, Math.floor(h.quantity / 10) || 1)))].map((_, lotIdx) => {
                          const lotShares = lotIdx === 0 ? Math.ceil(h.quantity * 0.6) : Math.floor(h.quantity * (0.4 / Math.max(1, Math.floor(h.quantity / 10) - 1)));
                          const costBasis = h.price * (0.85 + lotIdx * 0.08);
                          const currentVal = lotShares * h.price;
                          const costTotal = lotShares * costBasis;
                          const gain = currentVal - costTotal;
                          const daysAgo = 365 * (2 - lotIdx) + Math.floor(Math.random() * 100);
                          const acqDate = new Date(Date.now() - daysAgo * 86400000).toISOString().split('T')[0];
                          return (
                            <div key={lotIdx} className="grid grid-cols-5 gap-4 text-xs py-1">
                              <span className="text-slate-500">{acqDate}</span>
                              <span className="text-slate-700 dark:text-slate-300">{lotShares}</span>
                              <span className="text-slate-500">${costBasis.toFixed(2)}</span>
                              <span className="text-slate-700 dark:text-slate-300">${currentVal.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
                               <span className={`text-numeric ${gain >= 0 ? 'text-gain' : 'text-loss'}`}>{gain >= 0 ? '+' : ''}${gain.toFixed(2)}</span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
              </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );

  const renderAllocationTab = () => {
    const sectorTotal = sectorData.reduce((s, sec) => s + sec.value, 0);
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Large Pie Chart */}
        <div className="card-l1 p-6 flex flex-col h-[360px]">
          <h3 className="font-bold text-xl mb-4">Sector Allocation</h3>
          <div className="flex-1 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '12px', color: '#fff', fontSize: '12px', boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.5)' }}
                  formatter={(value: any, name: any) => [`$${value.toLocaleString()} (${sectorTotal > 0 ? ((value / sectorTotal) * 100).toFixed(1) : 0}%)`, name]}
                />
                <Pie
                  data={sectorData}
                  cx="50%"
                  cy="50%"
                  innerRadius={70}
                  outerRadius={130}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                  label={(props: any) => `${props.name || ''} ${(((props.percent ?? 0)) * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {sectorData.map((_entry, index) => (
                    <Cell key={`cell-alloc-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Sector Breakdown List */}
        <div className="card-l1 p-6 flex flex-col h-[360px]">
          <h3 className="font-bold text-xl mb-4">Breakdown</h3>
          <div className="flex-1 space-y-3 overflow-y-auto custom-scrollbar">
            {sectorData.sort((a, b) => b.value - a.value).map((sector, idx) => {
              const pct = sectorTotal > 0 ? ((sector.value / sectorTotal) * 100) : 0;
              return (
                <div key={sector.name} className="flex items-center gap-4 p-3 rounded-lg hover:bg-slate-50 dark:hover:bg-primary/5 transition-colors">
                  <div className="size-10 rounded-lg flex items-center justify-center" style={{ backgroundColor: COLORS[idx % COLORS.length] + '20' }}>
                    <span className="material-symbols-outlined text-sm" style={{ color: COLORS[idx % COLORS.length] }}>
                      {idx === 0 ? 'account_balance' : idx === 1 ? 'computer' : idx === 2 ? 'public' : 'savings'}
                    </span>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold text-sm">{sector.name}</span>
                      <span className="font-bold text-sm">${sector.value.toLocaleString()}</span>
                    </div>
                    <div className="w-full bg-slate-100 dark:bg-primary/5 h-2 rounded-full overflow-hidden">
                      <div 
                        className="h-full rounded-full transition-all duration-500" 
                        style={{ width: `${pct}%`, backgroundColor: COLORS[idx % COLORS.length] }}
                      ></div>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">{pct.toFixed(1)}% of portfolio</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-background overflow-auto custom-scrollbar">
      
      {/* Top Navigation Tabs */}
      <div className="flex items-center gap-8 border-b border-slate-200 dark:border-slate-800 px-12 pt-6 bg-white/50 dark:bg-background/50 backdrop-blur-md sticky top-0 z-10">
        {["Investments", "Holdings", "Allocation"].map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-2 py-3 border-b-2 font-bold text-sm transition-all duration-300 ${
              activeTab === tab 
                ? "border-primary text-primary" 
                : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
            }`}
          >
            {tab}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-4 pb-2">
          <div className="bg-slate-100 dark:bg-primary/5 rounded-lg p-1 flex text-xs font-bold text-slate-500">
            {TIMEFRAMES.map((tf) => (
              <button 
                key={tf} 
                className={`px-3 py-1 rounded-md transition-colors ${
                  activeTimeframe === tf 
                    ? "bg-white dark:bg-primary/20 text-slate-900 dark:text-primary shadow-sm" 
                    : "hover:text-slate-900 dark:hover:text-slate-200"
                }`}
                onClick={() => setActiveTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>
          <select 
            className="bg-white dark:bg-background-dark border border-slate-200 dark:border-primary/20 rounded-lg px-3 py-1.5 text-xs font-bold outline-none cursor-pointer"
            value={accountFilter}
            onChange={(e) => setAccountFilter(e.target.value)}
          >
            <option value="all">All accounts</option>
            {accounts.map(acct => (
              <option key={acct.id} value={acct.id}>{acct.name}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="p-12 space-y-8 flex-1">
        {activeTab === "Investments" && renderInvestmentsTab()}
        {activeTab === "Holdings" && renderHoldingsTab()}
        {activeTab === "Allocation" && renderAllocationTab()}
      </div>

      {/* Add Holding Dialog */}
      {showAddHolding && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center" onClick={() => setShowAddHolding(false)}>
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-2xl w-[400px] p-6 animate-in fade-in zoom-in-95 duration-200" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-5">
              <h3 className="font-bold text-lg">Add Holding</h3>
              <button onClick={() => setShowAddHolding(false)} className="text-slate-400 hover:text-red-500 transition-colors">
                <span className="material-symbols-outlined text-sm">close</span>
              </button>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-label mb-1">Ticker</label>
                  <input value={newHolding.ticker} onChange={(e) => setNewHolding(p => ({...p, ticker: e.target.value.toUpperCase()}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" placeholder="AAPL" />
                </div>
                <div>
                  <label className="block text-label mb-1">Account</label>
                  <select value={newHolding.account_id} onChange={(e) => setNewHolding(p => ({...p, account_id: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none cursor-pointer">
                    {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-label mb-1">Shares</label>
                  <input type="number" step="0.01" value={newHolding.shares} onChange={(e) => setNewHolding(p => ({...p, shares: e.target.value}))} className="w-full px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" placeholder="10" />
                </div>
                <div>
                  <label className="block text-label mb-1">Price per Share</label>
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-slate-400">$</span>
                    <input type="number" step="0.01" value={newHolding.price} onChange={(e) => setNewHolding(p => ({...p, price: e.target.value}))} className="w-full pl-7 pr-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm outline-none focus:border-slate-500" placeholder="150.00" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex gap-3 mt-5">
              <button
                onClick={() => {
                  const shares = parseFloat(newHolding.shares);
                  const price = parseFloat(newHolding.price);
                  if (!newHolding.ticker || isNaN(shares) || isNaN(price)) return;
                  // Add to local holdings state (simulated write-back)
                  const newH = {
                    id: allHoldings.length + 1,
                    security: newHolding.ticker,
                    ticker: newHolding.ticker,
                    price: price,
                    quantity: shares,
                    value: shares * price,
                    weight: 0,
                    account_id: newHolding.account_id,
                    past3m: 0,
                  };
                  const updated = [...allHoldings, newH];
                  const totalVal = updated.reduce((s, h) => s + h.value, 0);
                  const reweighted = updated.map(h => ({ ...h, weight: totalVal > 0 ? (h.value / totalVal * 100) : 0 }));
                  setAllHoldings(reweighted);
                  setShowAddHolding(false);
                  setNewHolding({ ticker: '', shares: '', price: '', account_id: 'fidelity_inv_001' });
                }}
                className="flex-1 px-4 py-2.5 bg-[var(--color-gain)] text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity"
              >Add Holding</button>
              <button onClick={() => setShowAddHolding(false)} className="px-4 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm font-semibold hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
