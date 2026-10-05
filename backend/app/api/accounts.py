from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, or_
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import (
    Account,
    AccountBalanceSnapshot,
    Connection,
    SyncState,
    Transaction,
    TransactionLink,
    TransactionTag,
)
from app.schemas import AccountCreate, AccountRead, AccountUpdate
from app.services.secure_accounts import (
    AccountData,
    decode_account,
    find_account_by_external_id,
    insert_account_payload,
    load_accounts,
    update_account_payload,
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountRead])
def list_accounts(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[AccountRead]:
    return [_to_read(item) for item in load_accounts(session, dek)]


def _to_read(item: AccountData) -> AccountRead:
    return AccountRead(**item.__dict__)


@router.post("", response_model=AccountRead, status_code=201)
def create_account(
    body: AccountCreate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> AccountRead:
    existing = find_account_by_external_id(
        session, dek, source=body.source, external_id=body.external_id
    )
    if existing:
        raise HTTPException(status_code=409, detail="Account already exists")
    account = insert_account_payload(session, dek, **body.model_dump())
    session.commit()
    session.refresh(account)
    return _to_read(decode_account(account, dek))


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: int,
    body: AccountUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> AccountRead:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if body.name is not None:
        update_account_payload(session, account, dek, name=body.name.strip())
    session.commit()
    session.refresh(account)
    return _to_read(decode_account(account, dek))


@router.get("/{account_id}", response_model=AccountRead)
def get_account(
    account_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> AccountRead:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return _to_read(decode_account(account, dek))


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: int,
    connection_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> None:
    """Delete an imported account and every dependent local record atomically."""
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")

    connection = None
    if connection_id is not None:
        connection = session.get(Connection, connection_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Connection not found")
        if account.connection_id is not None and connection.id != account.connection_id:
            raise HTTPException(status_code=400, detail="Connection does not own this account")
        if connection.source != account.source:
            raise HTTPException(
                status_code=400, detail="Connection does not belong to account source"
            )

    transaction_ids = select(Transaction.id).where(Transaction.account_id == account_id)
    session.exec(
        delete(TransactionLink).where(
            or_(
                TransactionLink.transaction_a_id.in_(transaction_ids),
                TransactionLink.transaction_b_id.in_(transaction_ids),
            )
        )
    )
    session.exec(
        delete(TransactionTag).where(TransactionTag.transaction_id.in_(transaction_ids))
    )
    session.exec(delete(Transaction).where(Transaction.account_id == account_id))
    session.exec(
        delete(AccountBalanceSnapshot).where(AccountBalanceSnapshot.account_id == account_id)
    )
    session.exec(delete(SyncState).where(SyncState.account_id == account_id))
    session.delete(account)
    other_linked_account = (
        session.exec(
            select(Account).where(
                Account.connection_id == connection.id,
                Account.id != account_id,
            )
        ).first()
        if connection is not None
        else None
    )
    if connection is not None and other_linked_account is None:
        session.delete(connection)
    session.commit()
