# Architecture

## Overview

**finsight** — insight-first personal finance.

```
Adapters (FinTS / Trade Republic / Binance / Trading 212 / Coinbase)
        → Sync job (per account, delta or history backfill)
        → Normalize (income / expense / transfer / asset trade)
        → Match and deduplicate (provider-aware, optional LLM scoring)
        → Categorize (keyword / regex rules, then local Ollama)
        → Embed transaction context (local Ollama, encrypted payload)
        → PostgreSQL (ciphertext + technical metadata/blind indexes)
        → FastAPI + worker
        → React dashboard and finance agent
```

## Components

- **Dev container** (`Dockerfile.dev` + `docker-compose-dev.yml`, project `finsight-dev`): Ubuntu with Python 3, Node 20 and the Postgres client. It mounts the repository and starts FastAPI plus Vite via `docker/dev-entrypoint.sh`. Only Vite is published on host port 5173; it proxies API and documentation requests internally.
- **Production images** (`docker-compose.yml`, project `finsight-prod`): `backend/Dockerfile` (FastAPI) and `frontend/Dockerfile` (Vite build + nginx with `/api` proxy). There are no source mounts. Only nginx is published on host port 80. PostgreSQL, FastAPI and the FinTS gateway communicate over the private Compose network.
- **PostgreSQL**: Source of truth for accounts, transactions, links, categories, sync state, jobs, portfolios and embeddings.
- **Job worker**: Async loop inside the FastAPI process; polls the `jobs` table (no Redis). Categorization and embedding jobs can run after sync and report progress to the UI.
- **LLM loop**: Separate asyncio loop; LangChain `create_agent` + `ChatOllama` categorizes uncategorized expense/income and powers the persistent finance chat. `OLLAMA_MODEL` and `OLLAMA_EMBEDDING_MODEL` provide the first-run defaults; onboarding and Settings persist the selected models as encrypted application preferences. Missing selected models are downloaded in the background. The loop reconnects every 10s if Ollama is down. Status is available through `GET /api/categorize/status` (the UI polls it). From Docker, `http://host.docker.internal:11434` reaches host Ollama. Automatic categorization research is an encrypted preference, while chat search is a per-request choice. Outbound queries are minimized and scrubbed before they reach the external search provider.
- **Sync progress**: Process-local status while FinTS waits for app approval (`GET /api/sync/progress`); UI shows a blocking modal until approved.
- **Vault**: The master password derives an Argon2id key that unwraps a random DEK. A separately generated 12-word BIP-39 phrase derives a domain-separated recovery key that wraps the same DEK; the words are never persisted. Password recovery therefore rewraps the DEK instead of re-encrypting financial rows. Personal and financial payloads are AES-GCM ciphertext. Technical metadata and keyed blind indexes remain queryable. The DEK exists only in RAM after unlock.
- **Adapters**: Each source implements the relevant account, transaction and/or portfolio read methods. Credentials come from unlocked vault connections (UI-configured under Accounts). FinTS discovery and all live, read-only FinTS dialogs run in the internal Spring Boot/HBCI4Java gateway. The FastAPI adapter submits short-lived jobs for account discovery, transactions and balances; credentials are kept in memory for the duration of a job and the gateway is not published on a host port. The FinTS product id is supplied locally through `FINTS_PRODUCT_ID`.

## Cashflow rules

- Transfers between owned accounts or brokers are `kind=transfer` and excluded
  from income/expense stats.

## Sync resilience

- Overlap window: `SYNC_OVERLAP_DAYS` (default 14). A delta sync re-fetches
  this trailing window to catch late or corrected bank bookings; upserts keep
  already imported transactions from being duplicated.
- Upsert key: `(account_id, external_id)`.
- Failed syncs store `last_error` on `sync_state`; next run retries with overlap.
- Categorize / match jobs are enqueued after sync and can run later.

## Domain tables

| Table | Purpose |
| --- | --- |
| `accounts` | Linked cash accounts per source |
| `transactions` | Normalized bookings |
| `transaction_links` | Dedup / funding pairs |
| `categories` / `category_rules` | Classification |
| `sync_state` | Per-account sync cursor/status |
| `jobs` | Background work queue |
| `portfolios`, `asset_trades`, `portfolio_value_points` | Broker positions, trades and historical values |
| `transaction_embeddings` | Encrypted local embeddings for semantic search |
| `inflation_indices` | Monthly German CPI observations and provenance |

## Later phases

More currencies and country-specific inflation series, recurring-payment
detection, anomaly alerts, stable broker history reconstruction, encrypted
backups and multi-user access.
