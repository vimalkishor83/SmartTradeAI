"""Validation and normalization for admin-managed provider configurations."""

import re


class APIConfigValidationError(ValueError):
    """Raised when an API configuration payload is not safe to persist."""


_AUTH_TYPES = {"api_key", "oauth", "token", "none"}
_STATUSES = {"active", "paused", "error"}
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


def validate_api_config_payload(data: object, *, existing=None) -> dict:
    """Return a normalized payload suitable for creating or updating a config.

    ``existing`` enables partial update validation against the current market
    and provider. The function imports the model lazily to avoid making the
    model depend on the route layer during application startup.
    """
    if not isinstance(data, dict):
        raise APIConfigValidationError("request body must be a JSON object")

    from app.models.api_config import APIConfig

    is_create = existing is None
    required = ("name", "provider", "market") if is_create else ()
    missing = [field for field in required if field not in data]
    if missing:
        raise APIConfigValidationError(
            f"{', '.join(missing)} is required"
        )

    clean = {}

    if is_create or "name" in data:
        clean["name"] = _text(data.get("name"), "name", max_length=100)

    market = data.get("market", getattr(existing, "market", None))
    if is_create or "market" in data:
        if market not in APIConfig.MARKETS:
            raise APIConfigValidationError("invalid market")
        clean["market"] = market

    provider = data.get("provider", getattr(existing, "provider", None))
    if is_create or "provider" in data or "market" in data:
        allowed = APIConfig.PROVIDERS.get(market, [])
        if provider not in allowed:
            raise APIConfigValidationError("provider is not supported for this market")
        if is_create or "provider" in data:
            clean["provider"] = provider

    for field, max_length in (("base_url", 500), ("websocket_url", 500)):
        if field in data:
            clean[field] = _text(data[field], field, max_length=max_length, allow_empty=True)

    if "auth_type" in data:
        auth_type = data["auth_type"]
        if auth_type not in _AUTH_TYPES:
            raise APIConfigValidationError("invalid auth_type")
        clean["auth_type"] = auth_type

    for field, minimum, maximum in (
        ("rate_limit", 1, 100000),
        ("refresh_interval", 5, 86400),
        ("priority", -10000, 10000),
    ):
        if field in data:
            clean[field] = _integer(data[field], field, minimum, maximum)

    for field in ("is_default", "is_active"):
        if field in data:
            clean[field] = _boolean(data[field], field)

    if "status" in data:
        status = data["status"]
        if status not in _STATUSES:
            raise APIConfigValidationError("invalid status")
        clean["status"] = status

    for field in ("api_key", "api_secret", "access_token", "refresh_token"):
        if field in data:
            clean[field] = _text(data[field], field, max_length=10000, allow_empty=True)

    return clean


def _text(value, field: str, *, max_length: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise APIConfigValidationError(f"{field} must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise APIConfigValidationError(f"{field} is required")
    if len(value) > max_length:
        raise APIConfigValidationError(f"{field} must be {max_length} characters or fewer")
    return value


def _integer(value, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise APIConfigValidationError(f"{field} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and _INTEGER_PATTERN.fullmatch(value.strip()):
        result = int(value.strip())
    else:
        raise APIConfigValidationError(f"{field} must be an integer")
    if not minimum <= result <= maximum:
        raise APIConfigValidationError(f"{field} must be between {minimum} and {maximum}")
    return result


def _boolean(value, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise APIConfigValidationError(f"{field} must be a boolean")
