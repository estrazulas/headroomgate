# Lessons Learned — E2E Testing (Playwright + Alpine.js)

## 1. Don't use Playwright `click()` on Alpine `x-show` elements

**What happened:** Buttons hidden by Alpine's `x-show` are in the DOM but have `display: none`. Playwright's `locator.click()` waits for the element to be "visible, enabled and stable" — it times out after 30 seconds because Alpine hasn't made the element visible yet (or the element is behind a transition).

**Root cause:** Alpine.js renders elements with `x-show="false"` as `style="display: none"`. Playwright's visibility check treats `display: none` as not visible. Even after Alpine evaluates `x-show="true"`, the CSS transition may delay `display` removal.

**Fix:** Use JavaScript-native clicks for Alpine-controlled buttons:

```python
# Instead of:
page.locator("button:has-text('Keys')").first.click()

# Use:
page.evaluate(
    "() => {"
    "  const btn = Array.from(document.querySelectorAll('button')).find("
    "    b => b.textContent.trim() === 'Keys' && b.offsetParent !== null"
    "  );"
    "  if (btn) btn.click();"
    "}"
)
```

Also, wait for the button to be in the visible DOM before clicking:

```python
page.wait_for_function(
    "Array.from(document.querySelectorAll('button')).some("
    "  b => b.textContent.includes('Keys') && b.offsetParent !== null"
    ")",
    timeout=5000,
)
```

**Rule:** For any Alpine.js `x-show` / `x-if` controlled element, use `page.evaluate()` with native `element.click()`. Reserve Playwright's `locator.click()` for static HTML elements.

---

## 2. Don't share login state across `browser.new_page()` calls

**What happened:** A `@pytest.fixture(autouse=True)` logged in on a page, then closed it with `page.close()`. The test created its own `browser.new_page()` — but each page has isolated cookies. The test page had no session.

**Root cause:** `browser.new_page()` creates independent browser contexts with no shared cookies or localStorage. A login performed in one page is invisible to another.

**Fix:** Use a per-test helper method instead of a fixture:

```python
def _login_admin(self, page: Page) -> None:
    """Log in as admin on the given page."""
    page.goto(f"{E2E_BASE_URL}/manage/login")
    page.fill("input[name='headroomgate_key']", E2E_API_KEY)
    page.click("button[type='submit']")
    expect(page).to_have_url(re.compile(r"/manage/users"))
```

Each test calls `self._login_admin(page)` on its own page.

**Rule:** Never assume sessions are shared between `browser.new_page()` calls. Log in on the exact page used in the test — use a helper method, not a fixture.
