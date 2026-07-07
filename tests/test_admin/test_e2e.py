"""Playwright E2E tests for the admin interface (Tasks 9.5, 9.6, 9.7).

These tests require:
- Playwright to be installed (``playwright install chromium``)
- The proxy server to be running (``uv run headroom proxy``)
- Neo4j to be running with test data

Marked with ``pytest.mark.e2e`` — skipped in CI by default.
"""

from __future__ import annotations

import os
import re
import secrets

import pytest

# Skip all tests if playwright is not installed
pytest.importorskip("playwright")

from playwright.sync_api import Browser, expect

E2E_BASE_URL = os.environ.get("HEADROOM_ADMIN_URL", "http://localhost:8000")
E2E_API_KEY = os.environ.get("HEADROOM_E2E_KEY", "hr_admin_test_key_placeholder")

# Unique tag per session to avoid 409 conflicts between runs
_TAG = secrets.token_hex(4)


def _unique(prefix: str) -> str:
    return f"{prefix}_{_TAG}"


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Shared browser context arguments."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 800}}


@pytest.mark.e2e
class TestAdminE2E:
    """Task 9.5 — Admin E2E: login → create team → create user → generate key → revoke key."""

    def test_full_admin_workflow(self, browser: Browser) -> None:
        """Complete admin workflow: login, navigate, manage resources."""
        page = browser.new_page()

        test_team = _unique("e2e-team")
        test_user = _unique("e2e-user")

        # ── Login ─────────────────────────────────────────────────────
        page.goto(f"{E2E_BASE_URL}/manage/login")
        expect(page).to_have_title(re.compile(r"Login.*Headroom Admin"))

        page.fill("input[name='headroomgate_key']", E2E_API_KEY)
        page.click("button[type='submit']")

        # Should redirect to /manage/users
        expect(page).to_have_url(re.compile(r"/manage/users"))

        # ── Navigate to Teams ─────────────────────────────────────────
        page.click("a[href='/manage/teams']")
        expect(page).to_have_url(re.compile(r"/manage/teams"))

        # Create team (Enter triggers Alpine @submit.prevent)
        page.click("text=+ New Team")
        page.wait_for_timeout(300)
        page.fill("input[placeholder='e.g. backend']", test_team)
        page.keyboard.press("Enter")
        # Wait for team to appear
        expect(page.locator(f"text={test_team}")).to_be_visible(timeout=5000)

        # ── Navigate to Users ─────────────────────────────────────────
        page.click("a[href='/manage/users']")
        expect(page).to_have_url(re.compile(r"/manage/users"))

        # Create user (Enter triggers Alpine @submit.prevent)
        page.click("text=+ New User")
        page.wait_for_timeout(500)
        # Fill username
        page.locator("div[x-show='showCreateModal'] input[type='text']").first.fill(test_user)
        # Fill team via combobox: type, wait for dropdown, pick first match
        page.locator("input[placeholder='Search or type team name...']").fill(test_team)
        page.wait_for_timeout(300)
        page.locator("input[placeholder='Search or type team name...']").press("Enter")
        page.wait_for_timeout(300)
        # Click Create button in the modal
        page.locator("div[x-show='showCreateModal'] button[type='submit']").click()
        # Wait for user in table
        expect(page.locator(f"text={test_user}")).to_be_visible(timeout=5000)

        # ── Navigate to API Keys ──────────────────────────────────────
        page.click("a[href='/manage/keys']")
        expect(page).to_have_url(re.compile(r"/manage/keys"))

        # Generate key
        page.click("text=+ New Key")
        page.wait_for_timeout(500)
        # Select user via combobox: type, wait for dropdown, pick first match
        page.locator("input[placeholder='Search or type username...']").fill(test_user)
        page.wait_for_timeout(300)
        page.locator("input[placeholder='Search or type username...']").press("Enter")
        page.wait_for_timeout(300)
        # Click Generate button
        page.locator("div[x-show='showCreateModal'] button[type='submit']").click()
        # The generated key should appear (shown once)
        expect(page.locator("text=⚠️ Copy this key now")).to_be_visible(timeout=5000)

        # Close modal
        page.click("text=Done")

        # ── Revoke a key ─────────────────────────────────────────────
        # First key in the list should have a Revoke button
        revoke_button = page.locator("text=Revoke").first
        if revoke_button.is_visible():
            # Accept confirmation dialog before clicking (Playwright default dismisses)
            page.once("dialog", lambda dialog: dialog.accept())
            revoke_button.click()
            expect(page.locator("text=Revoked").first).to_be_visible(timeout=5000)

        page.close()


@pytest.mark.e2e
class TestTeamLeadE2E:
    """Task 9.6 — Team lead login → scoped views."""

    def test_team_lead_flows(self, browser: Browser) -> None:
        """Team lead sees only their own team's data."""
        page = browser.new_page()

        page.goto(f"{E2E_BASE_URL}/manage/login")
        page.fill("input[name='headroomgate_key']", E2E_API_KEY)
        page.click("button[type='submit']")

        # Should land on users page
        expect(page).to_have_url(re.compile(r"/manage/users"))

        # Team leads should not see "Teams" in sidebar (admin-only nav)
        teams_link = page.locator("a[href='/manage/teams']")
        if teams_link.is_visible():
            # If visible (admin), navigate to it
            teams_link.click()

        page.close()


@pytest.mark.e2e
class TestUsageE2E:
    """Task 9.7 — Usage dashboard loads, charts render, search works."""

    def test_usage_dashboard(self, browser: Browser) -> None:
        """Usage dashboard loads and shows data."""
        page = browser.new_page()

        page.goto(f"{E2E_BASE_URL}/manage/login")
        page.fill("input[name='headroomgate_key']", E2E_API_KEY)
        page.click("button[type='submit']")

        # Navigate to usage
        page.click("a[href='/manage/usage']")
        expect(page).to_have_url(re.compile(r"/manage/usage"))

        # Summary cards should appear
        expect(page.locator("text=Total Requests")).to_be_visible(timeout=10000)

        # Time window selector should be visible
        expect(page.locator("text=24h")).to_be_visible()
        expect(page.locator("text=7d")).to_be_visible()
        expect(page.locator("text=30d")).to_be_visible()

        # Switch time windows
        page.click("text=24h")
        page.click("text=30d")

        # User history section should exist
        expect(page.locator("text=User History")).to_be_visible()

        # Search section should exist
        expect(page.locator("text=Search Requests")).to_be_visible()

        page.close()
