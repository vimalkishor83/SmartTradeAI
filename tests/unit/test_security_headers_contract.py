from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_csp_report_only_does_not_allow_dynamic_eval():
    source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    assert "Content-Security-Policy-Report-Only" in source
    assert "script-src 'self' 'unsafe-inline' https:;" in source
    assert "'unsafe-eval'" not in source


def test_security_headers_remain_enforced_alongside_csp_rollout():
    source = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
    for header in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "Strict-Transport-Security"):
        assert header in source
