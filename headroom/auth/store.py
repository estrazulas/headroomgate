"""Neo4j-backed persistence for multi-user auth (users, roles, teams, api keys).

Reuses the same ``GraphDatabase.driver`` pattern established by
``DirectMem0Adapter``. All Cypher operations use MERGE for idempotency.
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from headroom.auth.crypto import FernetCrypto, FernetCryptoError
from headroom.auth.models import ApiKey, Role, Team, User

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthStoreError(Exception):
    """Raised when a Neo4j operation fails in a recoverable way."""


class Neo4jAuthStore:
    """CRUD operations for :User, :Role, :Team, and :ApiKey nodes.

    Connection parameters are read from the standard Neo4j environment
    variables (``NEO4J_URI``, ``NEO4J_USER``, ``NEO4J_PASSWORD``) with
    sensible defaults matching ``docker-compose.yml``.

    Parameters:
        uri: Neo4j bolt URI (default ``NEO4J_URI`` or ``neo4j://localhost:7687``).
        user: Neo4j username (default ``NEO4J_USER`` or ``neo4j``).
        password: Neo4j password (default ``NEO4J_PASSWORD`` or empty).
    """

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._uri = uri or os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
        self._user = user or os.environ.get("NEO4J_USER", "neo4j")
        self._pwd = password or os.environ.get("NEO4J_PASSWORD", "")
        self._driver: Any = None

    # ------------------------------------------------------------------
    # connection lifecycle
    # ------------------------------------------------------------------

    def _get_driver(self) -> Any:
        """Return the cached Neo4j driver, creating it on first call."""
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self._uri, auth=(self._user, self._pwd)
            )
            return self._driver
        except ImportError:
            raise AuthStoreError(
                "Neo4j driver (neo4j package) is not installed. "
                "Install it with: pip install headroom-ai[auth]"
            ) from None
        except Exception as exc:
            raise AuthStoreError(
                f"Failed to connect to Neo4j at {self._uri} as {self._user}. "
                "Check NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD and ensure Neo4j is running."
            ) from exc

    def close(self) -> None:
        """Close the Neo4j driver, if open."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    @staticmethod
    def _to_python(value: Any) -> Any:
        """Convert Neo4j temporal types to standard Python types."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        # neo4j.time.DateTime → datetime
        if hasattr(value, "to_native"):
            return value.to_native()
        return value

    def _run(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a Cypher query and return the result records as dicts.

        Neo4j temporal types are converted to standard Python types.
        """
        driver = self._get_driver()
        with driver.session() as session:
            result = session.run(cypher, params or {})
            records: list[dict[str, Any]] = []
            for record in result:
                row: dict[str, Any] = {}
                for key, value in dict(record).items():
                    row[key] = self._to_python(value)
                records.append(row)
            return records

    # ------------------------------------------------------------------
    # database initialization
    # ------------------------------------------------------------------

    def init_db(self, force: bool = False) -> dict[str, Any]:
        """Initialize Neo4j constraints and base roles (idempotent).

        Returns a summary dict with counts of constraints created
        and roles created.
        """
        constraints = [
            ("User", "user_id"),
            ("User", "username"),
            ("Role", "name"),
            ("ApiKey", "key_hash"),
        ]
        constraint_count = 0
        for label, prop in constraints:
            cypher = (
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) "
                f"REQUIRE n.{prop} IS UNIQUE"
            )
            self._run(cypher)
            constraint_count += 1

        base_roles = [
            ("admin", "Full access — manages users, roles, providers"),
            ("team_lead", "Manages users in their team"),
            ("developer", "Uses the proxy with configured providers"),
            ("viewer", "Read-only access to own data (whoami, list-keys --self)"),
        ]
        role_count = 0
        for name, description in base_roles:
            result = self._run(
                """
                MERGE (r:Role {name: $name})
                ON CREATE SET r.description = $description, r.provider_keys = '{}'
                RETURN r.name AS name
                """,
                {"name": name, "description": description},
            )
            if result:
                role_count += 1

        return {
            "constraints_created": constraint_count,
            "roles_created": role_count,
        }

    # ------------------------------------------------------------------
    # user CRUD
    # ------------------------------------------------------------------

    def create_user(self, username: str, role: str, team: str) -> User:
        """Create a new user."""
        user = User(username=username, role=role, team=team)
        self._run(
            """
            MERGE (u:User {username: $username})
            ON CREATE SET
                u.user_id = $user_id,
                u.role = $role,
                u.team = $team,
                u.is_active = true,
                u.created_at = $created_at
            """,
            {
                "username": username,
                "user_id": user.user_id,
                "role": role,
                "team": team,
                "created_at": user.created_at,
            },
        )
        return user

    def get_user(self, username: str) -> User | None:
        """Look up a user by username."""
        records = self._run(
            """
            MATCH (u:User {username: $username})
            RETURN u.user_id AS user_id, u.username AS username,
                   u.role AS role, u.team AS team,
                   u.is_active AS is_active, u.created_at AS created_at
            """,
            {"username": username},
        )
        if not records:
            return None
        r = records[0]
        return User(
            user_id=r["user_id"],
            username=r["username"],
            role=r["role"],
            team=r["team"],
            is_active=r["is_active"],
            created_at=r["created_at"],
        )

    def list_users(self, team: str | None = None) -> list[dict[str, Any]]:
        """List all users, optionally filtered by team.

        Includes a count of active keys per user.
        """
        if team:
            cypher = """
                MATCH (u:User {team: $team})
                OPTIONAL MATCH (u)-[:OWNS_KEY]->(k:ApiKey)
                RETURN u.user_id AS user_id, u.username AS username,
                       u.role AS role, u.team AS team,
                       u.is_active AS is_active, u.created_at AS created_at,
                       COUNT(k) AS key_count
                ORDER BY u.username
                """
            params: dict[str, Any] = {"team": team}
        else:
            cypher = """
                MATCH (u:User)
                OPTIONAL MATCH (u)-[:OWNS_KEY]->(k:ApiKey)
                RETURN u.user_id AS user_id, u.username AS username,
                       u.role AS role, u.team AS team,
                       u.is_active AS is_active, u.created_at AS created_at,
                       COUNT(k) AS key_count
                ORDER BY u.username
                """
            params = {}
        return self._run(cypher, params)

    def update_user_status(self, username: str, is_active: bool) -> dict[str, Any] | None:
        """Set ``is_active`` on a user. Returns None if user not found."""
        user = self.get_user(username)
        if user is None:
            return None
        key_count = 0
        if not is_active:
            # Deactivate all keys owned by the user
            result = self._run(
                """
                MATCH (u:User {username: $username})-[:OWNS_KEY]->(k:ApiKey)
                SET k.is_active = false
                RETURN COUNT(k) AS key_count
                """,
                {"username": username},
            )
            key_count = result[0]["key_count"] if result else 0
        self._run(
            "MATCH (u:User {username: $username}) SET u.is_active = $is_active",
            {"username": username, "is_active": is_active},
        )
        return {"username": username, "role": user.role, "keys_revoked": key_count}

    def user_exists(self, username: str) -> bool:
        """Return True if a user with this username exists."""
        return self.get_user(username) is not None

    # ------------------------------------------------------------------
    # team CRUD
    # ------------------------------------------------------------------

    def create_team(self, name: str) -> Team:
        """Create a new team."""
        team = Team(name=name)
        self._run(
            """
            MERGE (t:Team {name: $name})
            ON CREATE SET t.created_at = $created_at
            """,
            {"name": name, "created_at": team.created_at},
        )
        return team

    def list_teams(self) -> list[dict[str, Any]]:
        """List all teams with member counts."""
        return self._run(
            """
            MATCH (t:Team)
            OPTIONAL MATCH (u:User {team: t.name})
            RETURN t.name AS name, COUNT(u) AS members,
                   COUNT(CASE WHEN u.is_active = true THEN 1 END) AS active_members
            ORDER BY t.name
            """
        )

    def add_user_to_team(self, username: str, team: str) -> None:
        """Set the team of a user."""
        self._run(
            "MATCH (u:User {username: $username}) SET u.team = $team",
            {"username": username, "team": team},
        )

    # ------------------------------------------------------------------
    # api key lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_key_token() -> str:
        """Generate a 256-bit random token with ``hr_`` prefix."""
        return "hr_" + secrets.token_hex(32)

    @staticmethod
    def _hash_key(key: str) -> str:
        """SHA-256 hex digest of a key string."""
        return hashlib.sha256(key.encode("ascii")).hexdigest()

    def create_key(
        self, username: str, ttl_days: int = 90
    ) -> tuple[str, ApiKey]:
        """Generate a new API key for a user.

        Returns ``(raw_key, api_key_model)``. The raw key is shown only
        once to the caller; only the hash is stored.
        """
        user = self.get_user(username)
        if user is None:
            raise AuthStoreError(f"User '{username}' not found.")

        raw_key = self._generate_key_token()
        key_hash = self._hash_key(raw_key)
        key_prefix = raw_key[:10]  # "hr_" + 8 chars

        api_key = ApiKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            user_id=user.user_id,
            expires_at=_utcnow() + timedelta(days=ttl_days),
        )

        self._run(
            """
            CREATE (k:ApiKey {
                key_id: $key_id,
                key_hash: $key_hash,
                key_prefix: $key_prefix,
                user_id: $user_id,
                is_active: true,
                created_at: $created_at,
                expires_at: $expires_at
            })
            WITH k
            MATCH (u:User {user_id: $user_id})
            CREATE (u)-[:OWNS_KEY]->(k)
            """,
            {
                "key_id": api_key.key_id,
                "key_hash": key_hash,
                "key_prefix": key_prefix,
                "user_id": user.user_id,
                "created_at": api_key.created_at,
                "expires_at": api_key.expires_at,
            },
        )
        return raw_key, api_key

    def list_keys(self, username: str | None = None) -> list[dict[str, Any]]:
        """List API keys, optionally filtered by owning user."""
        if username:
            cypher = """
                MATCH (u:User {username: $username})-[:OWNS_KEY]->(k:ApiKey)
                RETURN k.key_id AS key_id, k.key_prefix AS key_prefix,
                       k.user_id AS user_id, u.username AS username,
                       k.is_active AS is_active, k.expires_at AS expires_at,
                       k.created_at AS created_at
                ORDER BY k.created_at DESC
                """
            params: dict[str, Any] = {"username": username}
        else:
            cypher = """
                MATCH (u:User)-[:OWNS_KEY]->(k:ApiKey)
                RETURN k.key_id AS key_id, k.key_prefix AS key_prefix,
                       k.user_id AS user_id, u.username AS username,
                       k.is_active AS is_active, k.expires_at AS expires_at,
                       k.created_at AS created_at
                ORDER BY k.created_at DESC
                """
            params = {}
        return self._run(cypher, params)

    def revoke_key(self, key_id: str) -> dict[str, Any] | None:
        """Revoke a key by its key_id. Returns the key info or None."""
        records = self._run(
            """
            MATCH (k:ApiKey {key_id: $key_id})
            SET k.is_active = false
            RETURN k.key_prefix AS key_prefix, k.key_id AS key_id
            """,
            {"key_id": key_id},
        )
        return records[0] if records else None

    def get_key_owner(self, api_key: str) -> dict[str, Any] | None:
        """Resolve a proxy API key to its owner identity.

        Returns a dict with username, role, team, status, or None.
        """
        key_hash = self._hash_key(api_key)
        records = self._run(
            """
            MATCH (k:ApiKey {key_hash: $key_hash, is_active: true})
            WHERE k.expires_at IS NULL OR k.expires_at > datetime()
            MATCH (u:User {user_id: k.user_id})
            RETURN u.username AS username, u.role AS role,
                   u.team AS team, u.is_active AS status
            """,
            {"key_hash": key_hash},
        )
        if not records:
            return None
        r = records[0]
        return {
            "username": r["username"],
            "role": r["role"],
            "team": r["team"],
            "status": "active" if r["status"] else "deactivated",
        }

    # ------------------------------------------------------------------
    # provider key storage
    # ------------------------------------------------------------------

    def set_provider_key(self, role_name: str, provider: str, api_key: str) -> dict[str, Any]:
        """Encrypt and store a provider API key on a role node.

        If the provider already has a key, it is overwritten (rotation).
        """
        crypto = FernetCrypto()
        encrypted = crypto.encrypt(api_key)

        # Fetch existing provider_keys
        records = self._run(
            "MATCH (r:Role {name: $name}) RETURN r.provider_keys AS provider_keys",
            {"name": role_name},
        )
        if not records:
            raise AuthStoreError(
                f"Role '{role_name}' does not exist. Use 'list-roles' to see available roles."
            )

        raw = records[0].get("provider_keys") or "{}"
        try:
            import json

            keys: dict[str, str] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            keys = {}
        keys[provider] = encrypted

        self._run(
            "MATCH (r:Role {name: $name}) SET r.provider_keys = $provider_keys",
            {
                "name": role_name,
                "provider_keys": json.dumps(keys),
            },
        )
        return {"role": role_name, "provider": provider}

    def list_provider_keys(self, role_name: str) -> list[dict[str, str]]:
        """List which providers have keys configured for a role.

        Never returns the decrypted key values.
        """
        records = self._run(
            "MATCH (r:Role {name: $name}) RETURN r.provider_keys AS provider_keys",
            {"name": role_name},
        )
        if not records:
            return []
        raw = records[0].get("provider_keys") or "{}"
        try:
            import json

            keys: dict[str, str] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return [
            {"provider": provider, "status": "configured"}
            for provider in keys
        ]

    def get_provider_key(self, role_name: str, provider: str) -> str | None:
        """Decrypt and return a provider key for runtime use (PRD 2)."""
        records = self._run(
            "MATCH (r:Role {name: $name}) RETURN r.provider_keys AS provider_keys",
            {"name": role_name},
        )
        if not records:
            return None
        raw = records[0].get("provider_keys") or "{}"
        try:
            import json

            keys: dict[str, str] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        encrypted = keys.get(provider)
        if encrypted is None:
            return None
        crypto = FernetCrypto()
        return crypto.decrypt(encrypted)

    # ------------------------------------------------------------------
    # role management
    # ------------------------------------------------------------------

    def create_role(self, name: str, description: str = "") -> Role:
        """Create a custom role."""
        role = Role(name=name, description=description)
        self._run(
            """
            MERGE (r:Role {name: $name})
            ON CREATE SET r.description = $description, r.provider_keys = '{}'
            """,
            {"name": name, "description": description},
        )
        return role

    def list_roles(self) -> list[dict[str, str]]:
        """List all roles."""
        return self._run(
            """
            MATCH (r:Role)
            RETURN r.name AS name, r.description AS description
            ORDER BY r.name
            """
        )

    def role_exists(self, name: str) -> bool:
        """Return True if a role with this name exists."""
        records = self._run(
            "MATCH (r:Role {name: $name}) RETURN r.name AS name LIMIT 1",
            {"name": name},
        )
        return len(records) > 0

    def team_exists(self, name: str) -> bool:
        """Return True if a team with this name exists."""
        records = self._run(
            "MATCH (t:Team {name: $name}) RETURN t.name AS name LIMIT 1",
            {"name": name},
        )
        return len(records) > 0
