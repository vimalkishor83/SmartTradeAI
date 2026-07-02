"""
At-rest encryption for sensitive credentials (trading API keys/secrets).

Uses Fernet (AES-128-CBC + HMAC) with a key derived from the app's
SECRET_KEY via PBKDF2. This is app-instance-specific: rotating SECRET_KEY
invalidates previously-encrypted values, matching how JWT/session secrets
already behave in this app.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

_SALT = b"smarttradeai-apiconfig-v1"  # static salt — fine for PBKDF2 keyed off a secret app key


def _fernet() -> Fernet:
    secret = current_app.config.get("SECRET_KEY", "dev-secret-key-change-in-production").encode()
    key = hashlib.pbkdf2_hmac("sha256", secret, _SALT, 100_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext credential for storage. Returns a string safe for a Text column."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str | None:
    """Decrypt a stored credential. Returns None if it can't be decrypted
    (e.g. was stored as legacy plaintext before encryption was added, or
    SECRET_KEY changed) — callers must handle this rather than crash."""
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def is_encrypted(value: str) -> bool:
    """Best-effort check: does this look like a Fernet token (vs. legacy plaintext)?"""
    if not value:
        return False
    try:
        base64.urlsafe_b64decode(value.encode() + b"=" * (-len(value) % 4))
        return value.startswith("gAAAAA")  # Fernet tokens have this fixed prefix pattern
    except Exception:
        return False
