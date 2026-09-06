"""Regression coverage for the supported Docker Compose contract."""

from pathlib import Path


def test_compose_does_not_use_obsolete_top_level_version_key():
    source = (Path(__file__).parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8",
    )

    assert not source.lstrip().startswith("version:")


def test_worker_healthcheck_uses_redis_heartbeat_instead_of_http_probe():
    source = (Path(__file__).parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8",
    )

    assert "smarttradeai:worker:heartbeat" in source
    assert "socket_connect_timeout=2" in source
    assert "healthcheck:\n      disable: true" not in source
