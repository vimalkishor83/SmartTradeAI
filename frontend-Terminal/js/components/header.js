import { getState, subscribe } from "../state.js";
import { logout } from "../api.js";
import { navigate } from "../router.js";

function fmtClock() {
  const now = new Date();
  return now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) +
    " · " + now.toLocaleDateString("en-IN", { month: "short", day: "numeric" });
}

export function mountHeader(root) {
  root.innerHTML = `
    <header class="header">
      <div class="header-brand" id="brand-home">
        <div class="logo-mark">ST</div>
        <div class="brand-text">
          <div class="brand-name">SmartTrade Terminal</div>
          <div class="brand-sub">Signal-driven trading desk</div>
        </div>
      </div>
      <div class="header-search">
        <input class="input" type="text" placeholder="Search modules, assets…" id="global-search" />
      </div>
      <div class="header-actions">
        <span class="header-clock" id="header-clock"></span>
        <div id="header-user"></div>
      </div>
    </header>
  `;

  root.querySelector("#brand-home").addEventListener("click", () => navigate("home"));

  const clockEl = root.querySelector("#header-clock");
  clockEl.textContent = fmtClock();
  setInterval(() => { clockEl.textContent = fmtClock(); }, 1000);

  function renderUser() {
    const { user } = getState();
    const userEl = root.querySelector("#header-user");
    if (user) {
      userEl.innerHTML = `<button class="icon-btn" id="signout-btn">\u{1F464} ${user.name || user.email} · Sign out</button>`;
      userEl.querySelector("#signout-btn").addEventListener("click", () => {
        logout();
        navigate("terminal");
      });
    } else {
      userEl.innerHTML = `<span class="text-3" style="font-size:12px;">Not signed in</span>`;
    }
  }

  renderUser();
  subscribe(renderUser);
}
