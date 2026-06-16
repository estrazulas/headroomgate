"""Unit tests for AuthMiddleware (PRD 2 tasks 6.1-6.5)."""

import asyncio
import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from headroom_auth.cache import AuthCache, CachedIdentity
from headroom_auth.middleware import AuthMiddleware, _HEALTH_CHECK_PATHS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _kh(key: str) -> str:
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def _make_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers or [],
    }


def _make_header_dict(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    return {k.decode(): v.decode() for k, v in headers}


async def _collect_response(app, scope) -> dict:
    """Run the app against *scope* and collect the response as a dict."""
    collected: dict = {"status": None, "headers": [], "body": b""}
    send_messages: list = []

    async def send(msg):
        send_messages.append(msg)

    await app(scope, _dummy_receive, send)

    for msg in send_messages:
        if msg["type"] == "http.response.start":
            collected["status"] = msg["status"]
            collected["headers"] = _make_header_dict(msg["headers"])
        elif msg["type"] == "http.response.body":
            collected["body"] += msg.get("body", b"")
    return collected


async def _dummy_receive() -> dict:
    return {"type": "http.request", "body": b""}


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.resolve_key_identity.return_value = {
        "user_id": "u_joao",
        "username": "joao",
        "role": "developer",
        "team": "backend",
        "is_active": True,
        "provider_keys": "{}",
        "default_rpm": 60,
        "default_tpm": 100_000,
        "key_expires_at": None,
    }
    store.get_key_owner.return_value = {
        "username": "joao",
        "role": "developer",
        "team": "backend",
        "status": "active",
    }
    return store


def _mock_crypto() -> MagicMock:
    crypto = MagicMock()
    crypto.decrypt.return_value = "sk-ant-decrypted"
    crypto.validate_key.return_value = None
    return crypto


def _echo_app():
    """An inner app that echoes the Authorization header back as 200."""

    async def app(scope, receive, send):
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"none").decode()
        body = json.dumps({"echo": auth}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


class TestMiddlewareAuth:
    """Authentication scenarios (key validation, errors)."""

    @pytest.fixture
    def store(self) -> MagicMock:
        return _mock_store()

    @pytest.fixture
    def crypto(self) -> MagicMock:
        return _mock_crypto()

    @pytest.fixture
    def cache(self) -> AuthCache:
        return AuthCache(ttl_seconds=10)

    def _middleware(self, store, crypto, cache, auth_enabled: bool = True):
        inner = _echo_app()
        return AuthMiddleware(inner, auth_enabled=auth_enabled, store=store, crypto=crypto, auth_cache=cache)

    # -- success path --

    async def test_valid_key_proceeds_to_upstream(self, store, crypto, cache) -> None:
        # Store returns a provider key for anthropic so injection succeeds
        import json

        store.resolve_key_identity.return_value["provider_keys"] = json.dumps(
            {"anthropic": "encrypted-sk-ant"}
        )
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_a7f3b9c2d1e5...")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200

    async def test_cache_hit_no_neo4j_query(self, store, crypto, cache) -> None:
        raw_key = "hr_cached_key_12345"
        kh = _kh(raw_key)
        # Pre-populate cache
        ident = CachedIdentity(
            user_id="u_cached",
            username="cached_user",
            role="developer",
            team="backend",
            provider_keys={"anthropic": "sk-ant-test"},
        )
        await cache.set(kh, ident)

        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer " + raw_key.encode())])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200
        # Neo4j was never queried
        store.resolve_key_identity.assert_not_called()

    # -- error paths --

    async def test_missing_auth_header_returns_401(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages")  # no Authorization header
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 401
        body = json.loads(resp["body"])
        assert body["error"] == "missing_auth_header"

    async def test_wrong_auth_scheme_returns_401(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Basic abc123")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 401
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_key_format"

    async def test_invalid_key_format_no_hr_prefix_returns_401(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer invalid")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 401

    async def test_key_not_found_in_neo4j_returns_401(self, store, crypto, cache) -> None:
        store.resolve_key_identity.return_value = None
        store.get_key_owner.return_value = None  # not even the key exists
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_deadbeef1234")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 401
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_api_key"

    async def test_deactivated_user_returns_403(self, store, crypto, cache) -> None:
        store.resolve_key_identity.return_value = None  # user is_active: false → no match
        store.get_key_owner.return_value = {
            "username": "deactivated_user",
            "role": "developer",
            "team": "backend",
            "status": "deactivated",
        }
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_valid_inactive")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 403
        body = json.loads(resp["body"])
        assert body["error"] == "user_deactivated"

    async def test_expired_key_returns_401(self, store, crypto, cache) -> None:
        store.resolve_key_identity.return_value = None
        # get_key_owner returns the owner but resolve fails → expired or revoked
        store.get_key_owner.return_value = {
            "username": "expired_user",
            "role": "developer",
            "team": "backend",
            "status": "active",
        }
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_expired_1234")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 401
        body = json.loads(resp["body"])
        assert body["error"] == "api_key_expired"

    # -- health checks --

    async def test_livez_bypasses_auth(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/livez")  # no auth header
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200

    async def test_readyz_bypasses_auth(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/readyz")
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200

    async def test_health_bypasses_auth(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/health")
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200

    async def test_metrics_bypasses_auth(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/metrics")
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200

    # -- websocket skip --

    async def test_websocket_skips_auth(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = {"type": "websocket", "path": "/v1/messages"}
        # Should NOT return an error response
        send_messages = []

        async def send(msg):
            send_messages.append(msg)

        # WebSocket is passed to inner app without auth check
        await mw(scope, _dummy_receive, send)

    # -- auth disabled --

    async def test_auth_disabled_passes_through(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache, auth_enabled=False)
        scope = _make_scope("/v1/messages")  # no auth header
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200
        # No Neo4j queries
        store.resolve_key_identity.assert_not_called()

    # -- health check paths are correct --

    def test_health_check_paths(self) -> None:
        assert "/livez" in _HEALTH_CHECK_PATHS
        assert "/readyz" in _HEALTH_CHECK_PATHS
        assert "/health" in _HEALTH_CHECK_PATHS
        assert "/metrics" in _HEALTH_CHECK_PATHS


class TestMiddlewareNeo4jFallback:
    """Stale cache fallback when Neo4j is unreachable."""

    @pytest.fixture
    def store(self) -> MagicMock:
        store = _mock_store()
        return store

    @pytest.fixture
    def crypto(self) -> MagicMock:
        return _mock_crypto()

    @pytest.fixture
    def cache(self) -> AuthCache:
        return AuthCache(ttl_seconds=10)

    def _middleware(self, store, crypto, cache, auth_enabled: bool = True):
        inner = _echo_app()
        return AuthMiddleware(inner, auth_enabled=auth_enabled, store=store, crypto=crypto, auth_cache=cache)

    async def test_neo4j_down_stale_cache_served(self, store, crypto, cache) -> None:
        raw_key = "hr_stale_fallback_key"
        kh = _kh(raw_key)
        # Pre-populate cache with an expired entry
        ident = CachedIdentity(
            user_id="u_stale",
            username="stale_user",
            role="developer",
            team="backend",
            provider_keys={"anthropic": "sk-ant-stale"},
        )
        await cache.set(kh, ident)
        # Force Neo4j failure
        store.resolve_key_identity.side_effect = Exception("Neo4j connection refused")

        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer " + raw_key.encode())])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200  # stale served

    async def test_neo4j_down_no_cache_returns_503(self, store, crypto, cache) -> None:
        store.resolve_key_identity.side_effect = Exception("Neo4j connection refused")

        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_nocache_key")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 503
        body = json.loads(resp["body"])
        assert body["error"] == "auth_service_unavailable"


class TestMiddlewareProviderInjection:
    """Provider key injection in the middleware pipeline."""

    @pytest.fixture
    def store(self) -> MagicMock:
        store = _mock_store()
        # Return an identity with a provider key
        import json

        store.resolve_key_identity.return_value = {
            "user_id": "u_joao",
            "username": "joao",
            "role": "developer",
            "team": "backend",
            "is_active": True,
            "provider_keys": json.dumps({"anthropic": "encrypted-sk-ant"}),
            "default_rpm": 60,
            "default_tpm": 100_000,
            "key_expires_at": None,
        }
        return store

    @pytest.fixture
    def crypto(self) -> MagicMock:
        crypto = MagicMock()
        crypto.decrypt.return_value = "sk-ant-decrypted-token"
        crypto.validate_key.return_value = None
        return crypto

    @pytest.fixture
    def cache(self) -> AuthCache:
        return AuthCache(ttl_seconds=10)

    def _middleware(self, store, crypto, cache):
        inner = _echo_app()
        return AuthMiddleware(inner, auth_enabled=True, store=store, crypto=crypto, auth_cache=cache)

    async def test_provider_key_injected_in_forwarded_request(self, store, crypto, cache) -> None:
        mw = self._middleware(store, crypto, cache)
        scope = _make_scope("/v1/messages", [(b"authorization", b"Bearer hr_valid_key123")])
        resp = await _collect_response(mw, scope)
        assert resp["status"] == 200
        # The echo app returns the Authorization header that was forwarded
        body = json.loads(resp["body"])
        assert "sk-ant-decrypted-token" in body["echo"]


class TestMiddlewareRateLimiting:
    """Rate limit enforcement in the middleware pipeline."""

    @pytest.fixture
    def store(self) -> MagicMock:
        return _mock_store()

    @pytest.fixture
    def crypto(self) -> MagicMock:
        return _mock_crypto()

    @pytest.fixture
    def cache(self) -> AuthCache:
        return AuthCache(ttl_seconds=10)

    def _middleware(self, store, crypto, cache):
        inner = _echo_app()
        return AuthMiddleware(inner, auth_enabled=True, store=store, crypto=crypto, auth_cache=cache)

    async def test_rate_limit_exceeded_returns_429(self, store, crypto, cache) -> None:
        raw_key = "hr_ratelimit_test_key"
        # Pre-populate cache so we skip Neo4j. Use a path with no provider
        # mapping so we don't need provider keys for the test.
        kh = _kh(raw_key)
        ident = CachedIdentity(
            user_id="u_rl",
            username="rl_user",
            role="developer",
            team="backend",
            provider_keys={},
            default_rpm=1,  # only 1 RPM
            default_tpm=100_000,
        )
        await cache.set(kh, ident)

        mw = self._middleware(store, crypto, cache)
        # Use /v1/custom which has no provider mapping → no injection needed
        scope = _make_scope("/v1/custom", [(b"authorization", b"Bearer " + raw_key.encode())])

        # First request — allowed (no provider injection needed for /v1/custom)
        resp1 = await _collect_response(mw, scope)
        assert resp1["status"] == 200

        # Second request — rate limited (RPM=1)
        resp2 = await _collect_response(mw, scope)
        assert resp2["status"] == 429
        body = json.loads(resp2["body"])
        assert body["error"] == "rate_limit_exceeded"
