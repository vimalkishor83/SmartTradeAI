"""Regression coverage for non-destructive startup compatibility work."""

from pathlib import Path


def test_startup_compatibility_does_not_drop_legacy_tables():
    source = (Path(__file__).parents[2] / "app" / "__init__.py").read_text(
        encoding="utf-8",
    )

    assert "DROP TABLE IF EXISTS" not in source
