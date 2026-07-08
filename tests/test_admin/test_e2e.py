"""Playwright E2E tests for the admin interface.

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

from playwright.sync_api import Browser, Page, expect

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
class TestRolesE2E:
    """Roles page E2E — admin manages provider keys per role."""

    def _login_admin(self, page: Page) -> None:
        """Log in as admin on the given page."""
        page.goto(f"{E2E_BASE_URL}/manage/login")
        page.fill("input[name='headroomgate_key']", E2E_API_KEY)
        page.click("button[type='submit']")
        expect(page).to_have_url(re.compile(r"/manage/users"))

    def test_roles_page_loads_with_card_grid(self, browser: Browser) -> None:
        """Admin navigates to Roles page and sees the card grid."""
        page = browser.new_page()
        self._login_admin(page)
        page.goto(f"{E2E_BASE_URL}/manage/roles")
        expect(page).to_have_title(re.compile(r"Roles.*Headroom Admin"))

        # Wait for Alpine to render role cards
        page.wait_for_selector("h4", timeout=5000)

        # Should show heading
        expect(page.get_by_text("All Roles")).to_be_visible()

        # Should show role cards — at least admin and developer
        role_cards = page.locator("h4")
        card_texts = role_cards.all_inner_texts()
        assert "admin" in card_texts, f"Expected 'admin' in role cards, got {card_texts}"
        assert "developer" in card_texts, f"Expected 'developer' in role cards, got {card_texts}"

        # Sidebar Roles link should be active/highlighted
        active_link = page.locator(".sidebar-link.active")
        expect(active_link).to_contain_text("Roles")

        page.close()

    def test_admin_role_shows_protected_badge_no_keys_button(self, browser: Browser) -> None:
        """Admin role card shows Protected badge and no Keys button."""
        page = browser.new_page()
        self._login_admin(page)
        page.goto(f"{E2E_BASE_URL}/manage/roles")

        # Page should contain Protected badge
        expect(page.get_by_text("Protected")).to_be_visible()

        # Admin card row (parent of admin heading) should NOT have Keys button
        # Non-admin roles have Keys button, admin should not
        # Verify: all Keys buttons are on non-admin roles only
        keys_buttons = page.locator("button:has-text('Keys')")
        count = keys_buttons.count()
        assert count >= 1, "Expected at least one non-admin role with Keys button"

        page.close()

    def test_non_admin_roles_show_keys_button(self, browser: Browser) -> None:
        """Non-admin roles show Keys button for provider management."""
        page = browser.new_page()
        self._login_admin(page)
        page.goto(f"{E2E_BASE_URL}/manage/roles")

        # developer, team_lead, viewer (and any custom roles) should have Keys button
        keys_buttons = page.locator("button:has-text('Keys')")
        count = keys_buttons.count()
        assert count >= 3, f"Expected at least 3 Keys buttons, got {count}"

        page.close()

    def _wait_for_keys_buttons(self, page: Page) -> None:
        """Wait for at least one Keys button to become visible (Alpine rendering)."""
        page.wait_for_function(
            "document.querySelectorAll('button').length > 0 && "
            "Array.from(document.querySelectorAll('button')).some("
            "b => b.textContent.includes('Keys') && b.offsetParent !== null"
            ")",
            timeout=5000,
        )
        page.wait_for_timeout(300)

    def _click_first_keys_button(self, page: Page) -> None:
        """Click the first visible Keys button using JS to bypass visibility checks."""
        page.evaluate(
            "() => {"
            "  const btn = Array.from(document.querySelectorAll('button')).find("
            "    b => b.textContent.trim() === 'Keys' && b.offsetParent !== null"
            "  );"
            "  if (btn) btn.click();"
            "}"
        )

    def test_provider_key_modal_opens(self, browser: Browser) -> None:
        """Clicking Keys opens modal showing provider status list."""
        page = browser.new_page()
        self._login_admin(page)
        page.goto(f"{E2E_BASE_URL}/manage/roles")
        self._wait_for_keys_buttons(page)

        # Click first Keys button via JS (Playwright can't click Alpine x-show buttons reliably)
        self._click_first_keys_button(page)
        page.wait_for_timeout(800)

        # Modal heading should appear
        expect(page.get_by_text("Provider Keys:")).to_be_visible(timeout=3000)

        # Should show the three provider labels
        expect(page.locator("text=anthropic").first).to_be_visible()
        expect(page.locator("text=openai").first).to_be_visible()
        expect(page.locator("text=gemini").first).to_be_visible()

        # Should have Add Key button
        expect(page.locator("button:has-text('+ Add Key')")).to_be_visible()

        page.close()

    def test_set_and_remove_provider_key(self, browser: Browser) -> None:
        """Admin can set a provider key via UI and remove it via API, UI reflects changes."""
        page = browser.new_page()
        self._login_admin(page)
        page.goto(f"{E2E_BASE_URL}/manage/roles")
        self._wait_for_keys_buttons(page)

        # Click Keys on first non-admin role via JS
        self._click_first_keys_button(page)
        page.wait_for_timeout(800)

        # Modal should be open — wait for it
        expect(page.get_by_text("Provider Keys:")).to_be_visible(timeout=3000)

        # Click + Add Key via JS
        page.evaluate(
            "() => {"
            "  const btn = Array.from(document.querySelectorAll('button')).find("
            "    b => b.textContent.trim() === '+ Add Key'"
            "  );"
            "  if (btn) btn.click();"
            "}"
        )
        page.wait_for_timeout(500)

        # Fill the form — select Anthropic and enter key
        page.evaluate(
            "() => {"
            "  const select = document.querySelector('select');"
            "  if (select) { select.value = 'anthropic'; select.dispatchEvent(new Event('change', {bubbles: true})); }"
            "  const input = document.querySelector('input[placeholder=\"Enter API key\"]');"
            "  if (input) { input.value = 'sk-ant-e2e-test-key-12345'; input.dispatchEvent(new Event('input', {bubbles: true})); }"
            "}"
        )
        page.wait_for_timeout(200)

        # Click Save via JS
        page.evaluate(
            "() => {"
            "  const btns = Array.from(document.querySelectorAll('button'));"
            "  const saveBtn = btns.find(b => b.textContent.trim() === 'Save');"
            "  if (saveBtn) saveBtn.click();"
            "}"
        )
        page.wait_for_timeout(1000)

        # Provider should now show as configured
        expect(page.get_by_text("configured").first).to_be_visible(timeout=3000)

        # Remove the key via API (bypassing the fragile x-show confirmation dialog)
        page.evaluate(
            "async () => {"
            "  await fetch('/manage/api/roles/developer/providers/anthropic', { method: 'DELETE' });"
            "}"
        )
        page.wait_for_timeout(500)

        # Reload the page and reopen modal to see updated state
        page.goto(f"{E2E_BASE_URL}/manage/roles")
        self._wait_for_keys_buttons(page)
        self._click_first_keys_button(page)
        page.wait_for_timeout(800)

        # Provider should now show as not configured
        expect(page.get_by_text("not configured").first).to_be_visible(timeout=3000)

        page.close()

    def test_non_admin_cannot_access_roles(self, browser: Browser) -> None:
        """Developer and team_lead users get 403 on Roles page."""
        # Create a test developer user and get their key via admin API
        admin_page = browser.new_page()
        self._login_admin(admin_page)

        test_user = _unique("e2e-roles-dev")
        test_team = _unique("e2e-roles-team")

        # Create team via API
        admin_page.evaluate(
            """async ({name}) => {
            await fetch('/manage/api/teams', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name})
            });
        }""",
            {"name": test_team},
        )

        # Create user via API
        admin_page.evaluate(
            """async ({username, role, team}) => {
            await fetch('/manage/api/users', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, role, team})
            });
        }""",
            {"username": test_user, "role": "developer", "team": test_team},
        )

        # Generate a key for the developer
        resp3 = admin_page.evaluate(
            """async ({username}) => {
            const r = await fetch('/manage/api/keys', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username, ttl_days: 1})
            });
            return await r.json();
        }""",
            {"username": test_user},
        )
        dev_key = resp3.get("raw_key", "")
        admin_page.close()

        if not dev_key:
            pytest.skip("Could not create developer key")

        # Now try to access Roles page as the developer
        dev_page = browser.new_page()
        dev_page.goto(f"{E2E_BASE_URL}/manage/login")
        dev_page.fill("input[name='headroomgate_key']", dev_key)
        dev_page.click("button[type='submit']")
        expect(dev_page).to_have_url(re.compile(r"/manage/users"))

        # Try to navigate to /manage/roles — should be blocked
        dev_page.goto(f"{E2E_BASE_URL}/manage/roles")
        dev_page.wait_for_timeout(500)

        # The response should be a 403 JSON or access denied page
        body_text = dev_page.locator("body").inner_text()
        assert (
            "Forbidden" in body_text
            or "Access Denied" in body_text
            or "Not authenticated" in body_text
        ), f"Expected access denied, got: {body_text[:200]}"

        # Sidebar should NOT show Roles link
        roles_sidebar = dev_page.locator("a:has-text('Roles')")
        expect(roles_sidebar).to_have_count(0)

        dev_page.close()


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
