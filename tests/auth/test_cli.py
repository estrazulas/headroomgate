"""Integration tests for headroom auth CLI (tasks 5.4, 5.8).

Requires Neo4j to be running.
Uses Click's CliRunner for testing.
"""

import os
import re
import uuid

import pytest
from click.testing import CliRunner

from headroom.cli.auth import auth_group


def _uniq(prefix: str) -> str:
    """Make a test username unique per run."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _clear_env() -> None:
    """Ensure tests don't accidentally use a real encryption key."""
    os.environ.pop("HEADROOM_ENCRYPTION_KEY", None)


def _neo4j_available() -> bool:
    try:
        from neo4j import GraphDatabase

        uri = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
        driver = GraphDatabase.driver(
            uri,
            auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "")),
        )
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
class TestAuthCLI:
    """Task 5.4 — Click test runner for all subcommands."""

    def test_auth_help(self, runner: CliRunner) -> None:
        result = runner.invoke(auth_group, ["--help"])
        assert result.exit_code == 0
        assert "init-db" in result.output
        assert "create-user" in result.output
        assert "whoami" in result.output
        assert "generate-key" in result.output

    def test_generate_key(self, runner: CliRunner) -> None:
        result = runner.invoke(auth_group, ["generate-key"])
        assert result.exit_code == 0
        assert "HEADROOM_ENCRYPTION_KEY" in result.output

    def test_init_db(self, runner: CliRunner) -> None:
        result = runner.invoke(auth_group, ["init-db", "--yes"])
        assert result.exit_code == 0
        assert "Schema initialized" in result.output

    def test_init_db_idempotent(self, runner: CliRunner) -> None:
        """Task 5.5 — init-db idempotency via CLI."""
        result1 = runner.invoke(auth_group, ["init-db", "--yes"])
        result2 = runner.invoke(auth_group, ["init-db", "--yes"])
        assert result1.exit_code == 0
        assert result2.exit_code == 0

    def test_create_user(self, runner: CliRunner) -> None:
        name = _uniq("cli_user")
        result = runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend", "--json"],
        )
        assert result.exit_code == 0
        assert name in result.output

    def test_create_duplicate_user_error(self, runner: CliRunner) -> None:
        name = _uniq("dup")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        result = runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_list_users(self, runner: CliRunner) -> None:
        name = _uniq("list_u")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        result = runner.invoke(auth_group, ["list-users"])
        assert result.exit_code == 0
        assert name in result.output

    def test_list_users_json(self, runner: CliRunner) -> None:
        name = _uniq("json_u")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        result = runner.invoke(auth_group, ["list-users", "--json"])
        assert result.exit_code == 0
        import json

        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_revoke_and_reactivate_user(self, runner: CliRunner) -> None:
        name = _uniq("revoke")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        result = runner.invoke(auth_group, ["revoke-user", name])
        assert result.exit_code == 0
        assert "deactivated" in result.output

        result = runner.invoke(auth_group, ["reactivate-user", name])
        assert result.exit_code == 0
        assert "reactivated" in result.output

    def test_create_and_list_teams(self, runner: CliRunner) -> None:
        team = _uniq("team")
        runner.invoke(auth_group, ["create-team", team])
        result = runner.invoke(auth_group, ["list-teams"])
        assert team in result.output

    def test_create_key(self, runner: CliRunner) -> None:
        name = _uniq("key_u")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        result = runner.invoke(auth_group, ["create-key", name])
        assert result.exit_code == 0
        assert "hr_" in result.output

    def test_list_keys(self, runner: CliRunner) -> None:
        name = _uniq("lkey")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        runner.invoke(auth_group, ["create-key", name])
        result = runner.invoke(auth_group, ["list-keys", "--user", name])
        assert result.exit_code == 0
        assert "hr_" in result.output

    def test_revoke_key(self, runner: CliRunner) -> None:
        name = _uniq("rkey")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        runner.invoke(auth_group, ["create-key", name])
        list_result = runner.invoke(auth_group, ["list-keys", "--user", name, "--json"])
        import json

        keys = json.loads(list_result.output)
        assert len(keys) > 0
        key_id = keys[0]["key_id"]
        result = runner.invoke(auth_group, ["revoke-key", key_id])
        assert result.exit_code == 0
        assert "revoked" in result.output

    def test_set_provider_key(self, runner: CliRunner) -> None:
        from headroom.auth.crypto import FernetCrypto
        key = FernetCrypto.generate_key()
        os.environ["HEADROOM_ENCRYPTION_KEY"] = key
        try:
            result = runner.invoke(
                auth_group,
                ["set-provider-key", "developer", "test_provider", "--stdin"],
                input="sk-test-key-123",
            )
            assert result.exit_code == 0
            assert "stored" in result.output or "updated" in result.output
        finally:
            del os.environ["HEADROOM_ENCRYPTION_KEY"]

    def test_list_provider_keys(self, runner: CliRunner) -> None:
        result = runner.invoke(auth_group, ["list-provider-keys", "developer"])
        assert result.exit_code == 0

    def test_create_and_list_roles(self, runner: CliRunner) -> None:
        runner.invoke(auth_group, ["create-role", "cli_test_role", "--description", "CLI test"])
        result = runner.invoke(auth_group, ["list-roles"])
        assert "cli_test_role" in result.output

    def test_whoami(self, runner: CliRunner) -> None:
        name = _uniq("whoami_u")
        runner.invoke(
            auth_group,
            ["create-user", name, "--role", "developer", "--team", "backend"],
        )
        raw_result = runner.invoke(auth_group, ["create-key", name])
        # Extract the key from output (strip ANSI escape codes from Click styling)
        clean = re.sub(r'\x1b\[[0-9;]*m', '', raw_result.output)
        api_key = None
        for line in clean.split("\n"):
            stripped = line.strip()
            if stripped.startswith("hr_"):
                api_key = stripped
                break
        assert api_key is not None, f"Could not extract key from output: {raw_result.output}"
        result = runner.invoke(auth_group, ["whoami", "--stdin"], input=api_key)
        assert result.exit_code == 0
        assert name in result.output
        assert "developer" in result.output
        assert "backend" in result.output

    def test_whoami_invalid_key(self, runner: CliRunner) -> None:
        result = runner.invoke(auth_group, ["whoami", "--stdin"], input="hr_invalid_key")
        assert result.exit_code != 0

    def test_role_based_access_developer_cannot_create_user(self, runner: CliRunner) -> None:
        """Task 5.8 — role-based access: developer cannot create users."""
        dev_name = _uniq("dev")
        os.environ["HEADROOM_AUTH_USER"] = dev_name
        try:
            runner.invoke(
                auth_group,
                ["create-user", dev_name, "--role", "developer", "--team", "backend"],
            )
            result = runner.invoke(
                auth_group,
                ["create-user", _uniq("other"), "--role", "developer", "--team", "backend"],
            )
            assert result.exit_code != 0
            assert "Access denied" in result.output
        finally:
            del os.environ["HEADROOM_AUTH_USER"]

    def test_role_based_access_team_lead_cross_team(self, runner: CliRunner) -> None:
        """Task 5.8 — team_lead cannot manage other teams."""
        tl_name = _uniq("tl")
        os.environ["HEADROOM_AUTH_USER"] = tl_name
        try:
            runner.invoke(
                auth_group,
                ["create-user", tl_name, "--role", "team_lead", "--team", "backend"],
            )
            result = runner.invoke(
                auth_group,
                ["create-user", _uniq("frontend"), "--role", "developer", "--team", "frontend"],
            )
            assert result.exit_code != 0
            assert "Access denied" in result.output
        finally:
            del os.environ["HEADROOM_AUTH_USER"]
