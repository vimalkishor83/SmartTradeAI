"""Regression coverage for the Delta stream connection-status contract.

DeltaStreamManager never actually set a `running`/`_running` attribute, so
the /system/ready market_stream check (which read exactly those via
getattr with a None/False default) always reported "idle (polling
fallback)" regardless of whether the WebSocket was genuinely connected.
"""

from app.services.data.delta_stream import DeltaStreamManager
import pytest


def test_status_defaults_to_disconnected_before_any_connection_attempt():
    manager = DeltaStreamManager()
    status = manager.status()

    assert status["connected"] is False
    assert status["last_message_ts"] is None
    assert status["thread_alive"] is False


@pytest.mark.slow
def test_connect_wires_on_open_to_mark_connected(monkeypatch):
    """Exercises the real on_open closure built inside _connect(), rather
    than asserting against manually-set state -- catches a future refactor
    that stops wiring the callback correctly."""
    import types
    from app.services.data import delta_stream as delta_stream_module

    manager = DeltaStreamManager()
    manager._last_close_reason = "closed (code=1006)"
    captured = {}

    class FakeWSApp:
        def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
            captured["on_open"] = on_open
            captured["on_close"] = on_close
            captured["on_error"] = on_error

        def run_forever(self, **kwargs):
            pass

    fake_websocket_module = types.SimpleNamespace(WebSocketApp=FakeWSApp)
    monkeypatch.setitem(__import__("sys").modules, "websocket", fake_websocket_module)

    manager._connect(["BTCUSDT"])

    class FakeWS:
        def send(self, payload):
            pass

    captured["on_open"](FakeWS())
    assert manager.status()["connected"] is True
    assert manager.status()["last_close_reason"] is None

    captured["on_close"](FakeWS(), 1006, "abnormal closure")
    status = manager.status()
    assert status["connected"] is False
    assert "1006" in status["last_close_reason"]


def test_on_message_records_last_message_timestamp(monkeypatch):
    import time as time_module
    from app.services.data import delta_stream as delta_stream_module

    manager = DeltaStreamManager()
    monkeypatch.setattr(delta_stream_module.time, "time", lambda: 1000.0)
    monkeypatch.setattr(manager, "_broadcast", lambda *a, **k: None)

    manager._on_message(ws=None, raw='{"type":"v2/ticker","symbol":"BTCUSDT","close":100,"open":99}')

    assert manager.status()["last_message_ts"] == 1000.0


def test_market_stream_health_reflects_a_genuinely_connected_stream(app, monkeypatch):
    from app.services.data.delta_stream import delta_stream
    from app.api.v1.system import _check_market_stream

    monkeypatch.setattr(delta_stream, "_connected", True)
    monkeypatch.setattr(delta_stream, "_last_message_ts", None)
    monkeypatch.setattr(delta_stream, "_thread", None)

    with app.app_context():
        result = _check_market_stream()

    assert result["healthy"] is True
    assert result["connected"] is True
    assert result["detail"] == "connected"


def test_market_stream_health_reports_reconnecting_when_thread_alive_but_disconnected(app, monkeypatch):
    from app.services.data.delta_stream import delta_stream
    from app.api.v1.system import _check_market_stream

    class FakeThread:
        def is_alive(self):
            return True

    monkeypatch.setattr(delta_stream, "_connected", False)
    monkeypatch.setattr(delta_stream, "_last_close_reason", "closed (code=1006)")
    monkeypatch.setattr(delta_stream, "_thread", FakeThread())

    with app.app_context():
        result = _check_market_stream()

    assert result["connected"] is False
    assert "reconnecting" in result["detail"]
    assert "1006" in result["detail"]


def test_market_stream_health_reports_stopped_when_no_thread_at_all(app, monkeypatch):
    from app.services.data.delta_stream import delta_stream
    from app.api.v1.system import _check_market_stream

    monkeypatch.setattr(delta_stream, "_connected", False)
    monkeypatch.setattr(delta_stream, "_thread", None)

    with app.app_context():
        result = _check_market_stream()

    assert result["connected"] is False
    assert "stopped" in result["detail"]
