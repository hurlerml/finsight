from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import Category, CategoryRule, Transaction
from app.schemas import (
    CategoryCreate,
    CategoryImpactRead,
    CategoryMutationRead,
    CategoryRead,
    CategoryRuleCreate,
    CategoryRuleRead,
    CategoryUpdate,
)
from app.services.categorize import apply_rules, category_impact
from app.services.embeddings import schedule_transaction_embedding_backfill
from app.services.secure_labels import (
    decode_category,
    decode_rule,
    insert_category_payload,
    insert_rule_payload,
    load_categories,
    load_rules,
    update_category_payload,
)
from app.services.llm_categorize import (
    invalidate_classification_context,
    retry_transactions,
)
from app.services.secure_transactions import decode_transaction, update_transaction_payload

router = APIRouter(tags=["categories"])

CATEGORY_COLORS = {
    "housing": "#b8cbee",
    "groceries": "#bfd4ae",
    "dining": "#e7c6ae",
    "mobility": "#b4d3e6",
    "health": "#e7c2d0",
    "subscriptions": "#c9bee0",
    "shopping": "#d6c3df",
    "leisure": "#add2c5",
    "travel": "#b8cbee",
    "family": "#e7c2d0",
    "education": "#b6d5d0",
    "savings": "#b7d5c3",
    "finance": "#c8c9c5",
    "income": "#b8d2a9",
    "other": "#c7ccd0",
}


def _mutation(
    category: CategoryRead | None,
    counts: tuple[int, int, int] = (0, 0, 0),
) -> CategoryMutationRead:
    reset_count, rules_applied, queued_for_agent = counts
    return CategoryMutationRead(
        category=category,
        reset_count=reset_count,
        rules_applied=rules_applied,
        queued_for_agent=queued_for_agent,
    )


@router.get("/api/categories", response_model=list[CategoryRead])
def list_categories(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[CategoryRead]:
    return [CategoryRead(**item.__dict__) for item in load_categories(session, dek)]


@router.get("/api/categories/impact", response_model=CategoryImpactRead)
def all_category_impact(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryImpactRead:
    return CategoryImpactRead(**category_impact(session, dek))


@router.get("/api/categories/{category_id}/impact", response_model=CategoryImpactRead)
def one_category_impact(
    category_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryImpactRead:
    if session.get(Category, category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return CategoryImpactRead(**category_impact(session, dek, category_id=category_id))


@router.post("/api/categories", response_model=CategoryMutationRead, status_code=201)
def create_category(
    body: CategoryCreate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryMutationRead:
    data = body.model_dump()
    name = str(data["name"]).strip()
    description = str(data["description"]).strip()
    try:
        cat = insert_category_payload(
            session,
            dek,
            name=name,
            description=description,
            slug=f"custom_{uuid4().hex}",
            color=CATEGORY_COLORS[str(data["color_key"])],
            color_key=str(data["color_key"]),
            icon=str(data["icon"]),
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    session.refresh(cat)
    invalidate_classification_context()
    return _mutation(CategoryRead(**decode_category(cat, dek).__dict__))


@router.patch("/api/categories/{category_id}", response_model=CategoryMutationRead)
def update_category(
    category_id: int,
    body: CategoryUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryMutationRead:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system:
        raise HTTPException(status_code=409, detail="System categories are read-only")

    current = decode_category(category, dek)
    changes = body.model_dump(exclude_none=True)
    if "name" in changes:
        changes["name"] = str(changes["name"]).strip()
    if "description" in changes:
        changes["description"] = str(changes["description"]).strip()
    if "color_key" in changes:
        changes["color"] = CATEGORY_COLORS[str(changes["color_key"])]
    semantic_change = any(
        key in changes and changes[key] != getattr(current, key)
        for key in ("name", "description")
    )
    try:
        updated = update_category_payload(session, category, dek, **changes)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Category name already exists") from exc
    if semantic_change:
        invalidate_classification_context()
    return _mutation(CategoryRead(**updated.__dict__))


@router.delete("/api/categories/{category_id}", response_model=CategoryMutationRead)
def delete_category(
    category_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryMutationRead:
    category = session.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if category.is_system:
        raise HTTPException(status_code=409, detail="System categories cannot be deleted")

    affected_rows: list[Transaction] = []
    for row in session.exec(select(Transaction).order_by(Transaction.id)).all():
        private = decode_transaction(row, dek)
        if private.category_id == category_id:
            affected_rows.append(row)
            update_transaction_payload(
                session,
                row,
                dek,
                category_id=None,
                categorized_by=None,
                categorization_reason=None,
            )
    transaction_ids = [row.id for row in affected_rows if row.id is not None]
    session.execute(delete(CategoryRule).where(CategoryRule.category_id == category_id))
    session.delete(category)
    session.commit()
    invalidate_classification_context()

    rules_applied = apply_rules(session, transaction_ids)
    queued_ids = [
        private.id
        for row in session.exec(
            select(Transaction).where(col(Transaction.id).in_(transaction_ids))
        ).all()
        if (private := decode_transaction(row, dek)).category_id is None
    ] if transaction_ids else []
    retry_transactions(queued_ids)
    schedule_transaction_embedding_backfill(dek)
    return _mutation(
        None,
        (len(transaction_ids), rules_applied, len(queued_ids)),
    )


@router.get("/api/category-rules", response_model=list[CategoryRuleRead])
def list_rules(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[CategoryRuleRead]:
    return [CategoryRuleRead(**item.__dict__) for item in load_rules(session, dek)]


@router.post("/api/category-rules", response_model=CategoryRuleRead, status_code=201)
def create_rule(
    body: CategoryRuleCreate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> CategoryRuleRead:
    if not session.get(Category, body.category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    rule = insert_rule_payload(session, dek, **body.model_dump())
    session.commit()
    session.refresh(rule)
    return CategoryRuleRead(**decode_rule(rule, dek).__dict__)
