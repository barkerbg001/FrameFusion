"""Encryption of provider API keys at rest (Fernet: AES-128-CBC + HMAC-SHA256).

The key comes from ``FRAMEFUSION_ENCRYPTION_KEY`` in the environment and is never
stored in SQLite. Multiple comma-separated keys enable rotation: the first key
encrypts, every key can decrypt.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

from engine.llm import LLMConfigurationError


class EncryptionUnavailable(LLMConfigurationError):
    def __init__(self, message: str) -> None:
        super().__init__(message, kind="encryption_unavailable")


def _fernet() -> MultiFernet:
    keys = list(getattr(settings, "FRAMEFUSION_ENCRYPTION_KEYS", []) or [])
    if not keys:
        raise EncryptionUnavailable(
            "Saving API keys requires FRAMEFUSION_ENCRYPTION_KEY to be set on the server. "
            "Run `npm run setup` or see README → Encryption."
        )
    try:
        return MultiFernet([Fernet(key.encode()) for key in keys])
    except (ValueError, TypeError) as exc:
        raise EncryptionUnavailable(
            "FRAMEFUSION_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64 bytes)."
        ) from exc


def encryption_configured() -> bool:
    try:
        _fernet()
    except EncryptionUnavailable:
        return False
    return True


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionUnavailable(
            "A saved API key could not be decrypted. The server encryption key may have "
            "changed; re-enter the key in Settings."
        ) from exc


def key_hint(secret: str) -> str:
    """Last four characters only; the UI shows it as ••••abcd."""
    return secret[-4:] if len(secret) >= 12 else ""
