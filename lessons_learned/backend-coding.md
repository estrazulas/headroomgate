# Lessons Learned — Backend / Coding

## 1. Don't assume store methods return what the UI needs

**What happened:** `list_roles()` returned `[{name, description}]` without `provider_count`. The template referenced `r.provider_count` which was `undefined` — the UI showed "No providers" silently.

**Root cause:** The store method was designed for CLI usage, not the admin UI. The API endpoint passed the raw return value straight through.

**Fix:** Enrich the response in the API endpoint (`api_list_roles`), not in the template or client-side:

```python
for role in roles:
    keys = store.list_provider_keys(role["name"])
    role["provider_count"] = len(keys)
```

**Rule:** Before building a template, inspect the actual JSON response from the API endpoint. Don't assume fields exist — they might not.

---

## 2. Don't assume API response shape — inspect it

**What happened:** `list_provider_keys()` returns `[{provider: "anthropic", status: "configured"}, ...]` (array of objects), but the JavaScript assumed an array of strings `["anthropic", ...]`. The loop `configured.forEach(p => providers[p] = true)` set `providers["[object Object]"] = true`.

**Root cause:** The API response format from `list_provider_keys` was enriched with status objects, but the client code was written against a simplified mental model.

**Fix:** Handle both formats defensively:

```javascript
configuredList.forEach(item => {
    const name = typeof item === 'string' ? item : item.provider;
    providers[name] = true;
});
```

**Rule:** Always `fetch()` the API endpoint and inspect the real JSON shape before writing template code against it.

---

## 3. Don't add validation gates without checking legacy data

**What happened:** The `_ALLOWED_PROVIDERS = frozenset({"anthropic", "openai", "gemini"})` validation in the DELETE endpoint blocked removal of a `test_provider` key that was created earlier via CLI. The API returned 400, and the UI showed an error toast.

**Root cause:** New validation was applied to existing data. The `test_provider` key was in Neo4j from before the validation existed.

**Fix:** The validation is correct for production (only the 3 providers are valid), but the lesson is to check for legacy data before adding gates. A migration or cleanup step may be needed.

**Rule:** Before adding validation on mutation endpoints, check if existing data could violate the new rules. If so, either relax the validation or provide a migration path.

---

## 4. Don't test Python changes without rebuild (when using pipx)

**What happened:** After editing `router.py`, the changes weren't picked up because the proxy runs from the pipx-installed wheel (`~/.local/pipx/venvs/headroom-ai/`), not from the source directory. Two rebuild cycles were wasted.

**Root cause:** Pipx installs a compiled wheel into an isolated venv. Source edits don't propagate automatically — unlike Jinja2 templates which load from disk.

**Fix:** After any Python source change:

```bash
source "$HOME/.cargo/env"
rm -rf dist/
maturin build --release --out dist/
WHEEL=$(ls dist/headroom_ai-*.whl | head -1)
pipx install --force "${WHEEL}[proxy,code,mcp,auth]"
systemctl --user restart headroom.service
```

Alternatively, for rapid iteration, run `uv run headroom proxy` directly from source instead of via pipx.

**Rule:** After editing `.py` files, rebuild and reinstall. Templates auto-update; Python doesn't.
