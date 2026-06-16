## ADDED Requirements

### Requirement: Provider resolution by request path
The system SHALL determine the upstream LLM provider from the request path using a static mapping. The mapping SHALL cover all standard headroom proxy routes.

#### Scenario: Anthropic path resolution
- **WHEN** a request arrives at `POST /v1/messages`
- **THEN** the provider is resolved as `"anthropic"`

#### Scenario: OpenAI path resolution
- **WHEN** a request arrives at `POST /v1/chat/completions`
- **THEN** the provider is resolved as `"openai"`

#### Scenario: Gemini path resolution
- **WHEN** a request arrives at `POST /v1beta/models/gemini-2.5-flash:generateContent`
- **THEN** the provider is resolved as `"gemini"`

#### Scenario: CloudCode path resolution
- **WHEN** a request arrives at `POST /v1internal/generate`
- **THEN** the provider is resolved as `"cloudcode"`

#### Scenario: Unknown path falls through
- **WHEN** a request arrives at a path not matching any known provider
- **THEN** the provider is resolved as `None` and the original request proceeds without key injection

### Requirement: Provider key decryption and injection
When a provider is resolved, the system SHALL look up the encrypted provider key from the role's `provider_keys` dict, decrypt it using `FernetCrypto`, and replace the `Authorization` header with the real provider key.

#### Scenario: Anthropic key injection
- **WHEN** an authenticated request arrives at `POST /v1/messages` and the user's role has an encrypted anthropic key
- **THEN** the `Authorization` header is replaced from `Bearer hr_...` to `Bearer sk-ant-api03-...`
- **AND** the decrypted key is the real Anthropic API key

#### Scenario: OpenAI key injection
- **WHEN** an authenticated request arrives at `POST /v1/chat/completions` and the user's role has an encrypted openai key
- **THEN** the `Authorization` header is replaced from `Bearer hr_...` to `Bearer sk-proj-...`

#### Scenario: Provider key not configured
- **WHEN** an authenticated request arrives at `POST /v1/messages` but the user's role has no anthropic key configured
- **THEN** the middleware returns HTTP 502 with `{"error": "provider_key_not_configured", "message": "No API key configured for provider 'anthropic' in your role"}`

#### Scenario: Decryption fails due to wrong encryption key
- **WHEN** the `HEADROOM_ENCRYPTION_KEY` is different from the key used to encrypt provider keys
- **THEN** the middleware returns HTTP 502 with `{"error": "provider_key_decryption_failed", "message": "Failed to decrypt provider key — HEADROOM_ENCRYPTION_KEY may have changed"}`

### Requirement: Provider key resolution reuses FernetCrypto from PRD 1
The provider key decryption SHALL use the `FernetCrypto` class from `headroom.auth.crypto`, reading the encryption key from the `HEADROOM_ENCRYPTION_KEY` environment variable.

#### Scenario: FernetCrypto decryption
- **WHEN** the system needs to decrypt a provider API key
- **THEN** it calls `FernetCrypto().decrypt(encrypted_token)` using the instance configured with `HEADROOM_ENCRYPTION_KEY`
