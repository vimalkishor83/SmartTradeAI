"""Regression coverage for the true base Alembic revision."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[2]
    / "migrations"
    / "versions"
    / "9aa5558991b2_initial_schema.py"
)

EXPECTED_BASE_TABLES = {
    "api_configs",
    "api_logs",
    "assets",
    "audit_logs",
    "backtests",
    "economic_events",
    "journal_entries",
    "news",
    "notifications",
    "portfolio_items",
    "portfolios",
    "predictions",
    "roles",
    "signal_history",
    "signals",
    "subscriptions",
    "system_logs",
    "user_asset_preferences",
    "users",
    "watchlist_items",
    "watchlists",
}


class RecordingOperations:
    """Capture migration operations without connecting to a database."""

    def __init__(self):
        self.created_tables = []
        self.created_indexes = []

    def create_table(self, name, *args, **kwargs):
        self.created_tables.append(name)

    def create_index(self, name, table_name, columns, **kwargs):
        self.created_indexes.append((name, table_name, tuple(columns)))

    def f(self, name):
        return name


def _load_migration():
    spec = spec_from_file_location("initial_schema", MIGRATION_PATH)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_revision_creates_the_complete_base_schema():
    module = _load_migration()
    operations = RecordingOperations()
    module.op = operations

    module.upgrade()

    assert set(operations.created_tables) == EXPECTED_BASE_TABLES
    assert len(operations.created_tables) == len(EXPECTED_BASE_TABLES)
    assert operations.created_indexes
    assert not hasattr(module.op, "batch_alter_table")
