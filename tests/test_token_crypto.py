from cryptography.fernet import Fernet

from core.config import get_settings


def test_refresh_token_round_trip(monkeypatch) -> None:
    from core.token_crypto import decrypt_secret, encrypt_secret

    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    try:
        ciphertext = encrypt_secret("refresh-token")
        assert "refresh-token" not in ciphertext
        assert decrypt_secret(ciphertext) == "refresh-token"
    finally:
        get_settings.cache_clear()


def test_missing_encryption_key_is_rejected(monkeypatch) -> None:
    from core.token_crypto import TokenCryptoError, encrypt_secret

    monkeypatch.setenv("YOUTUBE_TOKEN_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    try:
        try:
            encrypt_secret("refresh-token")
        except TokenCryptoError as exc:
            assert "YOUTUBE_TOKEN_ENCRYPTION_KEY" in str(exc)
        else:
            raise AssertionError("missing encryption key was accepted")
    finally:
        get_settings.cache_clear()
