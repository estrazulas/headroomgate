## ADDED Requirements

### Requirement: In-memory validation cache with TTL
The system SHALL maintain an in-memory cache of validation results keyed by the SHA-256 hash of the proxy key. Each cache entry SHALL expire after a configurable TTL (default 10 seconds).

#### Scenario: Cache hit
- **WHEN** a request arrives with a key that was validated within the last 10 seconds
- **THEN** the cached result (user_id, username, role, provider_keys, rpm, tpm) is used
- **AND** Neo4j is not queried

#### Scenario: Cache miss
- **WHEN** a request arrives with a key not present in the cache or whose entry has expired
- **THEN** Neo4j is queried via `Neo4jAuthStore.get_key_owner()`
- **AND** the result is stored in the cache with a new TTL

#### Scenario: Cache entry is a complete validation result
- **WHEN** a key is validated and cached
- **THEN** the cache entry contains `user_id`, `username`, `role`, `team`, `provider_keys` (decrypted), `rpm`, `tpm`, and `expires_at`
- **AND** provider keys are decrypted once at cache time, not on every request

### Requirement: Cache TTL is configurable
The cache TTL SHALL be configurable via the `HEADROOM_AUTH_CACHE_TTL` environment variable (integer, in seconds). The default value SHALL be 10 seconds.

#### Scenario: Custom TTL
- **WHEN** the proxy starts with `HEADROOM_AUTH_CACHE_TTL=30`
- **THEN** cache entries expire after 30 seconds

#### Scenario: Default TTL
- **WHEN** `HEADROOM_AUTH_CACHE_TTL` is not set
- **THEN** the cache uses a TTL of 10 seconds

### Requirement: Stale cache fallback when Neo4j is unreachable
When Neo4j is unreachable and a cache entry has expired, the system SHALL serve the stale (expired) entry and log a warning. If no cache entry exists at all (first request after startup), the system SHALL return a 503 error.

#### Scenario: Neo4j down, stale cache available
- **WHEN** Neo4j is unreachable and a cache entry for the key exists (expired but present)
- **THEN** the stale entry is served
- **AND** a warning log is emitted: "auth-cache: Neo4j unreachable, serving stale cache for user <username>"

#### Scenario: Neo4j down, no cache entry
- **WHEN** Neo4j is unreachable and no cache entry exists for the key (first request after startup)
- **THEN** the system returns HTTP 503 with `{"error": "auth_service_unavailable", "message": "Authentication service is temporarily unavailable"}`

#### Scenario: Neo4j recovers
- **WHEN** Neo4j becomes reachable again after being down
- **THEN** the next cache miss refreshes from Neo4j normally
- **AND** no stale entries are served

### Requirement: Cache cleanup of expired entries
The system SHALL periodically remove expired cache entries to prevent unbounded memory growth. Entries older than 5 minutes (since last access) SHALL be evicted.

#### Scenario: Stale entry eviction
- **WHEN** a cache entry has not been accessed for more than 5 minutes
- **THEN** it is removed from the cache during the next cleanup cycle

#### Scenario: Active entries are retained
- **WHEN** a cache entry is accessed frequently (every few seconds)
- **THEN** it is not evicted even if it was first created hours ago

### Requirement: Cache uses SHA-256 hash as lookup key
The cache SHALL use the SHA-256 hex digest of the raw proxy key as the lookup key, matching the hash stored in Neo4j's `ApiKey.key_hash` property.

#### Scenario: Cache lookup
- **WHEN** the middleware needs to look up a key `hr_a7f3b9c2d1e5...`
- **THEN** it computes `SHA-256("hr_a7f3b9c2d1e5...")` and uses the hex digest as the cache key
- **AND** the same hash matches the `key_hash` stored in Neo4j
