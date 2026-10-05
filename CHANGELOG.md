# Changelog

## Unreleased — first public MVP

- Local finance agent with transaction categorization, semantic search,
  calculations, charts and persistent chat.
- Read-only FinTS bank connections through the internal HBCI4Java gateway,
  plus Trade Republic, Binance, Trading 212 and Coinbase adapters.
- Cashflow, spending trends, investment positions and performance views.
- Encrypted financial payloads and embeddings in PostgreSQL.
- Mandatory first-run 12-word vault recovery with password-key rewrapping and
  phrase replacement while unlocked.
- Responsive English/German UI and presentation mode.
- First-run onboarding for local AI, optional web research, account setup and
  category review, including a custom Ollama model name and deferred downloads.
- Atomic vault creation, authenticated locking and ciphertext audits that also
  verify encrypted provider credentials.
- Private Docker networking: only the web frontend is published on the host;
  PostgreSQL, FastAPI and the FinTS gateway remain internal.
- A single Alembic baseline migration for the first public release.
- MIT license, contribution guide and security documentation.

Built with Codex and ChatGPT as an experiment in remote development from a
phone. The code has not been reviewed in detail. Bugs and incorrect results
are expected; this is an unaudited prototype, not a production-ready release.
