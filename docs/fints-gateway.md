# FinTS gateway

Finsight uses a private Spring Boot sidecar for all FinTS communication through
HBCI4Java. The Python backend uses it for bank discovery, account discovery,
balances and transaction history. There is no parallel `python-fints` runtime
or provider-specific FinTS implementation.

The gateway:

- is reachable only inside the Docker Compose network;
- has no host port;
- disables HBCI4Java InfoPoint communication;
- applies HBCI4Java's strongest log filter;
- keeps credentials only in an in-memory job for the duration of a request;
- validates bank endpoints before opening a connection;
- exposes read operations only and implements no payment or transfer jobs;
- removes completed jobs when the Python adapter has consumed the result.

The backend submits `ACCOUNTS`, `TRANSACTIONS` and `BALANCE` jobs to
`/v1/jobs`, polls their status while the user approves any decoupled TAN request,
then maps the result into Finsight's encrypted account and transaction model.
HBCI4Java's packaged bank directory is available through the separate internal
bank-search endpoint used by the connection form.

The dependency is pinned to `com.github.hbci4j:hbci4j-core:4.1.12`. HBCI4Java
is licensed under LGPL-2.1. See `THIRD_PARTY_NOTICES.md` before distributing a
prebuilt image. Finsight still needs its own registered FinTS product id for
live banking dialogs; a library or kernel registration must not be used as the
customer application's product id.
