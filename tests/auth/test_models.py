"""Unit tests for auth data models."""

from datetime import datetime, timezone

from headroom.auth.models import ApiKey, Role, Team, User


class TestUser:
    """Task 5.1 — dataclass validation and defaults."""

    def test_user_auto_generates_user_id(self) -> None:
        user = User(username="joao", role="developer", team="backend")
        assert user.username == "joao"
        assert user.role == "developer"
        assert user.team == "backend"
        assert user.user_id.startswith("u_")
        assert len(user.user_id) == 14  # "u_" + 12 hex chars
        assert user.is_active is True
        assert isinstance(user.created_at, datetime)

    def test_user_respects_explicit_user_id(self) -> None:
        user = User(
            username="maria", role="team_lead", team="backend", user_id="u_custom"
        )
        assert user.user_id == "u_custom"

    def test_users_have_unique_ids(self) -> None:
        u1 = User(username="a", role="developer", team="x")
        u2 = User(username="b", role="developer", team="x")
        assert u1.user_id != u2.user_id


class TestRole:
    def test_role_defaults(self) -> None:
        role = Role(name="admin")
        assert role.name == "admin"
        assert role.description == ""
        assert role.provider_keys == {}
        assert role.default_rpm is None
        assert role.default_tpm is None

    def test_role_with_provider_keys(self) -> None:
        role = Role(name="developer", description="Dev role", provider_keys={"anthropic": "enc_xxx"})
        assert role.provider_keys["anthropic"] == "enc_xxx"


class TestTeam:
    def test_team_creation(self) -> None:
        team = Team(name="backend")
        assert team.name == "backend"
        assert isinstance(team.created_at, datetime)


class TestApiKey:
    """Task 5.1 — ApiKey dataclass."""

    def test_api_key_auto_generates_key_id(self) -> None:
        key = ApiKey(
            key_hash="abc123def456",
            key_prefix="hr_a7f3b9",
            user_id="u_testuser123",
        )
        assert key.key_id.startswith("k_")
        assert len(key.key_id) == 14  # "k_" + 12 hex chars
        assert key.key_hash == "abc123def456"
        assert key.key_prefix == "hr_a7f3b9"
        assert key.user_id == "u_testuser123"
        assert key.is_active is True
        assert isinstance(key.created_at, datetime)
        assert isinstance(key.expires_at, datetime)

    def test_api_key_default_expiry_is_90_days(self) -> None:
        key = ApiKey(key_hash="h", key_prefix="hr_x", user_id="u_x")
        delta = key.expires_at - key.created_at
        assert delta.days == 90

    def test_api_keys_have_unique_ids(self) -> None:
        k1 = ApiKey(key_hash="a", key_prefix="hr_a", user_id="u_1")
        k2 = ApiKey(key_hash="b", key_prefix="hr_b", user_id="u_2")
        assert k1.key_id != k2.key_id
