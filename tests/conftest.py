"""
Shared pytest fixtures. Uses the app's existing TestingConfig
(sqlite:///:memory:, see app/config.py) so tests never touch the real dev
database, and disables the background scheduler so test runs don't spin
up live market-data polling threads.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-not-for-production-use-only")


@pytest.fixture
def app():
    from app import create_app
    from app.config import TestingConfig

    application = create_app(TestingConfig)
    application.config["SCHEDULER_API_ENABLED"] = False
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def app_context(app):
    with app.app_context():
        yield app
