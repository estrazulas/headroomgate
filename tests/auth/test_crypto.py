"""Unit tests for FernetCrypto (task 5.2)."""

import pytest

from headroom.auth.crypto import FernetCrypto, FernetCryptoError


class TestFernetCrypto:
    """Task 5.2 — encrypt/decrypt roundtrip, wrong key, corrupted token, validate_key."""

    def test_generate_key_produces_valid_key(self) -> None:
        key = FernetCrypto.generate_key()
        assert len(key) == 44  # 32 bytes base64 = 44 chars
        assert key.endswith("=")

    def test_encrypt_decrypt_roundtrip(self) -> None:
        key = FernetCrypto.generate_key()
        fc = FernetCrypto(encryption_key=key)
        plaintext = "sk-ant-api03-deadbeef"
        token = fc.encrypt(plaintext)
        assert plaintext not in token
        decrypted = fc.decrypt(token)
        assert decrypted == plaintext

    def test_same_plaintext_produces_different_tokens(self) -> None:
        key = FernetCrypto.generate_key()
        fc = FernetCrypto(encryption_key=key)
        token1 = fc.encrypt("hello")
        token2 = fc.encrypt("hello")
        assert token1 != token2  # timestamp-based

    def test_decrypt_with_wrong_key_raises(self) -> None:
        key1 = FernetCrypto.generate_key()
        key2 = FernetCrypto.generate_key()
        fc1 = FernetCrypto(encryption_key=key1)
        token = fc1.encrypt("secret")

        fc2 = FernetCrypto(encryption_key=key2)
        with pytest.raises(FernetCryptoError, match="invalid or has changed"):
            fc2.decrypt(token)

    def test_decrypt_corrupted_token_raises(self) -> None:
        key = FernetCrypto.generate_key()
        fc = FernetCrypto(encryption_key=key)
        token = fc.encrypt("secret")
        corrupted = token[:20] + "X" * (len(token) - 20)
        with pytest.raises(FernetCryptoError):
            fc.decrypt(corrupted)

    def test_validate_key_with_valid_key(self) -> None:
        key = FernetCrypto.generate_key()
        fc = FernetCrypto(encryption_key=key)
        fc.validate_key()  # should not raise

    def test_validate_key_with_invalid_key(self) -> None:
        fc = FernetCrypto(encryption_key="not-a-valid-key")
        with pytest.raises(FernetCryptoError, match="not a valid Fernet key"):
            fc.validate_key()
