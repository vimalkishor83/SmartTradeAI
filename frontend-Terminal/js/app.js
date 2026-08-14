import { getState, subscribe, gateIntent } from "./state.js";
import { fetchMe } from "./api.js";
import { registerRoute, setNotFound, startRouter } from "./router.js";
import { getModule, ALL_MODULES } from "./moduleRegistry.js";
import { mountHeader } from "./components/header.js";
import { mountNav } from "./components/nav.js";
import { loginGateHtml, bindLoginForm } from "./components/loginGate.js";
import { renderHome } from "./modules/home.js";
import { renderStub } from "./modules/stub.js";
import { renderTerminal } from "./modules/terminal.js";
import { renderTradingLogs } from "./modules/tradingLogs.js";
import { renderBacktest } from "./modules/backtest.js";
import { renderPortfolio } from "./modules/portfolio.js";
import { renderWatchlist } from "./modules/watchlist.js";
import { renderScanner } from "./modules/scanner.js";
import { renderNews } from "./modules/news.js";
import { renderCharts } from "./modules/charts.js";
import { renderPredictions } from "./modules/predictions.js";
import { renderRisk } from "./modules/risk.js";
import { renderAlerts } from "./modules/alerts.js";
import { renderEconomicCalendar } from "./modules/economicCalendar.js";
import { renderAdmin } from "./modules/admin.js";

const REAL_RENDERERS = {
  terminal: renderTerminal,
  "trading-logs": renderTradingLogs,
  backtest: renderBacktest,
  portfolio: renderPortfolio,
  watchlist: renderWatchlist,
  scanner: renderScanner,
  news: renderNews,
  charts: renderCharts,
  predictions: renderPredictions,
  risk: renderRisk,
  alerts: renderAlerts,
  "economic-calendar": renderEconomicCalendar,
  admin: renderAdmin,
};

const main = document.querySelector("#main-content");
const bodyShell = document.querySelector("#body-shell");
const navRoot = document.querySelector("#nav-root");

function renderHomeRoute() {
  bodyShell.classList.add("no-nav");
  navRoot.style.display = "none";
  renderHome(main);
}

function renderModule(id) {
  bodyShell.classList.remove("no-nav");
  navRoot.style.display = "";

  const mod = getModule(id) || ALL_MODULES[0];
  const { user } = getState();

  if (mod.premium && !user) {
    main.innerHTML = loginGateHtml(gateIntent.tab);
    bindLoginForm(main);
    gateIntent.tab = "signin"; // reset so a later plain nav click defaults back to sign-in
    return;
  }

  const renderer = REAL_RENDERERS[mod.id];
  if (mod.real && renderer) {
    renderer(main, mod);
  } else {
    renderStub(main, mod);
  }
}

registerRoute("home", renderHomeRoute);
ALL_MODULES.forEach((mod) => registerRoute(mod.id, () => renderModule(mod.id)));
setNotFound(renderHomeRoute);

mountHeader(document.querySelector("#header-root"));
mountNav(navRoot);

function renderCurrentRoute() {
  const id = location.hash.replace(/^#\/?/, "") || "home";
  if (id === "home") renderHomeRoute();
  else renderModule(id);
}

subscribe(renderCurrentRoute);

async function bootstrap() {
  const { token } = getState();
  if (token) {
    try {
      await fetchMe();
    } catch {
      /* token invalid/expired — user stays signed out */
    }
  }
  startRouter();
}

bootstrap();
