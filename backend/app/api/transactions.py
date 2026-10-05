from datetime import date
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import Account, Connection, Transaction, TransactionLink
from app.models.enums import CategorizedBy, LinkStatus, TransactionKind
from app.schemas import (
    GroupedTransactionRead,
    TransactionGroupRead,
    TransactionPageRead,
    TransactionRead,
    TransactionUpdate,
)
from app.services.match import confirm_link, reject_link, run_matching
from app.services.secure_accounts import decode_account
from app.services.secure_repository import decrypted_financial_payload
from app.services.secure_transactions import (
    decode_transaction,
    load_transactions,
    update_transaction_payload,
)
from app.services.transaction_titles import fints_card_transaction_title

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
T = TypeVar("T")


def _transaction_read(session: Session, tx, dek: bytes) -> TransactionRead:
    """Build a read model and fill missing FinTS card titles on the fly.

    Older encrypted records may predate the adapter parser. Deriving the
    display title here makes those records immediately readable without
    rewriting their ciphertext.
    """

    result = TransactionRead.model_validate(tx)
    if result.counterparty:
        return result
    account = session.get(Account, tx.account_id)
    if account is None or account.source.value != "volksbank":
        return result
    account_data = decode_account(account, dek)
    if account_data.account_type.value != "card":
        return result
    title = fints_card_transaction_title(tx.raw_text)
    return result.model_copy(update={"counterparty": title}) if title else result


def _page_window(rows: list[T], offset: int, limit: int) -> tuple[list[T], bool, int | None]:
    has_more = len(rows) > limit
    items = rows[:limit]
    return items, has_more, offset + len(items) if has_more else None


@router.post("/rematch")
def rematch_transactions(session: Session = Depends(get_session)) -> dict[str, int | bool]:
    result = run_matching(session)
    return {
        "created_links": result.created_links,
        "confirmed_links": result.confirmed_links,
        "suggested_links": result.suggested_links,
        "rejected_candidates": result.rejected_candidates,
        "candidates_evaluated": result.candidates_evaluated,
        "model_available": result.model_available,
    }


@router.post("/groups/{link_id}/confirm", status_code=204)
def confirm_transaction_group(
    link_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> None:
    link = session.get(TransactionLink, link_id)
    if link is None or link.status == LinkStatus.REJECTED:
        raise HTTPException(status_code=404, detail="Match suggestion not found")
    confirm_link(session, link, dek)


@router.post("/groups/{link_id}/reject", status_code=204)
def reject_transaction_group(
    link_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> None:
    link = session.get(TransactionLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Match not found")
    reject_link(session, link, dek)


@router.get("/groups", response_model=list[TransactionGroupRead])
def list_transaction_groups(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account_id: int | None = None,
    category_id: int | None = None,
    kind: TransactionKind | None = None,
    search: str | None = Query(default=None, alias="q"),
) -> list[TransactionGroupRead]:
    groups: list[TransactionGroupRead] = []
    links = session.exec(
        select(TransactionLink)
        .where(col(TransactionLink.status).in_([LinkStatus.CONFIRMED, LinkStatus.SUGGESTED]))
        .order_by(col(TransactionLink.id))
    ).all()
    for link in links:
        if link.id is None:
            continue
        first = session.get(Transaction, link.transaction_a_id)
        second = session.get(Transaction, link.transaction_b_id)
        if first is None or second is None:
            continue
        transactions = [
            decode_transaction(first, _dek),
            decode_transaction(second, _dek),
        ]
        if (from_date or to_date) and not any(
            (from_date is None or tx.booking_date >= from_date)
            and (to_date is None or tx.booking_date <= to_date)
            for tx in transactions
        ):
            continue
        if account_id is not None and not any(
            tx.account_id == account_id for tx in transactions
        ):
            continue
        if category_id is not None and not any(
            tx.category_id == category_id for tx in transactions
        ):
            continue
        if kind is not None and not any(tx.kind == kind for tx in transactions):
            continue
        if search:
            needle = search.strip().casefold()
            if needle and not any(
                needle in " ".join(
                    (
                        tx.counterparty or "",
                        tx.raw_text or "",
                        str(tx.amount),
                        tx.currency or "",
                        tx.booking_date.isoformat(),
                    )
                ).casefold()
                for tx in transactions
            ):
                continue

        members: list[GroupedTransactionRead] = []
        for tx in transactions:
            account = session.get(Account, tx.account_id)
            if account is None:
                continue
            account_data = decode_account(account, _dek)
            connection = (
                session.get(Connection, account.connection_id)
                if account.connection_id is not None
                else None
            )
            members.append(
                GroupedTransactionRead(
                    **_transaction_read(session, tx, _dek).model_dump(),
                    account_name=account_data.name,
                    account_source=account.source.value,
                    account_provider=connection.provider if connection else None,
                    account_type=account_data.account_type.value,
                )
            )
        if len(members) != 2:
            continue
        members.sort(
            key=lambda tx: (
                0 if tx.id == link.transfer_transaction_id else 1,
                0 if tx.amount < 0 else 1,
                tx.booking_date,
            )
        )
        link_payload = decrypted_financial_payload(link, _dek)
        groups.append(
            TransactionGroupRead(
                id=link.id,
                link_type=link.link_type,
                status=link.status,
                confidence=link_payload.get("confidence") or link.confidence,
                reason=link_payload.get("reason"),
                transactions=members,
            )
        )
    groups.sort(
        key=lambda group: max(tx.booking_date for tx in group.transactions), reverse=True
    )
    return groups


@router.get("", response_model=list[TransactionRead])
def list_transactions(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account_id: int | None = None,
    category_id: int | None = None,
    kind: TransactionKind | None = None,
    search: str | None = Query(default=None, alias="q"),
    limit: int = Query(default=200, le=1000),
) -> list[TransactionRead]:
    rows = load_transactions(
        session,
        _dek,
        from_date=from_date,
        to_date=to_date,
        account_id=account_id,
        category_id=category_id,
        kind=kind,
        search=search,
    )
    return [_transaction_read(session, row, _dek) for row in rows[:limit]]


@router.get("/page", response_model=TransactionPageRead)
def list_transaction_page(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    account_id: int | None = None,
    category_id: int | None = None,
    kind: TransactionKind | None = None,
    search: str | None = Query(default=None, alias="q"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
) -> TransactionPageRead:
    rows = load_transactions(
        session,
        _dek,
        from_date=from_date,
        to_date=to_date,
        account_id=account_id,
        category_id=category_id,
        kind=kind,
        search=search,
    )[offset : offset + limit + 1]
    items, has_more, next_offset = _page_window(rows, offset, limit)
    return TransactionPageRead(
        items=[_transaction_read(session, item, _dek) for item in items],
        has_more=has_more,
        next_offset=next_offset,
    )


@router.patch("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: int,
    body: TransactionUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> TransactionRead:
    tx = session.get(Transaction, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    data = body.model_dump(exclude_unset=True)
    changes: dict[str, object] = {}
    if "category_id" in data:
        changes["category_id"] = data["category_id"]
        changes["categorized_by"] = CategorizedBy.MANUAL
        changes["categorization_reason"] = None
    if "kind" in data and data["kind"] is not None:
        changes["kind"] = data["kind"]
    updated = update_transaction_payload(session, tx, dek, **changes)
    session.commit()
    return _transaction_read(session, updated, dek)
