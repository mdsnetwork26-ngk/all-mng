import os
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")


def _fernet():
    # Derive a 32-byte key from SECRET_KEY
    digest = hashlib.sha256(SECRET_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(value: str) -> str:
    if not value:
        return value
    try:
        return _fernet().encrypt(value.encode()).decode()
    except Exception:
        return value


def decrypt(value: str) -> str:
    if not value:
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        # legacy plaintext
        return value