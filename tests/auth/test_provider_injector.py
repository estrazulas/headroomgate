"""Unit tests for provider injector (PRD 2 tasks 4.1-4.3)."""

import pytest

from headroom_auth.provider_injector import (
    PROVIDER_PATH_MAP,
    inject_provider_key,
    resolve_provider,
)


class TestResolveProvider:
    """Path-based provider resolution."""

    def test_anthropic_path(self) -> None:
        assert resolve_provider("/v1/messages") == "anthropic"

    def test_anthropic_path_with_query(self) -> None:
        assert resolve_provider("/v1/messages?beta=true") == "anthropic"

    def test_openai_path(self) -> None:
        assert resolve_provider("/v1/chat/completions") == "openai"

    def test_gemini_path(self) -> None:
        assert resolve_provider("/v1beta/models/gemini-2.5-flash:generateContent") == "gemini"

    def test_cloudcode_path(self) -> None:
        assert resolve_provider("/v1internal/generate") == "cloudcode"

    def test_unknown_path(self) -> None:
        assert resolve_provider("/v1/unknown-endpoint") is None

    def test_root_path(self) -> None:
        assert resolve_provider("/") is None

    def test_empty_path(self) -> None:
        assert resolve_provider("") is None

    def test_provider_path_map_is_ordered(self) -> None:
        """Longer prefixes must come before shorter ones."""
        # /v1/messages (anthropic) should come before any /v1/ prefix
        paths = [p for p, _ in PROVIDER_PATH_MAP]
        assert paths == ["/v1/messages", "/v1/chat/completions", "/v1beta/models/", "/v1internal/"]


class TestInjectProviderKey:
    """Provider key injection into ASGI headers."""

    def test_injects_anthropic_key(self) -> None:
        headers: list[tuple[bytes, bytes]] = [
            (b"authorization", b"Bearer hr_test"),
            (b"content-type", b"application/json"),
        ]
        new_headers, err = inject_provider_key(
            headers, {"anthropic": "sk-ant-real-key"}, "anthropic"
        )
        assert err is None
        auth_values = [v for k, v in new_headers if k.lower() == b"authorization"]
        assert len(auth_values) == 1
        assert auth_values[0] == b"Bearer sk-ant-real-key"

    def test_preserves_other_headers(self) -> None:
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"x-request-id", b"abc123"),
        ]
        new_headers, err = inject_provider_key(
            headers, {"openai": "sk-proj-real"}, "openai"
        )
        assert err is None
        assert (b"content-type", b"application/json") in new_headers
        assert (b"x-request-id", b"abc123") in new_headers

    def test_replaces_existing_auth_header(self) -> None:
        headers: list[tuple[bytes, bytes]] = [
            (b"authorization", b"Bearer hr_old"),
        ]
        new_headers, err = inject_provider_key(
            headers, {"anthropic": "sk-ant-new"}, "anthropic"
        )
        assert err is None
        auth_values = [v for k, v in new_headers if k.lower() == b"authorization"]
        assert len(auth_values) == 1
        assert auth_values[0] == b"Bearer sk-ant-new"

    def test_missing_provider_key_returns_error(self) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"authorization", b"Bearer hr_test")]
        new_headers, err = inject_provider_key(
            headers, {"anthropic": "sk-ant-test"}, "openai"
        )
        assert err is not None
        assert err["error"] == "provider_key_not_configured"
        assert "openai" in err["message"]

    def test_empty_provider_keys_returns_error(self) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"authorization", b"Bearer hr_test")]
        new_headers, err = inject_provider_key(headers, {}, "anthropic")
        assert err is not None
        assert err["error"] == "provider_key_not_configured"

    def test_multiple_providers_in_keys(self) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"authorization", b"Bearer hr_test")]
        keys = {"anthropic": "sk-ant-1", "openai": "sk-proj-2", "gemini": "ai-gem-3"}
        new_headers, err = inject_provider_key(headers, keys, "openai")
        assert err is None
        auth_values = [v for k, v in new_headers if k.lower() == b"authorization"]
        assert auth_values == [b"Bearer sk-proj-2"]
