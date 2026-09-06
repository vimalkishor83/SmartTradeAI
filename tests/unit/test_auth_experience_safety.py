"""Contract checks for the UI-5 authentication and onboarding experience."""

from pathlib import Path


ROOT = Path(__file__).parents[2]
AUTH = ROOT / "frontend" / "templates" / "auth"
BASE = ROOT / "frontend" / "templates" / "partials" / "base.html"
SHARED = ROOT / "frontend" / "static" / "js" / "auth_public.js"


def test_auth_pages_use_explicit_form_labels_and_feedback_regions():
    login = (AUTH / "login.html").read_text(encoding="utf-8")
    register = (AUTH / "register.html").read_text(encoding="utf-8")
    forgot = (AUTH / "forgot_password.html").read_text(encoding="utf-8")
    reset = (AUTH / "reset_password.html").read_text(encoding="utf-8")
    verify = (AUTH / "verify_email.html").read_text(encoding="utf-8")

    for source in (login, register, forgot):
        assert 'class="auth-side" aria-labelledby="authValueTitle"' in source
        assert 'class="auth-form-panel" aria-labelledby="authFormTitle"' in source
        assert 'role="alert" aria-live="assertive"' in source

    assert 'for="loginEmail"' in login
    assert 'for="loginPassword"' in login
    assert 'for="totpCode"' in login
    assert 'id="totpStep" aria-hidden="true"' in login
    assert 'id="authTicker" role="status" aria-live="polite"' in login
    assert 'for="brokerSelect"' in register
    assert 'for="brokerAccountId"' in register
    assert 'for="referralCode"' in register
    assert 'id="authTicker" role="status" aria-live="polite"' in register
    assert 'role="status" aria-live="polite"' in register
    assert 'for="fpEmail"' in forgot
    assert 'id="authTicker" role="status" aria-live="polite"' in forgot
    assert 'id="fpSuccessView" class="text-center" aria-hidden="true"' in forgot
    assert 'for="newPassword"' in reset
    assert 'for="confirmPassword"' in reset
    assert 'id="toggleNewPassword"' in reset
    assert 'id="toggleConfirmPassword"' in reset
    assert 'class="auth-card auth-simple-card"' in reset
    assert 'class="auth-card auth-simple-card text-center"' in verify
    assert 'aria-busy="true"' in verify
    assert 'id="veMessage" role="status" aria-live="polite"' in verify


def test_auth_public_context_is_shared_and_dom_safe():
    base = BASE.read_text(encoding="utf-8")
    shared = SHARED.read_text(encoding="utf-8")

    assert "auth_public.js?v={{ asset_version('js/auth_public.js') }}" in base
    assert "replaceChildren" in shared
    assert "textContent = item.symbol" in shared
    assert "textContent = formatPrice(item.price)" in shared
    assert ".slice(0, 3)" in shared
    assert "clearTimeout(timeout)" in shared

    for filename in ("login.html", "register.html", "forgot_password.html"):
        source = (AUTH / filename).read_text(encoding="utf-8")
        assert "/api/v1/signals/public-ticker" not in source
        assert "/api/v1/signals/public-stats" not in source


def test_auth_submit_and_state_transitions_recover_cleanly():
    login = (AUTH / "login.html").read_text(encoding="utf-8")
    register = (AUTH / "register.html").read_text(encoding="utf-8")
    forgot = (AUTH / "forgot_password.html").read_text(encoding="utf-8")
    reset = (AUTH / "reset_password.html").read_text(encoding="utf-8")

    assert "setAttribute('aria-hidden', 'false')" in login
    assert "try {\n        localStorage.setItem('access_token'" in login
    assert "const data = await res.json().catch(() => ({}));" in register
    assert "finally {\n    btn.disabled = false;" in register
    assert "try { token = localStorage.getItem('access_token'); } catch (_) {}" in register
    assert "setAttribute('aria-hidden', 'false')" in forgot
    assert "setAttribute('aria-hidden', 'true')" in forgot
    assert "clearTimeout(timeout);" in forgot
    assert "data.message || 'Password updated successfully.'" in reset
    assert "wirePasswordToggle('newPassword', 'toggleNewPassword')" in reset
