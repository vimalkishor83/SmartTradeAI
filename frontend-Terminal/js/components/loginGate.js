import { login, register, ApiError } from "../api.js";
import { resolveRoute } from "../router.js";

export function loginGateHtml(initialTab = "signin") {
  const signinActive = initialTab === "signin";
  return `
    <div class="gate-wrap">
      <div class="card">
        <div class="gate-tabs" role="tablist">
          <div class="gate-tab ${signinActive ? "active" : ""}" data-tab="signin" role="tab">Sign in</div>
          <div class="gate-tab ${signinActive ? "" : "active"}" data-tab="register" role="tab">Create account</div>
        </div>

        <div id="gate-panel-signin" style="${signinActive ? "" : "display:none;"}">
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

        <div id="gate-panel-register" style="${signinActive ? "display:none;" : ""}">
          ${registerFormHtml()}
        </div>
      </div>
    </div>
  `;
}

function registerFormHtml() {
  return `
    <div id="register-form-wrap">
      <h2>\u{1F4DD} Create your account</h2>
      <p class="text-2" style="font-size:12px; margin-top:0;">New accounts are reviewed by the desk — approval typically takes 24–48 hours. You'll sign in with this email once approved.</p>
      <form id="register-form">
        <div class="field">
          <label for="reg-username">Username</label>
          <input class="input" type="text" id="reg-username" required autocomplete="username" />
        </div>
        <div class="field">
          <label for="reg-email">Email</label>
          <input class="input" type="email" id="reg-email" required autocomplete="email" />
        </div>
        <div class="gate-row-2">
          <div class="field">
            <label for="reg-first-name">First name</label>
            <input class="input" type="text" id="reg-first-name" autocomplete="given-name" />
          </div>
          <div class="field">
            <label for="reg-last-name">Last name</label>
            <input class="input" type="text" id="reg-last-name" autocomplete="family-name" />
          </div>
        </div>
        <div class="gate-row-2">
          <div class="field">
            <label for="reg-password">Password</label>
            <input class="input" type="password" id="reg-password" required autocomplete="new-password" minlength="8" />
          </div>
          <div class="field">
            <label for="reg-password-2">Confirm password</label>
            <input class="input" type="password" id="reg-password-2" required autocomplete="new-password" minlength="8" />
          </div>
        </div>
        <div class="gate-hint" style="margin-bottom:var(--space-3);">At least 8 characters.</div>
        <div class="gate-checkbox-row">
          <input type="checkbox" id="reg-terms" required />
          <label for="reg-terms">I accept the Terms of Service and Privacy Policy.</label>
        </div>
        <input class="gate-honeypot" type="text" id="reg-website" name="website" tabindex="-1" autocomplete="off" aria-hidden="true" />
        <button class="btn btn-primary" type="submit" style="width:100%;">Submit application</button>
        <div class="gate-error" id="register-error" style="display:none;"></div>
      </form>
    </div>
  `;
}

function registerSuccessHtml(email) {
  return `
    <div class="gate-success">
      <div class="gate-success-icon">\u{2705}</div>
      <h3>Application submitted</h3>
      <p>We've sent a confirmation to <strong>${email}</strong>. The desk reviews new accounts within 24–48 hours — sign in with this email once you're approved.</p>
      <button class="btn btn-primary" id="register-back-to-signin">Back to sign in</button>
    </div>
  `;
}

export function bindLoginForm(root) {
  const tabSignin = root.querySelector('[data-tab="signin"]');
  const tabRegister = root.querySelector('[data-tab="register"]');
  const panelSignin = root.querySelector("#gate-panel-signin");
  const panelRegister = root.querySelector("#gate-panel-register");

  function showTab(name) {
    const isSignin = name === "signin";
    tabSignin.classList.toggle("active", isSignin);
    tabRegister.classList.toggle("active", !isSignin);
    panelSignin.style.display = isSignin ? "" : "none";
    panelRegister.style.display = isSignin ? "none" : "";
  }

  tabSignin.addEventListener("click", () => showTab("signin"));
  tabRegister.addEventListener("click", () => showTab("register"));

  const loginForm = root.querySelector("#login-form");
  const loginError = root.querySelector("#login-error");
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    loginError.style.display = "none";
    const email = root.querySelector("#login-email").value.trim();
    const password = root.querySelector("#login-password").value;
    try {
      await login(email, password);
      resolveRoute();
    } catch (err) {
      loginError.textContent = err instanceof ApiError ? err.message : "Sign-in failed.";
      loginError.style.display = "block";
    }
  });

  bindRegisterForm(panelRegister, () => showTab("signin"));
}

function bindRegisterForm(panelRegister, backToSignin) {
  const form = panelRegister.querySelector("#register-form");
  const errorEl = panelRegister.querySelector("#register-error");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.style.display = "none";

    const username = panelRegister.querySelector("#reg-username").value.trim();
    const email = panelRegister.querySelector("#reg-email").value.trim();
    const firstName = panelRegister.querySelector("#reg-first-name").value.trim();
    const lastName = panelRegister.querySelector("#reg-last-name").value.trim();
    const password = panelRegister.querySelector("#reg-password").value;
    const password2 = panelRegister.querySelector("#reg-password-2").value;
    const acceptTerms = panelRegister.querySelector("#reg-terms").checked;
    const website = panelRegister.querySelector("#reg-website").value;

    if (password.length < 8) {
      errorEl.textContent = "Password must be at least 8 characters.";
      errorEl.style.display = "block";
      return;
    }
    if (password !== password2) {
      errorEl.textContent = "Passwords don't match.";
      errorEl.style.display = "block";
      return;
    }
    if (!acceptTerms) {
      errorEl.textContent = "You must accept the Terms of Service and Privacy Policy.";
      errorEl.style.display = "block";
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting…";

    try {
      await register({
        username,
        email,
        password,
        accept_terms: acceptTerms,
        first_name: firstName,
        last_name: lastName,
        website, // honeypot — always empty for real users
      });
      panelRegister.innerHTML = registerSuccessHtml(email);
      panelRegister.querySelector("#register-back-to-signin").addEventListener("click", backToSignin);
    } catch (err) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit application";
      errorEl.textContent = err instanceof ApiError ? err.message : "Registration failed.";
      errorEl.style.display = "block";
    }
  });
}
