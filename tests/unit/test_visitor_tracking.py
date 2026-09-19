"""Coverage for the new-IP / new-device homepage visitor alert feature:
- a repeat visit from an already-known (ip, user_agent) pair must not
  re-alert, only update last_seen_at/visit_count.
- a brand new IP must be logged and alerted as "new visitor IP".
- a known IP with a new user_agent must be logged and alerted as "new
  device on known ip", distinct from a brand new IP.
See app/services/visitor_tracking.py and app/models/visitor_log.py.
"""
from unittest.mock import patch
import pytest

from app.models.visitor_log import VisitorLog


def test_brand_new_ip_is_logged_and_alerted(app):
    with app.app_context():
        from app.services.visitor_tracking import record_visitor_and_alert_if_new

        with patch("app.services.ip_geolocation.lookup_location", return_value=""), \
             patch("app.tasks.notification_tasks.send_security_alert") as mock_alert:
            record_visitor_and_alert_if_new("203.0.113.10", "Mozilla/5.0 Chrome Windows")

        row = VisitorLog.query.filter_by(ip_address="203.0.113.10").first()
        assert row is not None
        assert row.visit_count == 1
        mock_alert.assert_called_once()
        assert "NEW VISITOR IP" in mock_alert.call_args[0][0]


@pytest.mark.slow
def test_repeat_visit_from_known_ip_and_device_does_not_alert(app):
    with app.app_context():
        from app.services.visitor_tracking import record_visitor_and_alert_if_new

        with patch("app.services.ip_geolocation.lookup_location", return_value=""), \
             patch("app.tasks.notification_tasks.send_security_alert") as mock_alert:
            record_visitor_and_alert_if_new("203.0.113.20", "Mozilla/5.0 Chrome Windows")
            mock_alert.reset_mock()
            record_visitor_and_alert_if_new("203.0.113.20", "Mozilla/5.0 Chrome Windows")

        mock_alert.assert_not_called()
        row = VisitorLog.query.filter_by(ip_address="203.0.113.20").first()
        assert row.visit_count == 2


def test_new_device_on_known_ip_alerts_distinctly(app):
    with app.app_context():
        from app.services.visitor_tracking import record_visitor_and_alert_if_new

        with patch("app.services.ip_geolocation.lookup_location", return_value=""), \
             patch("app.tasks.notification_tasks.send_security_alert") as mock_alert:
            record_visitor_and_alert_if_new("203.0.113.30", "Mozilla/5.0 Chrome Windows")
            mock_alert.reset_mock()
            record_visitor_and_alert_if_new("203.0.113.30", "Mozilla/5.0 Safari iPhone")

        mock_alert.assert_called_once()
        assert "NEW DEVICE ON KNOWN IP" in mock_alert.call_args[0][0]
        assert VisitorLog.query.filter_by(ip_address="203.0.113.30").count() == 2
