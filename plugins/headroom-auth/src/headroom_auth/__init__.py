"""Authenticated proxy gateway — per-request auth middleware for the Headroom proxy.

Enable: ``--proxy-extension headroom-auth`` (or ``HEADROOM_PROXY_EXTENSIONS=headroom-auth``).
No-op unless ``HEADROOM_AUTH_ENABLED=true`` (the default). See README for configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

__all__ = ["install"]
__version__ = "0.1.0"
log = logging.getLogger("headroom_auth")


def install(app: Any, config: Any) -> None:
    """Headroom proxy-extension entry point: ``install(app, config) -> None``.

    Reads configuration from environment variables and registers the
    ``AuthMiddleware`` on the FastAPI *app*. Raises ``RuntimeError`` at
    startup when ``HEADROOM_ENCRYPTION_KEY`` is missing or invalid
    (fail-closed), so a misconfigured proxy refuses to start rather than
    silently serving requests without provider keys.
    """
    from headroom.auth.crypto import FernetCrypto, FernetCryptoError
    from headroom.auth.store import Neo4jAuthStore

    auth_enabled = os.environ.get("HEADROOM_AUTH_ENABLED", "true").strip().lower()
    if auth_enabled in ("0", "false", "no", "off"):
        log.info("headroom-auth: HEADROOM_AUTH_ENABLED is false; middleware is a no-op")
        auth_enabled = False
    else:
        auth_enabled = True

    # Validate the encryption key at startup (fail-closed).  If the key is
    # wrong, every request would fail with a 502 — better to abort early
    # with a clear error.
    try:
        crypto = FernetCrypto()
        crypto.validate_key()
    except FernetCryptoError as exc:
        raise RuntimeError(
            f"headroom-auth: HEADROOM_ENCRYPTION_KEY is invalid or not set. {exc}"
        ) from None

    cache_ttl_str = os.environ.get("HEADROOM_AUTH_CACHE_TTL", "10").strip()
    try:
        cache_ttl = int(cache_ttl_str)
    except ValueError:
        log.warning(
            "headroom-auth: HEADROOM_AUTH_CACHE_TTL=%r is not an integer; using default 10",
            cache_ttl_str,
        )
        cache_ttl = 10

    store = Neo4jAuthStore()

    from .cache import AuthCache
    from .middleware import AuthMiddleware

    auth_cache = AuthCache(store=store, crypto=crypto, ttl_seconds=cache_ttl)

    app.add_middleware(
        AuthMiddleware,
        auth_enabled=auth_enabled,
        store=store,
        crypto=crypto,
        auth_cache=auth_cache,
    )

    log.info(
        "headroom-auth: installed (auth_enabled=%s, cache_ttl=%ds)",
        auth_enabled,
        cache_ttl,
    )
