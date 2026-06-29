"""API key encryption utility using Fernet symmetric encryption."""
import os
import base64


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
        key = os.environ.get("ENCRYPTION_KEY")
        if not key:
            key = Fernet.generate_key().decode()
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)
    except ImportError:
        return None


def encrypt(value: str) -> str:
    f = _get_fernet()
    if not f or not value:
        return value
    return f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    f = _get_fernet()
    if not f or not value:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value
