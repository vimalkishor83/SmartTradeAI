"""Regression coverage for encrypted admin-provider credentials."""


def test_api_config_tokens_are_encrypted_at_rest(app):
    from app.models.api_config import APIConfig

    with app.app_context():
        config = APIConfig()
        config.set_access_token("access-token-value")
        config.set_refresh_token("refresh-token-value")

        assert config.access_token.startswith("gAAAAA")
        assert config.refresh_token.startswith("gAAAAA")
        assert config.get_access_token() == "access-token-value"
        assert config.get_refresh_token() == "refresh-token-value"


def test_api_config_tokens_can_read_legacy_plaintext_values(app):
    from app.models.api_config import APIConfig

    with app.app_context():
        config = APIConfig(
            access_token="legacy-access-token",
            refresh_token="legacy-refresh-token",
        )

        assert config.get_access_token() == "legacy-access-token"
        assert config.get_refresh_token() == "legacy-refresh-token"
