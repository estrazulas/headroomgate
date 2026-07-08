# Lessons Learned — Frontend (Templates / Alpine.js)

## 1. Don't build templates against assumed API response shapes

**What happened:** The `roles.html` template was written before the actual API responses were inspected. The `list_roles()` endpoint didn't include `provider_count`, and `list_provider_keys()` returned objects instead of strings. Both required post-hoc fixes.

**Root cause:** The spec and design documents described the intended behavior but not the exact JSON wire format. The template code was written against the spec, not against real `fetch()` responses.

**Fix:** For every API endpoint the template consumes, run `fetch()` in the browser console or via curl and copy the exact response shape. Then write the template against that.

**Checklist before writing a template:**
1. `curl` or `fetch()` every API endpoint the page uses
2. Copy the actual JSON response into a comment at the top of the template
3. Match field names exactly — no guessing `provider_count` vs `providers.length`
4. Handle both array-of-strings and array-of-objects defensively

**Rule:** Templates should be written *after* confirming real API responses. Never assume field names from design docs — verify with real `fetch()` output.

---

## 2. Don't trust Alpine `x-for` with untyped data

**What happened:** `x-for="(status, provider) in providers"` iterated over an object `{anthropic: false, openai: false, gemini: false}`. This works fine, but when a bug caused `providers` to get a key `[object Object]`, Alpine silently rendered it, creating a broken UI row.

**Root cause:** No defensive check on the provider name before rendering. An unexpected key from the API response polluted the object and the template rendered it.

**Fix:** Initialize the providers object explicitly and validate keys:

```javascript
this.providers = { anthropic: false, openai: false, gemini: false };
configuredList.forEach(item => {
    const name = typeof item === 'string' ? item : item.provider;
    if (name in this.providers) {
        this.providers[name] = true;
    }
    // Unknown providers are silently ignored
});
```

**Rule:** When iterating over API-fed data in Alpine, validate keys against a known set or filter out unknowns before rendering.
