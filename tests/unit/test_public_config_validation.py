from app.api.v1.public_config import _valid_social_url


def test_social_url_validation_rejects_placeholders_and_cross_platform_links():
    assert _valid_social_url("facebook", "https://facebook.com/") == ""
    assert _valid_social_url("linkedin", "https://t.me/smarttradeai") == ""
    assert _valid_social_url("youtube", "https://youtube.com/@smarttradeai")


def test_social_url_validation_requires_official_host_and_profile_path():
    assert _valid_social_url("telegram", "https://t.me/smarttradeai")
    assert _valid_social_url("x", "https://twitter.com/smarttradeai")
    assert _valid_social_url("discord", "https://example.com/community") == ""
    assert _valid_social_url("instagram", "smarttradeai") == ""


def test_admin_social_configuration_uses_the_same_validator():
    source = open("app/api/v1/admin.py", encoding="utf-8").read()
    assert "from app.api.v1.public_config import _valid_social_url" in source
    assert "_valid_social_url(platform, url)" in source


def test_public_site_config_is_bounded_and_cached():
    source = open("app/api/v1/public_config.py", encoding="utf-8").read()
    assert '@limiter.limit("60 per minute", override_defaults=True)' in source
    assert '@cache.cached(timeout=300, key_prefix="public_site_config")' in source
