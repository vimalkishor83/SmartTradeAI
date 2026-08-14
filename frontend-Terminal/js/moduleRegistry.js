// Central registry of every terminal module: nav grouping, icon, and
// whether it's wired to a real SmartTradeAI endpoint or a "coming soon" stub.
export const MODULE_GROUPS = [
  {
    label: "Trading",
    items: [
      { id: "terminal", icon: "⚡", label: "Signal Terminal", real: true, desc: "Live strategy signals, entries, stops, targets, confidence, and one-click paper trades." },
      { id: "trading-logs", icon: "\u{1F4D2}", label: "Trading Logs", real: true, desc: "Your journalled paper trades — wins, losses, notes, CSV export." },
      { id: "backtest", icon: "\u{1F9EA}", label: "Backtest Lab", real: true, desc: "Run and review strategy backtests and walk-forward validation." },
      { id: "nifty-scalper", icon: "\u{1F3AF}", label: "Index Scalper", real: false, desc: "Fast intraday index scalping module with simulated replay engine." },
      { id: "trading-course", icon: "\u{1F393}", label: "Trading Course", real: false, desc: "Structured lessons on macro-driven trading." },
    ],
  },
  {
    label: "Core",
    items: [
      { id: "macro-dashboard", icon: "▦", label: "Macro Dashboard", real: false, desc: "Cross-asset macro bias and regime overview." },
      { id: "confluence-engine", icon: "◈", label: "Confluence Engine", real: false, desc: "Multi-factor macro confluence scoring per asset." },
      { id: "scanner", icon: "⇄", label: "Bull/Bear Scanner", real: true, desc: "Filter-driven scanner across the tracked asset universe." },
      { id: "regime-matrix", icon: "▩", label: "Market-Regime Matrix", real: false, desc: "Growth × inflation quadrant regime map." },
      { id: "portfolio", icon: "\u{1F4BC}", label: "Portfolio", real: true, desc: "Your holdings, allocation, and CSV export." },
      { id: "watchlist", icon: "☆", label: "Watchlist", real: true, desc: "Assets and context you're tracking." },
    ],
  },
  {
    label: "Economy",
    items: [
      { id: "us-economic-data", icon: "≣", label: "US Economic Data", real: false, desc: "Key US indicators — actual vs forecast vs previous." },
      { id: "gdp-growth", icon: "↗", label: "GDP & Growth", real: false, desc: "GDP tracking and growth-scenario probabilities." },
      { id: "inflation", icon: "\u{1F525}", label: "Inflation Dashboard", real: false, desc: "CPI, core CPI, PCE, PPI trend and verdict." },
      { id: "labour-market", icon: "\u{1F477}", label: "Labour Market", real: false, desc: "Payrolls, claims, wages, and labour-market verdict." },
      { id: "economic-calendar", icon: "\u{1F5D3}", label: "Economic Calendar", real: true, desc: "Upcoming and released macro events." },
    ],
  },
  {
    label: "Policy & Money",
    items: [
      { id: "federal-reserve", icon: "\u{1F3DB}", label: "Federal Reserve", real: false, desc: "Rate path, meeting odds, and Fed communication tracker." },
      { id: "banking-liquidity", icon: "\u{1F3E6}", label: "Banking & Liquidity", real: false, desc: "Banking-system stress and net-liquidity tracker." },
      { id: "yield-curve", icon: "\u{1F4C9}", label: "Yield Curve & Bonds", real: false, desc: "Curve shape, auctions, and inversion history." },
      { id: "global-central-banks", icon: "\u{1F310}", label: "Global Central Banks", real: false, desc: "Rate and stance tracker across major central banks." },
    ],
  },
  {
    label: "World",
    items: [
      { id: "forex-dashboard", icon: "\u{1F4B1}", label: "Forex Dashboard", real: false, desc: "Currency strength matrix and pair observations." },
      { id: "geopolitical-risk", icon: "⚔", label: "Geopolitical Risk", real: false, desc: "Risk score and cross-asset impact map." },
      { id: "socioeconomic", icon: "\u{1F465}", label: "Socioeconomic Data", real: false, desc: "Household-stress and search-trend indicators." },
      { id: "news", icon: "\u{1F4F0}", label: "Financial News", real: true, desc: "Latest market and macro news." },
      { id: "sentiment", icon: "\u{1F9ED}", label: "Market Sentiment", real: false, desc: "Fear & greed, positioning, and survey data." },
      { id: "put-call-ratio", icon: "☯", label: "Put/Call Ratio", real: false, desc: "Options positioning across tracked instruments." },
    ],
  },
  {
    label: "Tools",
    items: [
      { id: "charts", icon: "\u{1F4CA}", label: "Charts & Correlations", real: true, desc: "Price charts, indicators, and rolling correlations." },
      { id: "asset-pages", icon: "◎", label: "Asset Pages", real: false, desc: "Deep-dive page per tracked asset." },
      { id: "predictions", icon: "\u{1F52E}", label: "Predictions", real: true, desc: "Model-generated price predictions and performance." },
      { id: "risk", icon: "\u{1F6E1}", label: "Risk Console", real: true, desc: "Position sizing, risk/reward, and portfolio risk." },
      { id: "educational-insights", icon: "\u{1F393}", label: "Educational Insights", real: false, desc: "Concept explainers for macro and technical terms." },
      { id: "reports", icon: "\u{1F4C4}", label: "Reports", real: false, desc: "Generated daily/weekly macro and performance reports." },
      { id: "alerts", icon: "\u{1F514}", label: "Alerts", real: true, desc: "Your notifications and alert history." },
      { id: "admin", icon: "⚙", label: "Admin Panel", real: true, admin: true, desc: "User approval, API config, logs, and backups." },
    ],
  },
];

export const ALL_MODULES = MODULE_GROUPS.flatMap((g) => g.items);

export function getModule(id) {
  return ALL_MODULES.find((m) => m.id === id);
}
