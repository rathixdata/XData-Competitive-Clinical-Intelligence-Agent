"""Hashing and application-level field encryption (NFR-SEC-004/005)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def stable_json(obj: Any) -> str:
    """Canonical JSON (sorted keys, no whitespace) used for hashing and fingerprints."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def stable_hash(obj: Any) -> str:
    return sha256_hex(stable_json(obj))


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    prefix = raw[:8]
    key = f"xdk_{raw}"
    return key, prefix, sha256_hex(key)


def _fernet() -> Fernet:
    s = get_settings()
    if s.field_encryption_key is not None:
        return Fernet(s.field_encryption_key.get_secret_value().encode())
    # Development fallback: derive a key from the JWT secret. Production requires an explicit key.
    digest = hashlib.sha256(("fernet:" + s.jwt_secret.get_secret_value()).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_json(obj: Any) -> str:
    return _fernet().encrypt(stable_json(obj).encode()).decode()


def decrypt_json(token: str | None) -> Any:
    if not token:
        return None
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise ValueError("unable to decrypt field") from e


def hmac_sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
