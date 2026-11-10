"""Password hashing and session-token hashing.

The raw session token is returned to the browser once. Only an HMAC of the
token is stored. Passwords are Argon2id hashes and are never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()
SESSION_COOKIE = "autopilot_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(raw_token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()
