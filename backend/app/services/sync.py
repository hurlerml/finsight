"""Orchestrate account sync: fetch → upsert → enqueue match/categorize."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, or_
from sqlmodel import Session, select

from app.adapters import build_registry
from app.adapters.base import RawAccount, RawBalance, RawPortfolio, RawTransaction
from app.config import get_settings
from app.models import (
    Account,
    AccountBalanceSnapshot,
    AssetPositionSnapshot,
    AssetPricePoint,
    AssetTrade,
    Connection,
    Job,
    Portfolio,
    PortfolioValuePoint,
    SyncState,
    Transaction,
)
from app.models.enums import AccountSource, AccountType, JobStatus, JobType, SyncStatus, TransactionKind
from app.services.normalize import infer_kind
from app.services.secure_accounts import (
    decode_account,
    find_account_by_external_id,
    insert_account_payload,
    insert_balance_payload,
    update_account_payload,
)
from app.services.secure_portfolios import (
    decode_portfolio,
    decode_position,
    decode_trade,
    find_portfolio_by_external_id,
    find_trade_by_external_id,
    insert_portfolio_payload,
    insert_portfolio_value_payload,
    insert_position_payload,
    update_portfolio_payload,
    upsert_trade_payload,
)
from app.services.secure_data import transaction_external_id_index
from app.services.secure_transactions import (
    decode_transaction,
    insert_transaction_payload,
    load_transactions,
    update_transaction_payload,
)
from app.services.secure_runtime import (
    decode_job,
    decode_sync_state,
    get_or_create_sync_state,
    insert_job_payload,
    update_job_payload,
    update_sync_state_payload,
)
from app.services.connections import set_connection_last_error
from app.services.sync_progress import clear_sync_progress, set_sync_progress
from app.services.transaction_titles import fints_card_transaction_title
from app.services.vault_session import vault_session

logger = logging.getLogger(__name__)


def default_history_from(today: date | None = None) -> date:
    """Default initial backfill target: Jan 1 of the current year."""
    today = today or date.today()
    return date(today.year, 1, 1)


def enqueue_sync(
    session: Session,
    account_id: int | None = None,
    connection_id: int | None = None,
    source: str | None = None,
    *,
    mode: str = "sync",
    history_from: date | None = None,
) -> list[int]:
    """Create connection-scoped pending sync jobs and return their IDs.

    mode=sync: smart refresh (full history if empty, else delta).
    mode=backfill: force full fetch from history_from → today (one shot).

    A request without an account or connection selector fans out to one job per
    existing account. Enabled connections without an imported account get one
    connection-scoped discovery job. This keeps progress attributable to each
    account instead of making one global job mark every account busy until the
    entire refresh has finished.
    """
    dek = vault_session.get_dek()
    if dek is None:
        return []

    target_account_ids: list[int] = []
    orphan_connection_ids: list[int] = []
    if account_id is None and connection_id is None:
        query = select(Connection.id)
        if source:
            try:
                query = query.where(Connection.source == AccountSource(source))
            except ValueError:
                return []
        connection_ids = [
            int(value) for value in session.exec(query.order_by(Connection.id)).all()
        ]
        if not connection_ids:
            return []
        account_rows = session.exec(
            select(Account)
            .where(Account.is_active == True)  # noqa: E712
            .where(Account.connection_id.in_(connection_ids))
            .order_by(Account.id)
        ).all()
        target_account_ids = [
            int(account.id) for account in account_rows if account.id is not None
        ]
        connections_with_accounts = {
            int(account.connection_id)
            for account in account_rows
            if account.connection_id is not None
        }
        orphan_connection_ids = [
            value
            for value in connection_ids
            if value not in connections_with_accounts
        ]

    payloads: list[dict] = []
    if target_account_ids or orphan_connection_ids:
        for target_account_id in target_account_ids:
            payload: dict = {
                "mode": mode,
                "account_id": target_account_id,
            }
            if history_from is not None:
                payload["history_from"] = history_from.isoformat()
            payloads.append(payload)
        for target_connection_id in orphan_connection_ids:
            payload: dict = {
                "mode": mode,
                "connection_id": target_connection_id,
            }
            if history_from is not None:
                payload["history_from"] = history_from.isoformat()
            payloads.append(payload)
    else:
        payload = {"mode": mode}
        if account_id is not None:
            payload["account_id"] = account_id
        if connection_id is not None:
            payload["connection_id"] = connection_id
        if source:
            payload["source"] = source
        if history_from is not None:
            payload["history_from"] = history_from.isoformat()
        payloads.append(payload)

    if history_from is not None:
        if target_account_ids or orphan_connection_ids:
            for target_account_id in target_account_ids:
                _apply_history_from(
                    session,
                    history_from,
                    account_id=target_account_id,
                    connection_id=None,
                    source=None,
                )
            for target_connection_id in orphan_connection_ids:
                _apply_history_from(
                    session,
                    history_from,
                    account_id=None,
                    connection_id=target_connection_id,
                    source=None,
                )
        else:
            _apply_history_from(
                session,
                history_from,
                account_id=account_id,
                connection_id=connection_id,
                source=source,
            )

    jobs = [
        insert_job_payload(session, dek, job_type=JobType.SYNC, payload=payload)
        for payload in payloads
    ]
    session.commit()
    for job in jobs:
        session.refresh(job)
    return [job.id for job in jobs if job.id is not None]


def update_sync_settings(
    session: Session,
    account_id: int,
    *,
    history_from: date | None,
) -> SyncState:
    dek = vault_session.get_dek()
    if dek is None:
        raise RuntimeError("Vault is locked")
    state = get_or_create_sync_state(
        session, dek, account_id, history_from=default_history_from()
    )
    update_sync_state_payload(session, state, dek, history_from=history_from)
    session.commit()
    session.refresh(state)
    return state


def run_sync_job(
    session: Session, job: Job, *, payload: dict | None = None
) -> None:
    from app.services.vault_session import vault_session
    from app.services.secure_runtime import decode_job

    settings = get_settings()
    dek = vault_session.get_dek()
    if not vault_session.is_unlocked() or dek is None:
        job.status = JobStatus.SKIPPED
        return

    registry = build_registry(session)
    if payload is None:
        payload = decode_job(job, dek).payload
    source_filter = payload.get("source")
    account_id_filter = payload.get("account_id")
    connection_id_filter = payload.get("connection_id")
    mode = payload.get("mode") or "sync"
    if payload.get("history_from"):
        try:
            payload_history = date.fromisoformat(str(payload["history_from"]))
        except ValueError:
            payload_history = None
    else:
        payload_history = None

    adapters = registry.configured()
    if connection_id_filter is not None:
        adapters = [a for a in adapters if a.connection_id == connection_id_filter]
    if source_filter:
        try:
            src = AccountSource(source_filter)
            adapters = [a for a in adapters if a.source == src]
        except ValueError:
            adapters = []

    target_account = None
    if account_id_filter is not None:
        target_account = session.get(Account, account_id_filter)
        if target_account is None or not target_account.is_active:
            adapters = []
        else:
            if target_account.connection_id is not None:
                adapters = [
                    a for a in adapters if a.connection_id == target_account.connection_id
                ]
            else:
                adapters = [
                    a
                    for a in adapters
                    if a.source == target_account.source
                    and a.accepts_account(
                        decode_account(target_account, dek).external_id,
                        decode_account(target_account, dek).iban,
                    )
                ]

    if not adapters:
        job.status = JobStatus.SKIPPED
        update_job_payload(
            session,
            job,
            dek,
            error="No configured adapters for this job (vault unlocked?)",
        )
        return

    until = date.today()
    overlap = timedelta(days=settings.sync_overlap_days)
    touched_tx_ids: list[int] = []

    set_sync_progress(phase="running", message="Syncing accounts…", source=source_filter)
    try:
        for adapter in adapters:
            known_trade_query = (
                select(AssetTrade)
                .join(Portfolio)
                .where(Portfolio.source == adapter.source)
            )
            if adapter.connection_id is not None:
                known_trade_query = known_trade_query.where(
                    Portfolio.connection_id == adapter.connection_id
                )
            known_trade_rows = session.exec(known_trade_query).all()
            known_trade_data = [decode_trade(row, dek) for row in known_trade_rows]
            known_trade_external_ids = {
                trade.external_id for trade in known_trade_data
            }
            known_trade_instruments = {
                trade.instrument_external_id for trade in known_trade_data
            }
            known_trade_symbols = {
                str((trade.raw_payload or {}).get("symbol"))
                for trade in known_trade_data
                if isinstance(trade.raw_payload, dict)
                and trade.raw_payload.get("kind") == "spot_trade"
                and trade.raw_payload.get("symbol")
            }
            known_history_external_ids = set(
                session.exec(
                    select(AssetPricePoint.external_id)
                    .where(AssetPricePoint.source == adapter.source)
                    .distinct()
                ).all()
            )
            has_asset_history = bool(known_history_external_ids)
            portfolio_query = select(Portfolio).where(
                Portfolio.source == adapter.source
            )
            if adapter.connection_id is not None:
                portfolio_query = portfolio_query.where(
                    Portfolio.connection_id == adapter.connection_id
                )
            existing_portfolio = session.exec(portfolio_query).first()
            existing_portfolio_data = (
                decode_portfolio(existing_portfolio, dek)
                if existing_portfolio is not None
                else None
            )
            adapter.prepare_asset_sync(
                known_trade_external_ids=known_trade_external_ids,
                known_history_external_ids=known_history_external_ids,
                has_history=has_asset_history,
                has_complete_trade_history=bool(
                    existing_portfolio_data
                    and existing_portfolio_data.asset_ledger_synced_at
                ),
                known_trade_instruments=known_trade_instruments,
                known_trade_symbols=known_trade_symbols,
            )
            set_sync_progress(
                phase="running",
                message=f"Syncing {adapter.source.value}…",
                source=adapter.source.value,
            )
            try:
                raw_accounts = adapter.list_accounts()
            except Exception as exc:
                logger.exception("list_accounts failed for %s", adapter.source)
                message = str(exc)
                _mark_adapter_error(session, adapter, message)
                if adapter.connection_id is not None:
                    set_connection_last_error(
                        session,
                        dek=dek,
                        connection_id=adapter.connection_id,
                        error=message,
                    )
                set_sync_progress(
                    phase="error",
                    message=message[:500],
                    source=adapter.source.value,
                )
                continue

            for raw_acc in raw_accounts:
                if target_account is not None and not _raw_account_matches(
                    raw_acc, target_account, dek
                ):
                    continue
                account = _upsert_account(
                    session,
                    adapter.source,
                    raw_acc,
                    connection_id=adapter.connection_id,
                    dek=dek,
                )
                if account_id_filter and account.id != account_id_filter:
                    continue

                state = get_or_create_sync_state(
                    session, dek, account.id, history_from=default_history_from()  # type: ignore[arg-type]
                )
                if payload_history is not None:
                    update_sync_state_payload(
                        session, state, dek, history_from=payload_history
                    )

                latest = _latest_booking_date(session, account.id, dek)  # type: ignore[arg-type]
                do_full = mode == "backfill" or latest is None

                try:
                    if do_full:
                        _run_full_history(
                            session,
                            adapter=adapter,
                            raw_acc=raw_acc,
                            account=account,
                            state=state,
                            until=until,
                            touched_tx_ids=touched_tx_ids,
                            dek=dek,
                        )
                    else:
                        assert latest is not None
                        since = latest - overlap
                        update_sync_state_payload(
                            session,
                            state,
                            dek,
                            status=SyncStatus.RUNNING,
                            backfill_cursor=None,
                        )
                        session.commit()
                        logger.info(
                            "Delta sync account %s from %s to %s",
                            account.id,
                            since,
                            until,
                        )
                        set_sync_progress(
                            phase="running",
                            message=f"Updating {decode_account(account, dek).name}…",
                            source=adapter.source.value,
                        )
                        raw_txs = adapter.fetch_transactions(raw_acc, since, until)
                        for raw in raw_txs:
                            tx_id = _upsert_transaction(session, account.id, raw)  # type: ignore[arg-type]
                            if tx_id:
                                touched_tx_ids.append(tx_id)
                        update_sync_state_payload(
                            session,
                            state,
                            dek,
                            status=SyncStatus.SUCCESS,
                            last_success_at=datetime.now(timezone.utc),
                            last_error=None,
                            window_start=datetime.combine(
                                since, datetime.min.time(), tzinfo=timezone.utc
                            ),
                        )
                        session.commit()
                except Exception as exc:
                    logger.exception("sync failed for account %s", account.id)
                    update_sync_state_payload(
                        session,
                        state,
                        dek,
                        status=SyncStatus.ERROR,
                        last_error=str(exc)[:2000],
                    )
                    session.commit()
                    set_sync_progress(
                        phase="error",
                        message=str(exc)[:500],
                        source=adapter.source.value,
                    )

                # Balances are source-reported state, independent of the imported
                # transaction window. Keep the previous valid snapshot when a
                # provider temporarily cannot return a balance.
                try:
                    raw_balance = adapter.fetch_balance(raw_acc)
                    if raw_balance is not None:
                        _store_balance(session, account, raw_balance, dek)
                except Exception:
                    logger.exception("balance sync failed for account %s", account.id)

            try:
                has_portfolio_history = session.exec(
                    select(PortfolioValuePoint.id)
                    .join(Portfolio)
                    .where(Portfolio.source == adapter.source)
                    .limit(1)
                ).first() is not None
                # A backfill is an explicit request for the complete market
                # history.  Normal refreshes stay incremental, but must not
                # make a fresh/clean Binance portfolio start at only the last
                # five days.
                requested_history_range = (
                    "max"
                    if mode == "backfill"
                    else "5d"
                    if has_portfolio_history or has_asset_history
                    else "max"
                )
                for raw_portfolio in adapter.fetch_portfolios(
                    history_range=requested_history_range,
                    known_history_external_ids=known_history_external_ids,
                ):
                    _store_portfolio_snapshot(
                        session,
                        adapter.source,
                        raw_portfolio,
                        connection_id=adapter.connection_id,
                        dek=dek,
                    )
            except Exception as exc:
                # Portfolio data is an additional read model. A provider change
                # must not roll back successfully imported cash transactions.
                logger.exception("portfolio sync failed for %s", adapter.source)
                message = f"Depot sync failed: {exc}"
                _mark_adapter_error(session, adapter, message, dek)
                job.status = JobStatus.FAILED
                update_job_payload(session, job, dek, error=message[:2000])
                set_sync_progress(
                    phase="error",
                    message=message[:500],
                    source=adapter.source.value,
                )

        # Older FinTS card rows were imported without a counterparty. Keep
        # the parsed merchant in the encrypted payload itself so the list,
        # detail modal and categorization status all use the same title.
        backfilled_card_titles = backfill_fints_card_titles(session, dek)
        if backfilled_card_titles:
            logger.info(
                "Backfilled %s Volksbank credit-card transaction titles",
                backfilled_card_titles,
            )

        insert_job_payload(session, dek, job_type=JobType.MATCH, payload={})
        insert_job_payload(
            session, dek, job_type=JobType.CATEGORIZE,
            payload={"transaction_ids": touched_tx_ids} if touched_tx_ids else {},
        )
        session.commit()
        if touched_tx_ids:
            # A sync may run while the LLM worker is active. Make freshly
            # touched and previously skipped transactions eligible again; the
            # LLM loop is independent from the database sync worker and will
            # pick them up on its next iteration without restarting it.
            from app.services.llm_categorize import retry_transactions
            retry_transactions(touched_tx_ids)
    finally:
        clear_sync_progress()


def backfill_fints_card_titles(
    session: Session,
    dek: bytes,
    *,
    commit: bool = True,
) -> int:
    """Persist missing merchant titles for existing FinTS card rows."""

    card_account_ids = [
        account.id
        for account in session.exec(
            select(Account).where(Account.source == AccountSource.VOLKSBANK)
        ).all()
        if account.id is not None
        and decode_account(account, dek).account_type == AccountType.CARD
    ]
    if not card_account_ids:
        return 0

    updated = 0
    rows = session.exec(
        select(Transaction).where(Transaction.account_id.in_(card_account_ids))
    ).all()
    for row in rows:
        private = decode_transaction(row, dek)
        if private.counterparty:
            continue
        title = fints_card_transaction_title(private.raw_text)
        if title:
            update_transaction_payload(session, row, dek, counterparty=title)
            updated += 1
    if updated:
        if commit:
            session.commit()
        else:
            session.flush()
    return updated


def _run_full_history(
    session: Session,
    *,
    adapter,
    raw_acc: RawAccount,
    account: Account,
    state: SyncState,
    until: date,
    touched_tx_ids: list[int],
    dek: bytes,
) -> None:
    """Fetch the full history window in one request (no monthly chunks)."""
    private = decode_sync_state(state, dek)
    history_from = private.history_from or default_history_from(until)
    if private.history_from is None:
        update_sync_state_payload(session, state, dek, history_from=history_from)

    update_sync_state_payload(
        session,
        state,
        dek,
        status=SyncStatus.BACKFILLING,
        backfill_cursor=None,
    )
    session.commit()

    logger.info(
        "Full history account %s from %s to %s",
        account.id,
        history_from,
        until,
    )
    set_sync_progress(
        phase="running",
        message=f"Loading history for {decode_account(account, dek).name}…",
        source=adapter.source.value,
    )
    raw_txs = adapter.fetch_transactions(raw_acc, history_from, until)
    for raw in raw_txs:
        tx_id = _upsert_transaction(session, account.id, raw)  # type: ignore[arg-type]
        if tx_id:
            touched_tx_ids.append(tx_id)

    update_sync_state_payload(
        session,
        state,
        dek,
        status=SyncStatus.SUCCESS,
        last_success_at=datetime.now(timezone.utc),
        last_error=None,
        backfill_cursor=None,
        window_start=datetime.combine(
            history_from, datetime.min.time(), tzinfo=timezone.utc
        ),
    )
    session.commit()


def _apply_history_from(
    session: Session,
    history_from: date,
    *,
    account_id: int | None,
    connection_id: int | None,
    source: str | None,
) -> None:
    dek = vault_session.get_dek()
    if dek is None:
        return
    q = select(Account).where(Account.is_active == True)  # noqa: E712
    if account_id is not None:
        q = q.where(Account.id == account_id)
    if connection_id is not None:
        q = q.where(Account.connection_id == connection_id)
    if source:
        try:
            q = q.where(Account.source == AccountSource(source))
        except ValueError:
            return
    for acc in session.exec(q).all():
        state = get_or_create_sync_state(
            session, dek, acc.id, history_from=history_from  # type: ignore[arg-type]
        )
        update_sync_state_payload(session, state, dek, history_from=history_from)
    session.commit()


def _latest_booking_date(session: Session, account_id: int, dek: bytes) -> date | None:
    dates = [
        transaction.booking_date
        for transaction in load_transactions(session, dek, account_id=account_id)
    ]
    return max(dates) if dates else None


def _raw_account_matches(raw: RawAccount, account: Account, dek: bytes) -> bool:
    def normalize(value: str | None) -> str:
        return str(value or "").replace(" ", "").upper()

    private = decode_account(account, dek)
    expected = {normalize(private.external_id), normalize(private.iban)} - {""}
    actual = {normalize(raw.external_id), normalize(raw.iban)} - {""}
    return bool(expected & actual)


def _upsert_account(
    session: Session,
    source: AccountSource,
    raw: RawAccount,
    *,
    connection_id: int | None = None,
    dek: bytes,
) -> Account:
    existing = find_account_by_external_id(
        session, dek, source=source, external_id=raw.external_id
    )
    if existing:
        private = decode_account(existing, dek)
        # Keep user-facing display names; replace IBAN placeholders and legacy "Source: …" labels.
        iban_norm = (private.iban or raw.iban or "").replace(" ", "")
        name_norm = (private.name or "").replace(" ", "")
        legacy_prefix = private.name.startswith(f"{source.value}: ") or private.name.startswith(
            "FinTS: "
        )
        changes: dict[str, object] = {
            "currency": raw.currency,
            "account_type": raw.account_type,
            "iban": raw.iban,
            "is_active": True,
        }
        if not private.name or legacy_prefix or (iban_norm and iban_norm in name_norm):
            changes["name"] = raw.name
        if connection_id is not None:
            changes["connection_id"] = connection_id
        update_account_payload(session, existing, dek, **changes)
        session.commit()
        session.refresh(existing)
        return existing

    account = insert_account_payload(
        session,
        dek,
        connection_id=connection_id,
        source=source,
        external_id=raw.external_id,
        name=raw.name,
        currency=raw.currency,
        account_type=raw.account_type,
        iban=raw.iban,
    )
    session.commit()
    session.refresh(account)
    return account


def _store_balance(
    session: Session, account: Account, raw: RawBalance, dek: bytes
) -> AccountBalanceSnapshot:
    currency = str(raw.currency or decode_account(account, dek).currency).upper()[:3]
    snapshot = insert_balance_payload(
        session,
        dek,
        account_id=account.id,  # type: ignore[arg-type]
        booked_balance=raw.booked,
        available_balance=raw.available,
        currency=currency,
        captured_at=raw.captured_at,
        raw_payload=raw.raw_payload or None,
    )
    update_account_payload(
        session,
        account,
        dek,
        current_balance=raw.booked,
        available_balance=raw.available,
        balance_updated_at=raw.captured_at,
        currency=currency,
    )
    session.commit()
    session.refresh(snapshot)
    return snapshot


def _store_portfolio_snapshot(
    session: Session,
    source: AccountSource,
    raw: RawPortfolio,
    *,
    connection_id: int | None,
    dek: bytes,
) -> Portfolio:
    portfolio = find_portfolio_by_external_id(
        session, dek, source=source, external_id=raw.external_id
    )
    if portfolio is None:
        portfolio = insert_portfolio_payload(
            session,
            dek,
            connection_id=connection_id,
            source=source,
            external_id=raw.external_id,
            name=raw.name,
            currency=raw.currency,
            last_synced_at=raw.captured_at,
            asset_ledger_synced_at=raw.captured_at if raw.trades_complete else None,
        )
    else:
        changes: dict[str, object] = {
            "connection_id": connection_id,
            "name": raw.name,
            "currency": raw.currency,
            "last_synced_at": raw.captured_at,
        }
        if raw.trades_complete:
            changes["asset_ledger_synced_at"] = raw.captured_at
        update_portfolio_payload(session, portfolio, dek, **changes)

    # Delta APIs may omit old executions and therefore return no current cost
    # basis. Never erase a previously established average merely because this
    # particular sync window contains no purchase for the asset.
    stored_cost_rows = session.exec(
        select(AssetPositionSnapshot)
        .where(AssetPositionSnapshot.portfolio_id == portfolio.id)
        .order_by(AssetPositionSnapshot.captured_at.desc())
    ).all()
    known_cost_rows = [
        decoded
        for row in stored_cost_rows
        if (decoded := decode_position(row, dek)).average_buy_in is not None
    ]
    last_known_average: dict[str, Decimal] = {}
    for known in known_cost_rows:
        if known.average_buy_in is not None:
            last_known_average.setdefault(known.external_id, known.average_buy_in)

    for position in raw.positions:
        if position.average_buy_in is not None:
            average_buy_in = position.average_buy_in
        elif raw.trades_complete and source == AccountSource.BINANCE:
            # A complete Binance ledger is authoritative.  Keeping an older
            # average here when the refreshed history contains no buy basis
            # preserves stale/CSV-derived cost values indefinitely (which can
            # turn a tiny residual balance such as VET into a four-digit loss).
            average_buy_in = None
        else:
            average_buy_in = last_known_average.get(position.external_id)
        raw_payload = dict(position.raw_payload or {})
        if position.average_buy_in is None and average_buy_in is not None:
            raw_payload["average_buy_in_carried_forward"] = True
        insert_position_payload(
                session,
                dek,
                portfolio_id=portfolio.id,  # type: ignore[arg-type]
                external_id=position.external_id,
                isin=position.isin,
                name=position.name,
                asset_type=position.asset_type,
                quantity=position.quantity,
                average_buy_in=average_buy_in,
                current_price=position.current_price,
                market_value=position.market_value,
                currency=position.currency,
                captured_at=raw.captured_at,
                raw_payload=raw_payload or None,
        )
    _upsert_asset_price_history(session, source, raw)
    _upsert_portfolio_value_history(session, portfolio, raw, dek)
    _upsert_asset_trades(session, portfolio, raw, dek)
    session.commit()
    session.refresh(portfolio)
    return portfolio


def _upsert_asset_price_history(
    session: Session, source: AccountSource, raw: RawPortfolio
) -> None:
    by_instrument: dict[tuple[str, str], list] = {}
    for point in raw.price_history:
        by_instrument.setdefault((point.external_id, point.exchange), []).append(point)

    for (external_id, exchange), points in by_instrument.items():
        timestamps = [point.timestamp for point in points]
        existing = session.exec(
            select(AssetPricePoint).where(
                AssetPricePoint.source == source,
                AssetPricePoint.external_id == external_id,
                AssetPricePoint.exchange == exchange,
                AssetPricePoint.timestamp.in_(timestamps),
            )
        ).all()
        by_timestamp = {point.timestamp: point for point in existing}
        for raw_point in points:
            point = by_timestamp.get(raw_point.timestamp)
            if point is None:
                point = AssetPricePoint(
                    source=source,
                    external_id=raw_point.external_id,
                    exchange=raw_point.exchange,
                    timestamp=raw_point.timestamp,
                    close=raw_point.close,
                    currency=raw_point.currency,
                )
            point.open = raw_point.open
            point.high = raw_point.high
            point.low = raw_point.low
            point.close = raw_point.close
            point.adjusted = raw_point.adjusted
            point.volume = raw_point.volume
            point.currency = raw_point.currency
            session.add(point)


def _upsert_portfolio_value_history(
    session: Session, portfolio: Portfolio, raw: RawPortfolio, dek: bytes
) -> None:
    if not raw.value_history:
        return
    history_ranges = {point.history_range for point in raw.value_history}
    # A max history is the canonical performance series. Short provider ranges
    # rebase absoluteValue and must not survive beside it, otherwise changing
    # the UI range changes the reported performance rather than only its view.
    if "max" in history_ranges:
        session.exec(
            delete(PortfolioValuePoint).where(
                PortfolioValuePoint.portfolio_id == portfolio.id,
            )
        )
    else:
        # Keep compatibility for providers that cannot return a maximum range.
        for history_range in history_ranges:
            session.exec(
                delete(PortfolioValuePoint).where(
                    PortfolioValuePoint.portfolio_id == portfolio.id,
                    PortfolioValuePoint.history_range == history_range,
                )
            )
        session.exec(
            delete(PortfolioValuePoint).where(
                PortfolioValuePoint.portfolio_id == portfolio.id,
                PortfolioValuePoint.history_range == "legacy",
            )
        )
    session.flush()
    for raw_point in raw.value_history:
        insert_portfolio_value_payload(
            session,
            dek,
            portfolio_id=portfolio.id,  # type: ignore[arg-type]
            timestamp=raw_point.timestamp,
            history_range=raw_point.history_range,
            market_value=raw_point.market_value,
            currency=raw_point.currency,
            cash_balance=raw_point.cash_balance,
            raw_payload=raw_point.raw_payload or None,
        )


def _upsert_asset_trades(
    session: Session, portfolio: Portfolio, raw: RawPortfolio, dek: bytes
) -> None:
    if not raw.trades and not raw.completed_trade_symbols:
        return
    incoming_spot_ids: dict[str, set[str]] = {}
    for raw_trade in raw.trades:
        raw_payload = raw_trade.raw_payload or {}
        if (
            isinstance(raw_payload, dict)
            and raw_payload.get("kind") == "spot_trade"
            and raw_payload.get("symbol")
        ):
            incoming_spot_ids.setdefault(str(raw_payload["symbol"]), set()).add(
                raw_trade.external_id
            )
        trade = find_trade_by_external_id(
            session,
            dek,
            portfolio_id=portfolio.id,  # type: ignore[arg-type]
            external_id=raw_trade.external_id,
        )
        upsert_trade_payload(
            session, dek, row=trade,
            portfolio_id=portfolio.id,  # type: ignore[arg-type]
            external_id=raw_trade.external_id,
            instrument_external_id=raw_trade.instrument_external_id,
            timestamp=raw_trade.timestamp, side=raw_trade.side,
            quantity=raw_trade.quantity, cash_amount=raw_trade.cash_amount,
            fees=raw_trade.fees, taxes=raw_trade.taxes,
            currency=raw_trade.currency,
            raw_payload=raw_trade.raw_payload or None,
        )

    # A complete Binance ``myTrades`` response is authoritative for the pair
    # it queried. Remove old spot rows for that pair that are no longer in the
    # response (for example rows left behind by the retired CSV importer or a
    # previous leg mapping). Capital, convert and earn rows remain untouched
    # because those endpoints are only partially available historically.
    if raw.completed_trade_symbols and portfolio.id is not None:
        stale_rows: list[AssetTrade] = []
        existing_rows = session.exec(
            select(AssetTrade).where(AssetTrade.portfolio_id == portfolio.id)
        ).all()
        for row in existing_rows:
            decoded = decode_trade(row, dek)
            payload = decoded.raw_payload or {}
            if not isinstance(payload, dict) or payload.get("kind") != "spot_trade":
                continue
            symbol = str(payload.get("symbol") or "")
            if symbol not in raw.completed_trade_symbols:
                continue
            if decoded.external_id not in incoming_spot_ids.get(symbol, set()):
                stale_rows.append(row)
        for row in stale_rows:
            session.delete(row)
        if stale_rows:
            logger.info(
                "Reconciled %s stale Binance spot ledger rows for %s",
                len(stale_rows),
                ", ".join(sorted(raw.completed_trade_symbols)),
            )


def _get_or_create_sync_state(session: Session, account_id: int) -> SyncState:
    dek = vault_session.get_dek()
    if dek is None:
        raise RuntimeError("Vault is locked")
    state = get_or_create_sync_state(
        session, dek, account_id, history_from=default_history_from()
    )
    session.commit()
    session.refresh(state)
    return state


def _upsert_transaction(session: Session, account_id: int, raw: RawTransaction) -> int | None:
    dek = vault_session.get_dek()
    if dek is None:
        return None
    identity_filter = (
        Transaction.external_id_blind
        == transaction_external_id_index(dek, account_id, raw.external_id)
    )
    existing = session.exec(
        select(Transaction).where(
            Transaction.account_id == account_id,
            identity_filter,
        )
    ).first()
    kind = infer_kind(raw)
    if existing:
        private = decode_transaction(existing, dek)
        update_transaction_payload(
            session,
            existing,
            dek,
            booking_date=raw.booking_date,
            amount=raw.amount,
            currency=raw.currency,
            raw_text=raw.raw_text,
            counterparty=raw.counterparty,
            raw_payload=raw.raw_payload,
            kind=(
                private.kind
                if private.kind in (TransactionKind.TRANSFER, TransactionKind.IGNORE)
                else kind
            ),
        )
        session.commit()
        return existing.id

    tx = insert_transaction_payload(
        session,
        dek,
        account_id=account_id,
        external_id=raw.external_id,
        booking_date=raw.booking_date,
        amount=raw.amount,
        currency=raw.currency,
        raw_text=raw.raw_text,
        counterparty=raw.counterparty,
        kind=kind,
        raw_payload=raw.raw_payload,
    )
    session.commit()
    return tx.id


def connection_sync_statuses(
    session: Session, dek: bytes, connection_ids: list[int]
) -> dict[int, dict]:
    """Summarize encrypted sync jobs scoped to each connection."""

    if not connection_ids:
        return {}
    sync_jobs = session.exec(
        select(Job)
        .where(Job.job_type == JobType.SYNC)
        .order_by(Job.created_at.desc())  # type: ignore[arg-type]
    ).all()
    by_connection: dict[int, list[Job]] = {cid: [] for cid in connection_ids}
    for job in sync_jobs:
        try:
            payload = decode_job(job, dek).payload
        except Exception:
            continue
        raw_connection_id = payload.get("connection_id")
        if raw_connection_id is None:
            continue
        try:
            connection_id = int(raw_connection_id)
        except (TypeError, ValueError):
            continue
        if connection_id in by_connection:
            by_connection[connection_id].append(job)

    result: dict[int, dict] = {}
    for connection_id, jobs in by_connection.items():
        pending = [
            job
            for job in jobs
            if job.status in (JobStatus.PENDING, JobStatus.RUNNING)
        ]
        latest = jobs[0] if jobs else None
        latest_error: str | None = None
        if latest is not None:
            try:
                private = decode_job(latest, dek)
                latest_error = private.error
            except Exception:
                latest_error = None
        result[connection_id] = {
            "pending_jobs": len([j for j in pending if j.status == JobStatus.PENDING]),
            "running_jobs": len([j for j in pending if j.status == JobStatus.RUNNING]),
            "latest_job_status": latest.status if latest else None,
            "latest_job_error": latest_error,
        }
    return result


def _mark_adapter_error(session: Session, adapter, error: str, dek: bytes) -> None:
    query = select(Account).where(Account.source == adapter.source)
    if adapter.connection_id is not None:
        query = query.where(Account.connection_id == adapter.connection_id)
    accounts = session.exec(query).all()
    for acc in accounts:
        state = get_or_create_sync_state(
            session, dek, acc.id, history_from=default_history_from()  # type: ignore[arg-type]
        )
        update_sync_state_payload(
            session, state, dek, status=SyncStatus.ERROR, last_error=error[:2000]
        )
    session.commit()
