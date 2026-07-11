# Tests

```
pytest                    # run everything
pytest tests/unit          # pure-function tests, no Flask app/DB, fast
pytest tests/integration   # real Flask app + in-memory SQLite + real JWT auth
```

`tests/conftest.py` provides `app`, `client`, and `app_context` fixtures
built on the app's existing `TestingConfig` (`sqlite:///:memory:`) — no
test ever touches the real dev/prod database.

## What's covered so far

- Delta Exchange HMAC request-signing (`services/trading/delta_trading.py`)
- Position sizing / risk-reward calculator (`services/risk/calculator.py`)
- Portfolio correlation/concentration (`services/risk/portfolio_risk.py`)
- Protective order (stop-loss/take-profit/trailing-stop) breach detection
  (`tasks/protective_order_tasks.py`)
- FY-wise tax report classification (`services/tax/report.py`)
- Risk API routes, end-to-end through a real Flask test client

This is a foundational suite, not full coverage — it prioritizes the
places a regression has direct financial consequence (order signing,
position sizing, stop-loss/take-profit logic) over broad breadth. Add
tests alongside new features going forward rather than backfilling
everything at once.
