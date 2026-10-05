# Adapters

Credentials are configured under **Accounts** after unlocking the vault with
your master password. They are stored encrypted in PostgreSQL and only decrypted
in process memory while unlocked.

Empty / missing connections skip that adapter.

## Sync windows

- **Delta sync** (default): from the latest booking date in the database minus
  an overlap (`SYNC_OVERLAP_DAYS`, default 14). The trailing window catches
  delayed or corrected bookings; transaction upserts prevent duplicates.
- **History backfill** (Accounts → Advanced): set “History back to” and **Load history**. finsight fetches the full range in **one** request (no monthly chunks). Regular **Refresh** auto-chooses full history (empty account) or delta.
- First sync on an empty account also backfills from `history_from`.

## Vault

1. First visit: set a master password (min. 8 characters), then write down and
   confirm the one-time 12-word recovery phrase
2. Unlock on each app/API restart (or after idle timeout)
3. Add connections under **Accounts**
4. Sync only works while unlocked

The master password and recovery words never live in the database. PostgreSQL
contains salts, two independently wrapped copies of the same data-encryption key
(DEK), and AES-GCM ciphertext. Resetting a forgotten password with the recovery
phrase only rewraps that DEK; it does not re-encrypt the financial records.

## FinTS banks

The connection form searches HBCI4Java's local bank directory by bank name or
BLZ and fills the bank code, BIC and PIN/TAN endpoint automatically. Accounts,
balances and transactions are retrieved by the same read-only HBCI4Java Spring
service. The service is private to the Docker network; credentials are sent to
it only for the duration of a synchronization job and are not persisted there.

The directory covers many Sparkassen, Volksbanken/Raiffeisenbanken and other
German banks, but a directory entry does not guarantee that every account type
or authentication method is supported. Banks without FinTS, such as app-only
providers, need a separate adapter.

Every imported account stores the owning connection id. Multiple bank logins of the same type therefore remain unambiguous during refresh and deletion.

### FinTS fields

| Field | Description |
| --- | --- |
| IBAN | Used to derive the BLZ and select the requested bank product |
| User | The bank's FinTS user id — for VR/Geno often **VR-NetKey** or alias |
| PIN | Onlinebanking PIN |
| Customer ID | Optional separate customer identifier when required by the bank |
| TAN medium | Optional display name of the TAN device or app |

The application product id, selected endpoint and internal account selection
are not exposed as user-facing fields.

FinTS requires an application product id. Configure your own registered id as
`FINTS_PRODUCT_ID` in the local, gitignored `.env` file. finsight deliberately
ships **no fallback or third-party product id**. (A legacy `product_id` value in
an encrypted connection is still honored.) Missing/invalid IDs can lead to
`Could not find system_id`.

A shared product ID registered specifically for finsight is planned but has not
yet been issued. Until then, every user who enables a FinTS connection must
register and configure their own product ID.

Registration can take days/weeks for your own ID. **Decoupled app approval**
is polled while you approve in the banking app. Typed TAN, flicker, photo and
QR input are not in the UI yet. Checking and credit-card products are mapped
to separate accounts when the bank exposes a recognizable account type. The
gateway does not expose payment, transfer or debit operations.

## Trade Republic (unofficial)

> [!CAUTION]
> This is an unofficial integration of Trade Republic's undocumented web
> protocol. It is not provided, endorsed or supported by Trade Republic and can
> stop working whenever the provider changes its login or internal protocol.

| Field | Description |
| --- | --- |
| Phone | Phone number used for login |
| PIN | PIN |

There is no official consumer API. finsight implements the current web protocol
directly without importing a Trade Republic client library at runtime. Protocol
behavior, endpoint discovery and parsing approaches were informed by the
MIT-licensed [`pytr`](https://github.com/pytr-org/pytr) project. The adapter was
adapted to finsight's encrypted storage, account model and read-only sync flow;
it should not be presented as having been reverse-engineered entirely from
scratch. See the [third-party notices](../THIRD_PARTY_NOTICES.md) and the
included [`pytr` license](licenses/pytr-MIT.txt).

The integration currently provides:

- AWS WAF challenge in an isolated Chromium runtime
- v2 login with push approval in the Trade Republic app
- encrypted persistence of session cookies and the stable device identifier
- read-only protocol-31 WebSocket access to `timelineTransactions`

The first login (and a login after session expiry) opens an approval prompt in the
Trade Republic app. Valid sessions are reused from the encrypted vault. Sync reads
cash transactions, investment positions and the available portfolio history.
Provider context is retained inside encrypted payloads. Some older execution
details may be unavailable, which limits historical reconstruction.

## Binance

Create a read-only API key and enter the key and secret in the connection form.
Do not enable trading or withdrawals. The adapter imports balances, spot trades
and the supported account-history endpoints, then reconstructs position costs
and performance. Missing transfers, conversions or prices can affect those
calculations; imported values should be checked against the provider.

## Trading 212

Trading 212 is connected through its official Public API. Create an API key and
secret for your real account and enter both in the connection form. Finsight
connects only to Trading 212's live API and calls account, position and
historical read endpoints; it implements no order endpoint.

The Public API is currently beta, supports Invest and Stocks ISA accounts, and
does not expose multi-currency accounts. The adapter imports the current cash
balance, cash movements, open positions, provider cost basis and executed order
history. Trading 212 currently exposes no historical market-price series through
this API, so Finsight can show the exact current position performance while the
historical chart grows from future synchronized snapshots and available fills.

| Field | Description |
| --- | --- |
| API key | Trading 212 API key |
| API secret | Matching Trading 212 secret |

## Coinbase

Coinbase is connected through the official Advanced Trade REST API using
`httpx` and Coinbase's documented CDP JWT authentication flow. Create a CDP API
key with **view** permission and the **ECDSA** signature algorithm, then paste
the complete key name and private key into the connection form. Finsight calls
account, portfolio-breakdown, fill and public candle endpoints only. A fresh,
request-specific JWT is generated locally and expires after two minutes.

Current holdings and their cost basis come directly from Coinbase's portfolio
breakdown in EUR. Historical reconstruction currently imports EUR-quoted spot
fills and EUR candle series. Fills quoted in another currency are deliberately
not treated as EUR; in that case the current position remains accurate but the
historical performance series can be incomplete until currency conversion is
implemented.

| Field | Description |
| --- | --- |
| CDP API key name | Full key name, for example `organizations/.../apiKeys/...` |
| CDP private key | Complete private key including its BEGIN/END lines |
