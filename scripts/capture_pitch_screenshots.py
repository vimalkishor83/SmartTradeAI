"""One-off script: log in and screenshot every major page for the pitch deck.
Not part of the running app — run manually with the server already up."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "pitch_screenshots"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("dashboard", "/dashboard"),
    ("morning_briefing", "/briefing"),
    ("markets_overview", "/markets/crypto"),
    ("markets_forex", "/markets/forex"),
    ("markets_commodities", "/markets/commodities"),
    ("markets_indian_stocks", "/markets/indian_stock"),
    ("markets_indices", "/markets/index"),
    ("all_signals", "/signals"),
    ("signal_history", "/signals?tab=history"),
    ("auto_generate", "/auto-generate"),
    ("scanner", "/scanner"),
    ("market_heatmap", "/heatmap"),
    ("backtesting", "/backtesting"),
    ("ai_insights", "/ai-insights"),
    ("ta_summary", "/ta-summary"),
    ("mtf_analysis", "/mtf-analysis"),
    ("model_performance", "/model-performance"),
    ("advanced_analysis", "/advanced-analysis"),
    ("analytics", "/analytics"),
    ("news", "/news"),
    ("economic_calendar", "/economic-calendar"),
    ("portfolio", "/portfolio"),
    ("watchlist", "/watchlist"),
    ("trading", "/trading"),
    ("risk_manager", "/risk"),
    ("my_performance", "/performance"),
    ("trade_journal", "/journal"),
    ("settings", "/settings"),
    ("help_faq", "/help"),
    ("asset_detail", "/asset/1"),
    ("admin_dashboard", "/admin"),
    ("admin_users", "/admin/users"),
    ("admin_api_configs", "/admin/api-configs"),
    ("admin_assets", "/admin/assets"),
    ("admin_logs", "/admin/logs"),
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5)
    page = ctx.new_page()

    login = ctx.request.post(
        f"{BASE}/api/v1/auth/login",
        data=json.dumps({"email": "admin@smarttradeai.com", "password": "Admin@123"}),
        headers={"Content-Type": "application/json"},
    ).json()
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.evaluate(
        "([t,r]) => { localStorage.setItem('access_token', t); localStorage.setItem('refresh_token', r); }",
        [login.get("access_token", ""), login.get("refresh_token", "")],
    )

    for name, route in PAGES:
        try:
            page.goto(f"{BASE}{route}", wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"NAV FAIL {route}: {e}")
            continue
        page.wait_for_timeout(3500)
        out_path = OUT / f"{name}.png"
        try:
            page.screenshot(path=str(out_path), full_page=True, timeout=15000)
            print(f"OK  {name:24} <- {route}")
        except Exception as e:
            print(f"SHOT FAIL {name}: {e}")

    browser.close()

print("\nDone. Screenshots in:", OUT)
