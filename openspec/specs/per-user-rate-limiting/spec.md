# per-user-rate-limiting

Token-bucket rate limiter keyed by `user_id` with limits inherited from the user's role, exposing standard `X-RateLimit-*` response headers.

## Purpose

Enforce per-user request and token rate limits so that one user's burst does not affect others. Each authenticated user gets independent RPM and TPM buckets with limits inherited from their role. Rate limit status is communicated via `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers. Exhausted limits return HTTP 429 with `Retry-After`.

## Requirements

### Requirement: Per-user_id rate limiting with token bucket
The system SHALL extend the existing `TokenBucketRateLimiter` to key buckets by `user_id`. Each authenticated user SHALL have independent RPM and TPM buckets, with limits inherited from their role.

#### Scenario: Two users have independent buckets
- **WHEN** user "joao" makes 60 requests in a minute (reaching their limit)
- **THEN** user "maria" can still make requests because her bucket is independent

#### Scenario: Rate limit inherited from role
- **WHEN** user "joao" is in role "developer" with `default_rpm=60` and `default_tpm=100000`
- **THEN** joao's rate limiter bucket is initialized with 60 RPM and 100k TPM

#### Scenario: Role without explicit limits uses defaults
- **WHEN** a role has no `default_rpm` or `default_tpm` set
- **THEN** the rate limiter uses the global defaults (60 RPM, 100k TPM)

### Requirement: Rate limit response headers
The system SHALL include rate limit information in every authenticated response via `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers.

#### Scenario: Rate limit headers in response
- **WHEN** an authenticated request is processed
- **THEN** the response includes `X-RateLimit-Limit: 60`
- **AND** `X-RateLimit-Remaining` indicates how many requests remain in the current window
- **AND** `X-RateLimit-Reset` indicates the Unix timestamp when the window resets

#### Scenario: Headers decrement on subsequent requests
- **WHEN** user "joao" makes first request of the minute
- **THEN** `X-RateLimit-Remaining` is 59
- **AND** the second request shows `X-RateLimit-Remaining: 58`

### Requirement: Rate limit exceeded returns 429
When a user exceeds their rate limit, the system SHALL return HTTP 429 with a `Retry-After` header and a JSON error body.

#### Scenario: Request rate limit exceeded
- **WHEN** user "joao" makes request #61 within the same minute (RPM limit is 60)
- **THEN** the system returns HTTP 429 with `Retry-After: <seconds>`
- **AND** the body is `{"error": "rate_limit_exceeded", "retry_after_seconds": <seconds>}`

#### Scenario: Token rate limit exceeded
- **WHEN** a request would push the user's token usage over their TPM limit
- **THEN** the system returns HTTP 429 with `Retry-After: <seconds>`

### Requirement: Rate limiter runs within auth middleware
The rate limit check SHALL be performed by the auth middleware after successful authentication and before provider key injection, using the `user_id` as the bucket key.

#### Scenario: Rate limit check after auth
- **WHEN** a request is successfully authenticated
- **THEN** the rate limiter checks the user's bucket before proceeding to provider key injection

#### Scenario: Unauthenticated requests skip rate limit
- **WHEN** a request fails authentication (401/403)
- **THEN** the rate limiter is not consulted

### Requirement: Role-level rate limit defaults
The base roles created by PRD 1 SHALL have the following default rate limits: admin (unlimited), team_lead (120 RPM, 200k TPM), developer (60 RPM, 100k TPM), viewer (20 RPM, 30k TPM).

#### Scenario: Admin has no rate limit
- **WHEN** an admin user makes requests
- **THEN** no rate limit is applied (RPM and TPM are effectively unlimited)

#### Scenario: Developer has standard limit
- **WHEN** a developer user makes requests
- **THEN** the rate limiter enforces 60 RPM and 100k TPM
