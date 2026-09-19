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


def make_reset_token(user_id, password_hash=None):
    payload = {"uid": user_id}
    if password_hash:
        payload["password_hash"] = password_hash
    return _serializer().dumps(payload, salt=_RESET_SALT)


def read_reset_token_data(token, max_age=3600):
    try:
        return _serializer().loads(token, salt=_RESET_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired, Exception):
        return None


def read_reset_token(token, max_age=3600):  # 1h
    data = read_reset_token_data(token, max_age=max_age)
    return data.get("uid") if data else None
