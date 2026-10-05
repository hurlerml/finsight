# API overview

Base URL (dev): `http://localhost:5173/api`

Interactive docs: `http://localhost:5173/docs`

The API is intentionally not published as a separate host port. Vite proxies it
inside the development container, and nginx does the same in production.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | Liveness |
| GET | `/api/accounts` | List accounts and balances |
| POST | `/api/accounts` | Create account manually (optional) |
| GET | `/api/accounts/{id}` | Account detail |
| GET | `/api/transactions` | List (`from`, `to`, `account_id`, `category_id`, `kind`) |
| PATCH | `/api/transactions/{id}` | Set category / kind (manual) |
| GET | `/api/categories` | List categories |
| GET | `/api/categories/impact` | Count current category assignments and uncategorized transactions |
| GET | `/api/categories/{id}/impact` | Count assignments affected by deleting one category |
| POST | `/api/categories` | Create a custom category for future categorizations |
| PATCH | `/api/categories/{id}` | Edit a custom category for future categorizations; system categories are read-only |
| DELETE | `/api/categories/{id}` | Delete a custom category and queue its affected transactions |
| GET | `/api/category-rules` | List rules |
| POST | `/api/category-rules` | Create rule |
| POST | `/api/sync` | Enqueue sync (`account_id`, `source` optional) |
| GET | `/api/sync/status` | Per-account sync status |
| GET | `/api/sync/progress` | Live sync progress / FinTS approval wait |
| GET | `/api/categorize/status` | LLM categorize progress / Ollama reachability |
| POST | `/api/categorize/reprocess` | Explicitly reevaluate categories, optionally scoped by account/current category |
| GET | `/api/llm/models` | Installed chat and embedding models from Ollama |
| POST | `/api/llm/models/setup` | Save the first-run chat model and queue missing configured models for installation |
| POST | `/api/llm/model` | Persist the active chat model without changing existing assignments |
| POST | `/api/llm/embedding-model` | Persist the active embedding model and rebuild encrypted vectors |
| POST | `/api/llm/models/pull` | Download an Ollama model with streamed NDJSON progress and select it |
| GET | `/api/onboarding` | Read encrypted first-run completion state |
| PUT | `/api/onboarding` | Complete or reopen first-run onboarding |
| GET | `/api/assets` | Portfolios, positions and accumulated performance |
| GET | `/api/assets/history` | Portfolio/instrument value history and break-even data |
| GET | `/api/inflation/germany` | Monthly German CPI series and provenance |
| GET | `/api/embeddings/point-cloud` | Decrypted embedding projection while the vault is unlocked |
| POST | `/api/embeddings/backfill` | Generate encrypted embeddings for transactions |
| GET | `/api/agent/conversations` | List encrypted chat histories |
| POST | `/api/agent/chat` | Send a non-streaming finance-agent request |
| POST | `/api/agent/chat/stream` | Stream a finance-agent response |
| GET | `/api/vault/encryption-status` | Verify private-data encryption coverage |
| GET | `/api/vault/encryption-audit` | Authenticate every private ciphertext, including provider credentials |
| POST | `/api/vault/lock` | Lock the vault; requires the active vault token |
| POST | `/api/vault/recover` | Reset the master password with the 12-word recovery phrase |
| POST | `/api/vault/recovery/confirm` | Verify a newly generated recovery phrase |
| POST | `/api/vault/recovery/regenerate` | Replace the recovery phrase while unlocked |
| GET | `/api/stats/summary` | Income / expense / category breakdown (`from`, `to`) |
| GET | `/api/stats/timeseries` | Trend buckets (`grain`, `group_by`, `from`, `to`) |
| GET | `/api/stats/flow` | Sankey nodes/links for a period |

Bank credentials are configured in the UI (vault). `OLLAMA_BASE_URL` comes from
`.env`; its model names provide the first-run defaults. The selected chat and
embedding models are then stored inside the encrypted vault, and onboarding
controls the first chat-model selection.
For a new vault, automatic installation starts only after the onboarding model
selection is confirmed. Existing installations request the configured models
after a successful unlock.

### LLM preferences

- `GET /api/llm/preferences` returns the active encrypted AI preferences.
- `PUT /api/llm/preferences/categorization-web-search` enables or disables
  automatic merchant research for background categorization. This does not
  change the chat request's independent `web_search_enabled` flag.
