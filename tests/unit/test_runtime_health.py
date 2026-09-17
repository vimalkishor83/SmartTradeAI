from app.services.data import runtime_health


def test_runtime_health_records_success_without_response_data(monkeypatch):
    runtime_health.reset()
    monkeypatch.setattr(runtime_health.time, "time", lambda: 1000.0)

    runtime_health.record_success("yahoo", latency_ms=12.34)
    rows = runtime_health.snapshot(now=1005.0)

    assert rows == [{
        "provider": "yahoo",
        "state": "HEALTHY",
        "last_success_at": "1970-01-01T00:16:40+00:00",
        "last_failure_at": None,
        "age_seconds": 5.0,
        "stale_after_seconds": 180,
        "last_latency_ms": 12.3,
        "consecutive_failures": 0,
        "last_error": None,
    }]


def test_runtime_health_marks_repeated_failure_and_never_exposes_exception_text(monkeypatch):
    runtime_health.reset()
    monkeypatch.setattr(runtime_health.time, "time", lambda: 2000.0)

    for _ in range(3):
        runtime_health.record_failure("delta_exchange", reason="provider request failed")
    rows = runtime_health.snapshot(now=2001.0)

    assert rows[0]["state"] == "ERROR"
    assert rows[0]["consecutive_failures"] == 3
    assert rows[0]["last_error"] == "provider request failed"
    assert "password" not in str(rows[0]).lower()


def test_runtime_health_marks_old_success_stale(monkeypatch):
    runtime_health.reset()
    monkeypatch.setattr(runtime_health.time, "time", lambda: 3000.0)

    runtime_health.record_success("binance")
    assert runtime_health.snapshot(now=3181.0)[0]["state"] == "STALE"
    runtime_health.reset()
