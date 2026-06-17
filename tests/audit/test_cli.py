"""Tests for audit CLI commands (PRD 3 tasks 6.1-6.8).

CLI tests use Click's CliRunner. Neo4j-dependent commands are skipped.
"""

import os
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner


def _neo4j_available() -> bool:
    uri = os.environ.get("NEO4J_URI", "neo4j://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception:
        return False


class TestAuditCLIBasic:
    """Tests that don't need Neo4j."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_audit_group_help(self, runner: CliRunner) -> None:
        from headroom.cli.audit import audit_group
        result = runner.invoke(audit_group, ["--help"])
        assert result.exit_code == 0
        assert "user" in result.output
        assert "team" in result.output
        assert "top" in result.output
        assert "summary" in result.output
        assert "search" in result.output
        assert "purge" in result.output

    def test_duration_parser_valid(self) -> None:
        from headroom.cli.audit import _parse_duration
        assert _parse_duration("24h") is not None
        assert _parse_duration("7d") is not None
        assert _parse_duration("2w") is not None
        assert _parse_duration("3m") is not None

    def test_duration_parser_invalid(self) -> None:
        from headroom.cli.audit import _parse_duration
        import click
        with pytest.raises(click.BadParameter, match="Invalid duration"):
            _parse_duration("foo")

    @pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
    def test_audit_user_self(self, runner: CliRunner) -> None:
        from headroom.cli.audit import audit_user
        os.environ["HEADROOM_API_KEY"] = "hr_invalid_key_for_test"
        result = runner.invoke(audit_user, ["--self", "--last", "24h"])
        # Will fail identity resolution but the command parses correctly
        assert "could not resolve" in result.output.lower() or result.exit_code == 0

    @pytest.mark.skipif(not _neo4j_available(), reason="Neo4j not available")
    def test_audit_summary(self, runner: CliRunner) -> None:
        from headroom.cli.audit import audit_summary
        os.environ["HEADROOM_API_KEY"] = "hr_invalid_key_for_test"
        result = runner.invoke(audit_summary, ["--last", "24h"])
        assert "could not resolve" in result.output.lower() or result.exit_code == 0
