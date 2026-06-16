# auth-crypto

Criptografia simétrica (Fernet) para proteção de provider API keys em repouso no Neo4j.

## ADDED Requirements

### Requirement: Fernet encryption
The system SHALL use Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library to encrypt provider keys before storage. The encryption key SHALL be a 32-byte base64-encoded string read from the `HEADROOM_ENCRYPTION_KEY` environment variable.

#### Scenario: Encrypt a provider key
- **WHEN** `encrypt(plaintext, encryption_key)` is called with a valid Fernet key
- **THEN** the function returns a Fernet token (base64 string) that does NOT contain the plaintext
- **AND** the same plaintext encrypted twice produces different tokens (timestamp-based)

#### Scenario: Decrypt a provider key
- **WHEN** `decrypt(token, encryption_key)` is called with a valid token and the same key used for encryption
- **THEN** the function returns the original plaintext

#### Scenario: Decrypt with wrong key
- **WHEN** `decrypt(token, wrong_key)` is called with a different key than used for encryption
- **THEN** the function raises `cryptography.fernet.InvalidToken`
- **AND** the caller receives an error "HEADROOM_ENCRYPTION_KEY is invalid or has changed"

#### Scenario: Decrypt corrupted token
- **WHEN** `decrypt(corrupted_token, encryption_key)` is called with a token that has been modified
- **THEN** the function raises `cryptography.fernet.InvalidToken`

### Requirement: Key validation
The system SHALL validate the `HEADROOM_ENCRYPTION_KEY` format at startup and on first use. A valid key MUST be 32 bytes of urlsafe-base64-encoded data.

#### Scenario: Valid key
- **WHEN** `HEADROOM_ENCRYPTION_KEY` is set to a valid 32-byte base64 string
- **THEN** `validate_key()` returns successfully with no error

#### Scenario: Invalid key
- **WHEN** `HEADROOM_ENCRYPTION_KEY` is set to an invalid value (e.g., "not-a-key")
- **THEN** `validate_key()` returns an error message indicating the key is not a valid Fernet key
- **AND** the system exits with non-zero code when trying to encrypt or decrypt

#### Scenario: Key not set
- **WHEN** `HEADROOM_ENCRYPTION_KEY` environment variable is not set or empty
- **THEN** `validate_key()` returns an error "HEADROOM_ENCRYPTION_KEY is not set. Generate one with: headroom auth generate-key"

### Requirement: Provider keys JSON structure
The system SHALL store provider keys as a JSON object in the `provider_keys` property of the `:Role` node. Each key in the JSON object SHALL be the provider name, and each value SHALL be the Fernet-encrypted API key.

#### Scenario: Multiple providers per role
- **WHEN** admin stores keys for anthropic and openai for role "developer"
- **THEN** the `provider_keys` property contains `{"anthropic": "<enc1>", "openai": "<enc2>"}`
- **AND** each value decrypts independently with the same `HEADROOM_ENCRYPTION_KEY`

#### Scenario: Add provider to existing role
- **WHEN** admin sets a key for gemini on role "developer" that already has anthropic and openai
- **THEN** the existing anthropic and openai keys are preserved
- **AND** the gemini key is added to the JSON object

### Requirement: Secure input handling
The system SHALL accept provider API keys via interactive prompt (stdin with echo disabled) or piped stdin. Keys SHALL NEVER be accepted as command-line arguments.

#### Scenario: Interactive input
- **WHEN** admin runs `headroom auth set-provider-key developer anthropic`
- **THEN** the system prompts "Enter anthropic API key:" with echo disabled
- **AND** reads the key from stdin without displaying it on screen

#### Scenario: Piped input
- **WHEN** admin runs `echo "sk-ant-api03-xxx" | headroom auth set-provider-key developer anthropic --stdin`
- **THEN** the system reads the key from stdin without prompting
- **AND** the key never appears in the process list or shell history
