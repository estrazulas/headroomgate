"""Symmetric encryption for provider API keys using Fernet.

Fernet bundles AES-128-CBC + HMAC-SHA256 + expiration timestamp,
making it safe-by-default for the "encrypt at rest" use case.
"""

from __future__ import annotations

import base64
import os


class FernetCrypto:
    """Thin wrapper around ``cryptography.fernet.Fernet`` with key validation."""

    def __init__(self, encryption_key: str | None = None) -> None:
        """Initialize with an optional encryption key.

        If *encryption_key* is not provided, the ``HEADROOM_ENCRYPTION_KEY``
        environment variable is read.
        """
        self._key: str | None = encryption_key
        self._fernet: object | None = None

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_key(key: str | None) -> str:
        """Return the Fernet key, resolving from env if needed."""
        if key:
            return key
        env_key = os.environ.get("HEADROOM_ENCRYPTION_KEY", "")
        if not env_key:
            raise FernetCryptoError(
                "HEADROOM_ENCRYPTION_KEY is not set. "
                "Generate one with: headroom auth generate-key"
            )
        return env_key

    @staticmethod
    def _validate_key_format(key: str) -> None:
        """Raise ``FernetCryptoError`` if *key* is not a valid Fernet key."""
        try:
            raw = base64.urlsafe_b64decode(key.encode("ascii") + b"==")
        except Exception as exc:
            raise FernetCryptoError(
                "HEADROOM_ENCRYPTION_KEY is not a valid Fernet key: "
                "must be 32 bytes of urlsafe-base64 data."
            ) from exc
        if len(raw) != 32:
            raise FernetCryptoError(
                "HEADROOM_ENCRYPTION_KEY is not a valid Fernet key: "
                f"decoded to {len(raw)} bytes, expected 32."
            )

    def _get_fernet(self) -> object:
        """Return (and cache) the Fernet instance for the configured key."""
        if self._fernet is not None:
            return self._fernet
        from cryptography.fernet import Fernet

        key = self._resolve_key(self._key)
        self._validate_key_format(key)
        self._fernet = Fernet(key.encode("ascii"))
        return self._fernet

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: str, key: str | None = None) -> str:
        """Encrypt *plaintext* and return a Fernet token string.

        The token is a base64 blob containing the ciphertext + HMAC.
        """
        f = self._get_fernet() if key is None else self._fernet_for_key(key)
        token: bytes = f.encrypt(plaintext.encode("utf-8"))
        return token.decode("ascii")

    def decrypt(self, token: str, key: str | None = None) -> str:
        """Decrypt *token* and return the original plaintext.

        Raises ``FernetCryptoError`` when the key is wrong or the token
        has been corrupted.
        """
        try:
            f = self._get_fernet() if key is None else self._fernet_for_key(key)
            plaintext: bytes = f.decrypt(token.encode("ascii"))
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise FernetCryptoError(
                "HEADROOM_ENCRYPTION_KEY is invalid or has changed. "
                "Provider keys cannot be decrypted."
            ) from exc

    def validate_key(self, key: str | None = None) -> None:
        """Validate the format of *key* (or ``HEADROOM_ENCRYPTION_KEY``).

        Uses the instance's stored key if no explicit *key* is given.
        Raises ``FernetCryptoError`` if the key is missing or malformed.
        """
        resolved = key or self._key
        if resolved is None:
            resolved = self._resolve_key(None)
        self._validate_key_format(resolved)

    @staticmethod
    def generate_key() -> str:
        """Generate a new random Fernet key.

        Returns a 32-byte urlsafe-base64-encoded string suitable for
        ``HEADROOM_ENCRYPTION_KEY``.
        """
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode("ascii")

    def _fernet_for_key(self, key: str) -> object:
        """Build a one-off Fernet instance for a specific *key*."""
        from cryptography.fernet import Fernet

        self._validate_key_format(key)
        return Fernet(key.encode("ascii"))


class FernetCryptoError(Exception):
    """Raised when encryption, decryption, or key validation fails."""
