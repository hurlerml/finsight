"""Ciphertext-only writes for private transfer-link evaluation metadata."""
from decimal import Decimal
from sqlalchemy import insert, update
from sqlmodel import Session

from app.models.enums import LinkEvaluatedBy, LinkStatus, LinkType
from app.models.transaction import TransactionLink
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload
from app.services.secure_repository import decrypted_financial_payload


def insert_link_payload(session: Session, dek: bytes, *, transaction_a_id: int,
                        transaction_b_id: int, transfer_transaction_id: int | None,
                        link_type: LinkType, status: LinkStatus,
                        evaluated_by: LinkEvaluatedBy, confidence: Decimal,
                        reason: str | None) -> TransactionLink:
    link_id = session.execute(insert(TransactionLink).values(
        transaction_a_id=transaction_a_id, transaction_b_id=transaction_b_id,
        transfer_transaction_id=transfer_transaction_id, link_type=link_type,
        status=status,
    ).returning(TransactionLink.id)).scalar_one()
    payload = {"link_type": link_type.value, "status": status.value,
               "evaluated_by": evaluated_by.value, "confidence": confidence,
               "reason": reason}
    session.execute(update(TransactionLink).where(TransactionLink.id == link_id).values(
        encrypted_payload=encrypt_payload(
            dek, domain="transaction-link", record_id=link_id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION,
    ))
    session.flush()
    row = session.get(TransactionLink, link_id)
    if row is None:
        raise RuntimeError("Ciphertext transaction link insert failed")
    return row


def update_link_payload(session: Session, row: TransactionLink, dek: bytes, *,
                        status: LinkStatus | None = None,
                        evaluated_by: LinkEvaluatedBy | None = None) -> None:
    if row.id is None:
        raise ValueError("Persisted transaction link is missing its id")
    payload = decrypted_financial_payload(row, dek)
    if status is not None:
        payload["status"] = status.value
    if evaluated_by is not None:
        payload["evaluated_by"] = evaluated_by.value
    values: dict = {
        "encrypted_payload": encrypt_payload(
            dek, domain="transaction-link", record_id=row.id, payload=payload
        ),
        "encryption_version": ENCRYPTION_VERSION,
    }
    if status is not None:
        values["status"] = status
    session.execute(update(TransactionLink).where(TransactionLink.id == row.id).values(**values))
    session.flush()
    session.expire(row)
