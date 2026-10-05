# Security

finsight is an unaudited, single-user prototype handling sensitive financial data.
Its author has not reviewed the code in detail. Encryption does not make it
safe to run on an untrusted machine or expose directly to the public internet.

## Reporting a vulnerability

Use GitHub's private **Report a vulnerability** option if enabled for this
repository. Otherwise, ask the maintainer for a private contact channel without
publishing exploit details or financial data in an issue.

Include the affected version, reproduction steps using synthetic data and the
expected impact. Never include passwords, API keys, account details or real
transaction logs. There is no guaranteed response time for this prototype.

## What is protected

- A master-password-derived Argon2id key wraps a random data encryption key.
- A locally generated 12-word BIP-39 phrase can independently unwrap that same
  data key. The phrase is shown once, must be kept offline and is never persisted
  by finsight.
- Credentials, personal financial payloads, chat and embeddings are stored as
  AES-GCM ciphertext in PostgreSQL.
- While the vault is unlocked, the backend decrypts data in memory for queries
  and passes relevant context to the configured local Ollama models.
- Technical metadata, relationships, status fields and keyed blind indexes
  are not encrypted financial payloads. Public inflation data is also stored openly.

Locking the vault, session expiry or a backend restart removes access to the
active key through the application. This does not guarantee immediate erasure
of every copy from RAM, swap, core dumps or other processes. An attacker with
control of an unlocked host can read data. Use disk encryption and protect
backups and access to the host.

## External requests and diagnostics

Bank synchronization contacts the selected financial providers. Optional web
search sends minimized merchant queries externally. Automatic categorization
research can be disabled under **Settings**; chat search is controlled
separately for each request. The backend removes amounts and dates from automatic
categorization queries, filters common card descriptors and sensitive identifier
patterns, and skips searches for bank transfers and incoming payments. Chat
queries receive the identifier filtering but may still contain arbitrary text or
names produced by the local model. These measures reduce exposure but do not
guarantee anonymity. Disable the corresponding search control for sensitive data.
Configure Ollama on a machine you trust; a remote Ollama endpoint receives the
model context. UI fonts are bundled with the frontend and require no font-CDN
request at runtime.

Keep `DEBUG_LLM` disabled with real data: diagnostic output may contain sensitive
transaction context. Presentation mode only changes displayed numbers; booking
text and historical chats remain readable. Trade Republic uses an unofficial
protocol adapter that may break when the provider changes it.
