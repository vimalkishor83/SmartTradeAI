"""Small shared response contracts for data-heavy frontend modules."""

from datetime import datetime, timezone


CONTRACT_VERSION = "1.0"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def contract_meta(*, source, generated_at=None, freshness=None, pagination=None):
    """Return stable, non-sensitive metadata shared by canonical APIs."""
    meta = {
        "contract_version": CONTRACT_VERSION,
        "source": source,
        "generated_at": generated_at or utc_now_iso(),
    }
    if freshness is not None:
        meta["freshness"] = freshness
    if pagination is not None:
        meta["pagination"] = pagination
    return meta


def with_contract(payload, *, source, generated_at=None, freshness=None, pagination=None):
    """Attach ``_meta`` without changing the existing top-level fields."""
    result = dict(payload)
    result["_meta"] = contract_meta(
        source=source,
        generated_at=generated_at,
        freshness=freshness,
        pagination=pagination,
    )
    return result
