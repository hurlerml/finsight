from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import Tag, Transaction, TransactionTag
from app.schemas import TagCreate, TagRead, TagUpdate, TransactionTagRead
from app.services.secure_labels import (
    decode_assignment,
    decode_tag,
    find_tag_by_name,
    insert_assignment_payload,
    insert_tag_payload,
    load_tags,
    update_tag_payload,
)
from app.services.secure_transactions import decode_transaction

router = APIRouter(tags=["tags"])


@router.get("/api/tags", response_model=list[TagRead])
def list_tags(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[TagRead]:
    return [TagRead(**item.__dict__) for item in load_tags(session, dek)]


@router.post("/api/tags", response_model=TagRead, status_code=201)
def create_tag(
    body: TagCreate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> TagRead:
    name = body.name.strip()
    existing = find_tag_by_name(session, dek, name)
    if existing:
        raise HTTPException(status_code=409, detail="Tag name already exists")
    tag = insert_tag_payload(session, dek, **{**body.model_dump(), "name": name})
    session.commit()
    session.refresh(tag)
    return TagRead(**decode_tag(tag, dek).__dict__)


@router.patch("/api/tags/{tag_id}", response_model=TagRead)
def update_tag(
    tag_id: int,
    body: TagUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> TagRead:
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    updates = body.model_dump(exclude_unset=True)
    if "name" in updates:
        updates["name"] = updates["name"].strip()
    try:
        decoded = update_tag_payload(session, tag, dek, **updates)
    except ValueError:
        raise HTTPException(status_code=422, detail="from_date must not be after to_date")
    session.commit()
    session.refresh(tag)
    return TagRead(**decoded.__dict__)


@router.delete("/api/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: int, session: Session = Depends(get_session)) -> Response:
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    assignments = session.exec(select(TransactionTag).where(TransactionTag.tag_id == tag_id)).all()
    for assignment in assignments:
        session.delete(assignment)
    session.delete(tag)
    session.commit()
    return Response(status_code=204)


@router.get("/api/tag-assignments", response_model=list[TransactionTagRead])
def list_assignments(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[TransactionTagRead]:
    rows = session.exec(
        select(TransactionTag).order_by(col(TransactionTag.created_at))
    ).all()
    if from_date or to_date:
        filtered = []
        for row in rows:
            stored_transaction = session.get(Transaction, row.transaction_id)
            if stored_transaction is None:
                continue
            transaction = decode_transaction(stored_transaction, dek)
            if from_date is not None and transaction.booking_date < from_date:
                continue
            if to_date is not None and transaction.booking_date > to_date:
                continue
            filtered.append(row)
        rows = filtered
    return [TransactionTagRead(**decode_assignment(row, dek).__dict__) for row in rows]


@router.post(
    "/api/transactions/{transaction_id}/tags/{tag_id}",
    response_model=TransactionTagRead,
)
def assign_tag(
    transaction_id: int,
    tag_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> TransactionTagRead:
    if not session.get(Transaction, transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not session.get(Tag, tag_id):
        raise HTTPException(status_code=404, detail="Tag not found")
    existing = session.exec(
        select(TransactionTag).where(
            TransactionTag.transaction_id == transaction_id,
            TransactionTag.tag_id == tag_id,
        )
    ).first()
    if existing:
        return TransactionTagRead(**decode_assignment(existing, dek).__dict__)
    assignment = insert_assignment_payload(
        session, dek, transaction_id=transaction_id, tag_id=tag_id
    )
    session.commit()
    session.refresh(assignment)
    return TransactionTagRead(**decode_assignment(assignment, dek).__dict__)


@router.delete("/api/transactions/{transaction_id}/tags/{tag_id}", status_code=204)
def unassign_tag(
    transaction_id: int,
    tag_id: int,
    session: Session = Depends(get_session),
) -> Response:
    assignment = session.exec(
        select(TransactionTag).where(
            TransactionTag.transaction_id == transaction_id,
            TransactionTag.tag_id == tag_id,
        )
    ).first()
    if assignment:
        session.delete(assignment)
        session.commit()
    return Response(status_code=204)
