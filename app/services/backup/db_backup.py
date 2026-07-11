"""
SQLite backup/disaster-recovery. This app's single-file SQLite DB holds
encrypted broker API credentials and full trade history with no backup
or restore procedure anywhere before this — a corrupted disk, a bad
migration, or an accidental delete had no recovery path.

Uses SQLite's own online backup API (sqlite3.Connection.backup()) rather
than a raw file copy: a plain `shutil.copy` of a live WAL-mode database
can capture the main .db file mid-write relative to the -wal/-shm
sidecar files, producing a torn, inconsistent snapshot. The backup API
takes a page-level consistent snapshot while the source connection stays
live and usable by the app, so this can safely run on a schedule against
the production database without taking the app offline or risking a
corrupt backup.
"""
import gzip
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKUP_DIR = Path(__file__).parent.parent.parent.parent / "data" / "backups"
_RETENTION_DAYS = int(os.environ.get("DB_BACKUP_RETENTION_DAYS", "14"))


def _sqlite_path_from_uri(uri: str) -> str | None:
    """Extract a filesystem path from a sqlite:/// URI. Returns None for
    non-file (e.g. :memory:) or non-sqlite URIs — nothing to back up."""
    if not uri.startswith("sqlite:///"):
        return None
    path = uri[len("sqlite:///"):]
    if path in ("", ":memory:"):
        return None
    return path


def create_backup(app) -> str | None:
    """Creates a gzip-compressed, timestamped, consistent snapshot of the
    app's SQLite database under data/backups/. Returns the backup file
    path on success, None if the configured DB isn't SQLite (e.g.
    Postgres in some deployment) or the source file doesn't exist yet."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    src_path = _sqlite_path_from_uri(uri)
    if not src_path:
        logger.debug("DB backup skipped — not a file-based SQLite database")
        return None
    if not os.path.isabs(src_path):
        # Flask-SQLAlchemy resolves a relative sqlite:/// URI against
        # app.instance_path, NOT the process's working directory —
        # confirmed: this repo's actual DB lives at instance/smarttrade_dev.db.
        src_path = os.path.join(app.instance_path, src_path)
    if not os.path.exists(src_path):
        logger.warning(f"DB backup skipped — source file not found: {src_path}")
        return None

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    tmp_path = _BACKUP_DIR / f"smarttrade_{timestamp}.db"
    gz_path = _BACKUP_DIR / f"smarttrade_{timestamp}.db.gz"

    try:
        src_conn = sqlite3.connect(src_path)
        dst_conn = sqlite3.connect(str(tmp_path))
        with dst_conn:
            src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()

        with open(tmp_path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(tmp_path)

        size_mb = os.path.getsize(gz_path) / 1e6
        logger.info(f"DB backup created: {gz_path.name} ({size_mb:.2f} MB)")
        return str(gz_path)
    except Exception as e:
        logger.error(f"DB backup failed: {e}")
        try:
            from app.services.error_tracking import capture
            capture(e, job="create_backup")
        except Exception:
            pass
        if tmp_path.exists():
            os.remove(tmp_path)
        return None


def prune_old_backups() -> int:
    """Deletes backup files older than DB_BACKUP_RETENTION_DAYS (default
    14). Returns the count removed."""
    if not _BACKUP_DIR.exists():
        return 0
    cutoff = datetime.utcnow() - timedelta(days=_RETENTION_DAYS)
    removed = 0
    for f in _BACKUP_DIR.glob("smarttrade_*.db.gz"):
        try:
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
            if mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info(f"DB backup pruning: removed {removed} backup(s) older than {_RETENTION_DAYS} days")
    return removed


def restore_backup(app, backup_path: str, target_path: str | None = None) -> bool:
    """
    Restores a gzip-compressed backup file to target_path (or the app's
    configured DB path if not given). DESTRUCTIVE — overwrites the target
    file. Intended for manual/CLI disaster-recovery use, not called from
    any route or scheduled job; a human should run this deliberately
    after confirming which backup to restore and that the app is stopped
    (restoring into a live app's DB file while it's open is unsafe).
    """
    if target_path is None:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        target_path = _sqlite_path_from_uri(uri)
        if not target_path:
            raise ValueError("Cannot determine target path — configured DB is not file-based SQLite")
        if not os.path.isabs(target_path):
            target_path = os.path.join(app.instance_path, target_path)

    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    tmp_restored = target_path + ".restoring"
    with gzip.open(backup_path, "rb") as f_in, open(tmp_restored, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    # Verify the restored file is a valid SQLite database before
    # replacing the live target — a truncated/corrupt backup should fail
    # loudly here, not silently destroy the existing DB.
    conn = sqlite3.connect(tmp_restored)
    try:
        conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()

    shutil.move(tmp_restored, target_path)
    logger.info(f"DB restored from {backup_path} to {target_path}")
    return True


def register_backup_job(scheduler, app):
    """Daily backup at 03:00 UTC (low-traffic window), followed by
    pruning anything past the retention window."""
    def _run(app):
        with app.app_context():
            create_backup(app)
            prune_old_backups()

    scheduler.add_job(
        _run, "cron", hour=3, minute=0,
        args=[app], id="db_backup", replace_existing=True,
    )
