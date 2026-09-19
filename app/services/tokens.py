"""Signed, expiring tokens for email verification and password reset —
stateless (no separate DB table), using the app's own SECRET_KEY so a token
can't be forged without it, and can't be reused past its expiry window."""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import current_app

_VERIFY_SALT = "email-verify"
_RESET_SALT = "password-reset"


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def make_verify_token(user_id):
    return _serializer().dumps({"uid": user_id}, salt=_VERIFY_SALT)


def read_verify_token(token, max_age=86400):  # 24h
    try:
        data = _serializer().loads(token, salt=_VERIFY_SALT, max_age=max_age)
        return data.get("uid")
    except (BadSignature, SignatureExpired, Exception):
        return None


def make_reset_token(user_id, password_hash=""):
    # Binding a short fingerprint of the CURRENT password hash into the
    # token means it stops verifying the instant the password actually
    # changes — without this, the token is a plain stateless {uid} claim
    # that stays valid and reusable for its whole 1h window even after
    # being used once, so the same link could reset the password again
    # (or be raced by a second use) within that hour. No new DB column
    # needed: the caller re-derives the same fingerprint from the user's
    # *current* hash (fetched by uid, which the signature already
    # guarantees is authentic) and only accepts a match.
    fingerprint = (password_hash or "")[-16:]
    return _serializer().dumps({"uid": user_id, "pwf": fingerprint}, salt=_RESET_SALT)


def read_reset_token(token, max_age=3600):  # 1h
    """Returns (uid, fingerprint) from an unexpired, correctly-signed
    token, or (None, None). The signature check alone proves uid is
    authentic; the caller must additionally compare the returned
    fingerprint against the target user's CURRENT password hash before
    trusting the token for a reset, since a still-unexpired token issued
    before an earlier reset must not authorize a second one."""
    try:
        data = _serializer().loads(token, salt=_RESET_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired, Exception):
        return None, None
    return data.get("uid"), data.get("pwf")
