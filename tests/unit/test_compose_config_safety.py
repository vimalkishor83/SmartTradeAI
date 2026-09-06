"""Regression coverage for the supported Docker Compose contract."""

from pathlib import Path


def test_compose_does_not_use_obsolete_top_level_version_key():
    source = (Path(__file__).parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8",
    )

    assert not source.lstrip().startswith("version:")
