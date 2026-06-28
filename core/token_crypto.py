"""Encryption helpers for OAuth credentials stored in PostgreSQL."""

from cryptography.fernet import Fernet, InvalidToken

from core.config import get_settings


class TokenCryptoError(RuntimeError):
    """Raised when credential encryption is unavailable or invalid."""


def _fernet() -> Fernet:
    key = get_settings().youtube_token_encryption_key.strip().encode()
    if not key:
        raise TokenCryptoError("YOUTUBE_TOKEN_ENCRYPTION_KEY is required")
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise TokenCryptoError("YOUTUBE_TOKEN_ENCRYPTION_KEY is invalid") from exc


def encrypt_secret(value: str) -> str:
    """Encrypt a non-empty secret for persistent storage."""
    if not value:
        raise TokenCryptoError("secret must not be empty")
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Decrypt a stored secret without exposing ciphertext details."""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenCryptoError("encrypted token cannot be decrypted") from exc
