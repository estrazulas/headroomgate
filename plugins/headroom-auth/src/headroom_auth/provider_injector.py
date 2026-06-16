"""Automatic provider resolution and API key injection.

Determines which upstream LLM provider to use based on the request path
and injects the correct (decrypted) provider API key into the request.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("headroom_auth.provider_injector")

# Path-prefix → provider name mapping.  Order matters: longer prefixes
# must be checked first (e.g. ``/v1beta/models/`` before ``/v1/``).
PROVIDER_PATH_MAP: list[tuple[str, str]] = [
    ("/v1/messages", "anthropic"),
    ("/v1/chat/completions", "openai"),
    ("/v1beta/models/", "gemini"),
    ("/v1internal/", "cloudcode"),
]


def resolve_provider(path: str) -> str | None:
    """Return the provider name for *path*, or ``None`` if unmatched.

    Matching is prefix-based so ``/v1/messages`` and
    ``/v1/messages?beta=true`` both resolve to ``"anthropic"``.
    """
    for prefix, provider in PROVIDER_PATH_MAP:
        if path.startswith(prefix):
            return provider
    return None


def inject_provider_key(
    headers: list[tuple[bytes, bytes]],
    provider_keys: dict[str, str],
    provider: str,
) -> tuple[list[tuple[bytes, bytes]], dict[str, Any] | None]:
    """Replace the ``Authorization`` header with the real provider key.

    Parameters:
        headers: ASGI scope headers as ``[(b"name", b"value"), ...]``.
        provider_keys: Decrypted provider keys dict (from ``CachedIdentity``).
        provider: The provider name resolved by :func:`resolve_provider`.

    Returns:
        ``(new_headers, error)`` — on success *error* is ``None`` and the
        ``Authorization`` header carries the real provider key. On failure
        *error* is a JSON-serializable dict describing the problem (suitable
        for a 502 response).
    """
    api_key = provider_keys.get(provider)
    if api_key is None:
        return headers, {
            "error": "provider_key_not_configured",
            "message": f"No API key configured for provider '{provider}' in your role.",
        }

    # Build a new header list, dropping any existing Authorization.
    new_headers: list[tuple[bytes, bytes]] = []
    for k, v in headers:
        if k.lower() != b"authorization":
            new_headers.append((k, v))
    new_headers.append((b"authorization", b"Bearer " + api_key.encode("ascii")))
    return new_headers, None
