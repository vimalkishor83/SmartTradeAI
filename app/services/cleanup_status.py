"""Read-only status for the development host cleanup policy.

The web application never executes cleanup commands and never accepts a path
from a browser.  The host timer writes a small, sanitized JSON snapshot that
is mounted into the development container read-only.
"""

import json
import os
from pathlib import Path

from flask import current_app


STATUS_FILE = Path("/app/cleanup/status.json")
MAX_BYTES = 512 * 1024 * 1024

POLICY = {
    "frequency": "daily",
    "time_utc": "03:30",
    "randomized_delay": "up to 15 minutes",
    "allowed_roots": [
        {"path": "/tmp", "max_age_days": 14},
        {"path": "/var/tmp", "max_age_days": 30},
    ],
    "max_bytes": MAX_BYTES,
    "max_bytes_label": "512 MB",
    "mode": "apply (scheduled service); dry-run by default when run manually",
    "open_files_skipped": True,
    "lock_enabled": True,
    "arbitrary_paths_allowed": False,
}

_SNAPSHOT_KEYS = {
    "state",
    "mode",
    "completed_at",
    "candidate_count",
    "skipped_count",
    "bytes_processed",
}


def _empty_snapshot():
    return {
        "state": "not_run",
        "mode": "dry-run",
        "completed_at": None,
        "candidate_count": 0,
        "skipped_count": 0,
        "bytes_processed": 0,
    }


def _read_snapshot():
    """Return only known, non-sensitive values from the host snapshot."""
    try:
        raw = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_snapshot(), False

    if not isinstance(raw, dict):
        return _empty_snapshot(), False

    snapshot = _empty_snapshot()
    for key in _SNAPSHOT_KEYS:
        value = raw.get(key)
        if key in {"candidate_count", "skipped_count", "bytes_processed"}:
            if isinstance(value, int) and value >= 0:
                snapshot[key] = value
        elif key in {"state", "mode", "completed_at"}:
            if value is None or isinstance(value, str):
                snapshot[key] = value
    return snapshot, True


def get_cleanup_status():
    """Build the safe dashboard payload without invoking host commands."""
    # Do not expose host cleanup metadata if this code is ever promoted into
    # the production profile accidentally.
    environment = current_app.config.get("ENVIRONMENT") or os.environ.get("FLASK_ENV", "development")
    if environment == "production":
        return {"available": False, "reason": "development-only"}

    snapshot, available = _read_snapshot()
    return {
        "available": True,
        "environment": "development",
        "policy": POLICY,
        "snapshot": snapshot,
        "snapshot_available": available,
    }
