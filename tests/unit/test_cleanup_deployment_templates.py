from pathlib import Path


ROOT = Path(__file__).parents[2]
DEPLOY = ROOT / "deploy" / "development"


def test_cleanup_timer_is_daily_and_service_explicitly_applies_allowlisted_policy():
    timer = (DEPLOY / "smarttrade-safe-cleanup.timer").read_text(encoding="utf-8")
    service = (DEPLOY / "smarttrade-safe-cleanup.service").read_text(encoding="utf-8")
    script = (DEPLOY / "smarttrade-safe-cleanup").read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 03:30:00 UTC" in timer
    assert "RandomizedDelaySec=15m" in timer
    assert "ExecStart=/usr/local/sbin/smarttrade-safe-cleanup --apply" in service
    assert "readonly MAX_BYTES=$((512 * 1024 * 1024))" in script
    assert "/tmp:14" in script
    assert "/var/tmp:30" in script
    assert "readonly STATUS_FILE=/var/lib/smarttrade-safe-cleanup/status.json" in script
    assert "*.key" in script
    assert "local completed_json=null" in script
