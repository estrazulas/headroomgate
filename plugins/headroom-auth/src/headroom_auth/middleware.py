"""ASGI middleware that authenticates every request and injects provider keys.

Follows the same pattern as ``OAuth2Middleware`` in ``plugins/headroom-oauth2``:
a plain ASGI class registered via ``app.add_middleware(AuthMiddleware, ...)``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from .identity import clear_current_identity, set_current_identity
from .provider_injector import inject_provider_key, resolve_provider
from .rate_limiter import rate_limit_error

log = logging.getLogger("headroom_auth.middleware")

# Endpoints that never require authentication.
_HEALTH_CHECK_PATHS: frozenset[str] = frozenset(
    {"/livez", "/readyz", "/health", "/metrics"}
)


def _json_response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build ASGI response start + body messages for a JSON error."""
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return {
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            (b"cache-control", b"no-store"),
        ],
    }, {"type": "http.response.body", "body": payload}


class AuthMiddleware:
    """ASGI middleware for per-request authentication and provider key injection.

    Parameters:
        app: The inner ASGI application.
        auth_enabled: When ``False``, all requests pass through unmodified.
        store: ``Neo4jAuthStore`` instance for key validation.
        crypto: ``FernetCrypto`` instance for provider key decryption.
        auth_cache: ``AuthCache`` instance for validation caching.
    """

    def __init__(
        self,
        app: Any,
        auth_enabled: bool = True,
        store: Any = None,
        crypto: Any = None,
        auth_cache: Any = None,
    ) -> None:
        self.app = app
        self._auth_enabled = auth_enabled
        self._store = store
        self._crypto = crypto
        self._cache = auth_cache

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        # Only intercept HTTP requests.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Health checks never require auth.
        if path in _HEALTH_CHECK_PATHS:
            await self.app(scope, receive, send)
            return

        # Auth disabled? Pass through untouched.
        if not self._auth_enabled:
            await self.app(scope, receive, send)
            return

        # ---- 1. Extract and validate the Authorization header ----
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        auth_value = self._extract_auth_header(headers)
        if auth_value is None:
            start, body = _json_response(
                401,
                {
                    "error": "missing_auth_header",
                    "message": "Authorization header is required.",
                },
            )
            await send(start)
            await send(body)
            return

        auth_error = self._validate_key_format(auth_value)
        if auth_error:
            start, body = _json_response(401, auth_error)
            await send(start)
            await send(body)
            return

        # ---- 2. Resolve identity (cache → Neo4j → stale fallback) ----
        identity, resolve_error = await self._resolve_identity(auth_value)
        if resolve_error:
            status, err_body = resolve_error
            start, body = _json_response(status, err_body)
            await send(start)
            await send(body)
            return

        # identity is guaranteed non-None here — the error path above
        # handles all None cases.

        # ---- 3. Set identity for downstream consumers ----
        set_current_identity(
            user_id=identity.user_id,
            username=identity.username,
            role=identity.role,
            team=identity.team,
        )

        try:
            # ---- 4. Rate limit check ----
            from .rate_limiter import PerUserRateLimiter

            limiter = _get_rate_limiter()
            allowed, retry_after, rate_headers = await limiter.check_rate_limit(
                user_id=identity.user_id,
                rpm=identity.default_rpm,
                tpm=identity.default_tpm,
            )
            if not allowed:
                start, body = _json_response(429, rate_limit_error(retry_after))
                # Merge Retry-After into response headers.
                resp_headers = list(start["headers"])
                resp_headers.append(
                    (b"retry-after", str(int(retry_after)).encode())
                )
                start["headers"] = resp_headers
                await send(start)
                await send(body)
                return

            # ---- 5. Provider key injection ----
            provider = resolve_provider(path)
            new_headers = headers
            if provider is not None:
                new_headers, inject_error = inject_provider_key(
                    headers, identity.provider_keys, provider
                )
                if inject_error:
                    start, body = _json_response(502, inject_error)
                    await send(start)
                    await send(body)
                    return

            # ---- 6. Forward to upstream ----
            modified_scope = dict(scope, headers=new_headers)
            await self.app(modified_scope, receive, send)

        finally:
            # Always clear identity so it never leaks across requests.
            clear_current_identity()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_auth_header(headers: list[tuple[bytes, bytes]]) -> str | None:
        """Return the bearer token, or ``None`` if absent.

        Handles both ``Bearer hr_...`` (standard) and bare ``hr_...``
        (lenient, for clients that cannot set the scheme).
        """
        for k, v in headers:
            if k.lower() == b"authorization":
                value = v.decode("ascii", errors="replace")
                # Case-insensitive "Bearer " prefix.
                if value.lower().startswith("bearer "):
                    return value.split(" ", 1)[1]
                return value  # wrong scheme or bare key — let validation sort it out
        return None

    @staticmethod
    def _validate_key_format(raw_key: str) -> dict[str, Any] | None:
        """Check structural validity. Returns an error dict or ``None``."""
        if not raw_key.startswith("hr_"):
            return {
                "error": "invalid_key_format",
                "message": "API key must start with hr_.",
            }
        if len(raw_key) < 10:
            return {
                "error": "invalid_key_format",
                "message": "API key is too short.",
            }
        return None

    async def _resolve_identity(self, raw_key: str) -> tuple[Any, tuple[int, dict] | None]:
        """Resolve the authenticated user identity.

        Returns ``(identity, None)`` on success, or
        ``(None, (status, error_dict))`` on failure.
        """
        import hashlib

        from .cache import CachedIdentity

        key_hash = hashlib.sha256(raw_key.encode("ascii")).hexdigest()

        # 1. Check cache
        cached = await self._cache.get(key_hash)
        if cached is not None:
            return cached, None

        # 2. Cache miss — query Neo4j in executor (blocking)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._store.resolve_key_identity, raw_key
            )
        except Exception as exc:
            log.warning(
                "auth-middleware: Neo4j query failed for key hash %s: %s",
                key_hash[:16],
                exc,
            )
            # 3. Neo4j unreachable — serve stale cache
            stale = await self._cache.get_stale(key_hash)
            if stale is not None:
                log.warning(
                    "auth-middleware: Neo4j unreachable, serving stale cache for user '%s'",
                    stale.username,
                )
                return stale, None
            return None, (
                503,
                {
                    "error": "auth_service_unavailable",
                    "message": "Authentication service is temporarily unavailable.",
                },
            )

        if result is None:
            # Key not found in Neo4j — could be invalid, expired, or user deactivated.
            # We need to distinguish these cases.
            return None, await self._classify_key_failure(raw_key)

        # 4. Build cached identity (this also decrypts provider keys)
        identity = CachedIdentity.from_resolve_result(result, self._crypto)
        await self._cache.set(key_hash, identity)
        return identity, None

    async def _classify_key_failure(self, raw_key: str) -> tuple[int, dict]:
        """Determine *why* a key failed to resolve (invalid, expired, revoked, user inactive)."""
        import hashlib

        key_hash = hashlib.sha256(raw_key.encode("ascii")).hexdigest()

        # Check if the key exists at all (regardless of active/expiry).
        try:
            loop = asyncio.get_running_loop()
            owner = await loop.run_in_executor(
                None, self._store.get_key_owner, raw_key
            )
        except Exception:
            # Neo4j is down and no stale cache — already handled above.
            return 503, {
                "error": "auth_service_unavailable",
                "message": "Authentication service is temporarily unavailable.",
            }

        if owner is None:
            return 401, {
                "error": "invalid_api_key",
                "message": "API key is not valid.",
            }

        if owner.get("status") == "deactivated":
            return 403, {
                "error": "user_deactivated",
                "message": "Your account has been deactivated.",
            }

        # Key exists but resolve_key_identity returned None → expired or revoked.
        return 401, {
            "error": "api_key_expired",
            "message": "Your key has expired. Contact your team lead to renew.",
        }


# Module-level rate limiter singleton (lazily created).
_rate_limiter: Any = None


def _get_rate_limiter() -> Any:
    """Return the module-level ``PerUserRateLimiter`` singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        from .rate_limiter import PerUserRateLimiter

        _rate_limiter = PerUserRateLimiter()
    return _rate_limiter
