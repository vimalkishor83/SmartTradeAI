import { login, ApiError } from "../api.js";
import { resolveRoute } from "../router.js";

export function loginGateHtml() {
  return `
    <div class="gate-wrap">
      <div class="card">
        <h2>\u{1F511} Member sign-in</h2>
        <p class="text-2" style="font-size:12px; margin-top:0;">Sign in with your SmartTrade Terminal account to unlock the desk.</p>
        <form id="login-form">
          <div class="field">
            <label for="login-email">Email</label>
            <input class="input" type="email" id="login-email" required autocomplete="username" />
          </div>
          <div class="field">
            <label for="login-password">Password</label>
            <input class="input" type="password" id="login-password" required autocomplete="current-password" />
          </div>
          <button class="btn btn-primary" type="submit" style="width:100%;">Sign in</button>
          <div class="gate-error" id="login-error" style="display:none;"></div>
        </form>
      </div>
    </div>
  `;
}

export function bindLoginForm(root) {
  const form = root.querySelector("#login-form");
  const errorEl = root.querySelector("#login-error");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";
    const email = root.querySelector("#login-email").value.trim();
    const password = root.querySelector("#login-password").value;
    try {
      await login(email, password);
      resolveRoute();
    } catch (err) {
      errorEl.textContent = err instanceof ApiError ? err.message : "Sign-in failed.";
      errorEl.style.display = "block";
    }
  });
}
