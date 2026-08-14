import { api } from "../api.js";
import { getState } from "../state.js";
import { navigate } from "../router.js";
import { signalCardHtml } from "../components/signalCard.js";

const FEATURES = [
  { icon: "⚡", title: "Daily signal board", desc: "Direction, entry zone, stop, targets, and confidence for every tracked instrument." },
  { icon: "\u{1F9E0}", title: "Engine rationale", desc: "Every signal explains the factors and technicals behind it — no black box." },
  { icon: "\u{1F4D2}", title: "Paper trading", desc: "Practice account with real-time P&L and a full trade journal." },
  { icon: "\u{1F4C8}", title: "Live charts", desc: "Real-data price charts and indicators docked in the terminal." },
  { icon: "\u{1F6E1}", title: "Risk console", desc: "Position sizing, risk/reward, and portfolio-level risk in one place." },
  { icon: "\u{1F4DC}", title: "Your track record", desc: "Every trade you take is journalled — wins and losses, exportable." },
];

async function loadSamplePreview() {
  if (!getState().token) return null; // signals endpoint requires auth — skip the guaranteed-401 call
  try {
    const data = await api.get("/signals?limit=1");
    const signals = data.signals || data.items || data || [];
    return signals[0] || null;
  } catch {
    return null;
  }
}

export function renderHome(root) {
  root.innerHTML = `
    <div class="home-page">
      <section class="home-hero">
        <div class="home-hero-inner">
          <span class="badge badge-neutral" style="margin-bottom:14px;">SIGNAL-DRIVEN TRADING DESK</span>
          <h1>Trade with a system, not a hunch.</h1>
          <p class="home-hero-sub">
            SmartTrade Terminal turns your strategy engine into a full trading desk —
            signals, sizing, paper trading, and a journal that keeps you honest.
          </p>
          <div class="home-hero-cta">
            <button class="btn btn-primary" id="home-cta-signin">Sign in to the desk</button>
            <button class="btn" id="home-cta-explore">See what's inside</button>
          </div>
        </div>
      </section>

      <section class="home-section">
        <h2>What you get</h2>
        <div class="grid grid-cards">
          ${FEATURES.map((f) => `
            <div class="card">
              <div style="font-size:22px; margin-bottom:8px;">${f.icon}</div>
              <div style="font-weight:700; margin-bottom:4px;">${f.title}</div>
              <div class="text-2" style="font-size:13px;">${f.desc}</div>
            </div>
          `).join("")}
        </div>
      </section>

      <section class="home-section" id="home-preview-section">
        <h2>Terminal preview — sample signal</h2>
        <div id="home-preview-card" style="max-width:320px;">
          <div class="card text-3">Loading preview…</div>
        </div>
      </section>

      <section class="home-section home-final-cta">
        <div class="card" style="text-align:center; padding:40px;">
          <h2 style="margin-top:0;">Ready to trade with a system?</h2>
          <p class="text-2">Sign in with your account to unlock the full terminal — 13 live modules and counting.</p>
          <button class="btn btn-primary" id="home-cta-signin-2">Sign in</button>
        </div>
      </section>

      <footer class="home-footer">
        <p>Educational strategy engine. Signals combine live market data with technical and strategy logic — for learning and paper trading only. Not investment advice. No guaranteed returns. Markets involve substantial risk.</p>
      </footer>
    </div>
  `;

  root.querySelector("#home-cta-signin").addEventListener("click", () => navigate("terminal"));
  root.querySelector("#home-cta-signin-2").addEventListener("click", () => navigate("terminal"));
  root.querySelector("#home-cta-explore").addEventListener("click", () => {
    root.querySelector("#home-preview-section").scrollIntoView({ behavior: "smooth" });
  });

  loadSamplePreview().then((signal) => {
    const el = root.querySelector("#home-preview-card");
    if (!el) return; // user navigated away before this resolved
    el.innerHTML = signal
      ? signalCardHtml(signal)
      : `<div class="card text-3">Preview unavailable right now — sign in to see live signals.</div>`;
  });
}
