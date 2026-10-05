"""Ciphertext-first reads for categories, rules, tags, and assignments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, insert, or_, update
from sqlmodel import Session, select

from app.models.category import Category, CategoryRule
from app.models.enums import TagType
from app.models.tag import Tag, TransactionTag
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload, private_name_index
from app.services.secure_repository import decrypted_financial_payload


@dataclass(frozen=True)
class CategoryData:
    id: int
    name: str
    slug: str
    color: str
    is_system: bool
    created_at: datetime
    description: str = ""
    color_key: str = "other"
    icon: str = "other"


@dataclass(frozen=True)
class CategoryRuleData:
    id: int
    category_id: int
    pattern: str
    is_regex: bool
    priority: int
    is_active: bool
    created_at: datetime


@dataclass(frozen=True)
class TagData:
    id: int
    name: str
    tag_type: TagType
    color: str
    from_date: date | None
    to_date: date | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class TransactionTagData:
    id: int
    transaction_id: int
    tag_id: int
    assigned_by: str
    confidence: Decimal
    reason: str | None
    created_at: datetime


def _insert_payload(session: Session, dek: bytes, model: type, domain: str,
                    technical: dict, payload: dict, extra: dict | None = None):
    statement = insert(model).values(**technical) if technical else insert(model)
    record_id = session.execute(statement.returning(model.id)).scalar_one()
    session.execute(update(model).where(model.id == record_id).values(
        encrypted_payload=encrypt_payload(
            dek, domain=domain, record_id=record_id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION, **(extra or {}),
    ))
    session.flush()
    row = session.get(model, record_id)
    if row is None:
        raise RuntimeError(f"Ciphertext {domain} insert failed")
    return row


def insert_category_payload(
    session: Session,
    dek: bytes,
    *,
    name: str,
    slug: str,
    color: str,
    description: str = "",
    color_key: str = "other",
    icon: str = "other",
    is_system: bool = False,
) -> Category:
    return _insert_payload(
        session, dek, Category, "category",
        {"slug": slug, "is_system": is_system},
        {
            "name": name,
            "description": description,
            "color": color,
            "color_key": color_key,
            "icon": icon,
        },
        {"name_blind": private_name_index(dek, "category", name)},
    )


def update_category_payload(
    session: Session,
    row: Category,
    dek: bytes,
    **changes: object,
) -> CategoryData:
    if row.id is None:
        raise ValueError("Persisted category is missing its id")
    payload = decrypted_financial_payload(row, dek)
    payload.update(changes)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Category name must not be empty")
    session.execute(
        update(Category)
        .where(Category.id == row.id)
        .values(
            encrypted_payload=encrypt_payload(
                dek,
                domain="category",
                record_id=row.id,
                payload=payload,
            ),
            encryption_version=ENCRYPTION_VERSION,
            name_blind=private_name_index(dek, "category", name),
        )
    )
    session.flush()
    session.expire(row)
    return decode_category(row, dek)


def insert_rule_payload(session: Session, dek: bytes, *, category_id: int,
                        pattern: str, is_regex: bool = False, priority: int = 100,
                        is_active: bool = True) -> CategoryRule:
    return _insert_payload(
        session, dek, CategoryRule, "category-rule",
        {"category_id": category_id},
        {"pattern": pattern, "is_regex": is_regex, "priority": priority,
         "is_active": is_active},
    )


def insert_tag_payload(session: Session, dek: bytes, *, name: str,
                       tag_type: TagType = TagType.GENERAL, color: str = "#b9c8ea",
                       from_date: date | None = None, to_date: date | None = None,
                       created_by: str = "manual") -> Tag:
    return _insert_payload(
        session, dek, Tag, "tag",
        {},
        {"name": name, "tag_type": tag_type.value, "color": color,
         "from_date": from_date, "to_date": to_date, "created_by": created_by},
        {"name_blind": private_name_index(dek, "tag", name)},
    )


def update_tag_payload(session: Session, row: Tag, dek: bytes,
                       **changes: object) -> TagData:
    if row.id is None:
        raise ValueError("Persisted tag is missing its id")
    payload = decrypted_financial_payload(row, dek)
    for key, value in changes.items():
        payload[key] = value.value if hasattr(value, "value") else value
    from_value, to_value = _date(payload.get("from_date")), _date(payload.get("to_date"))
    if from_value and to_value and from_value > to_value:
        raise ValueError("from_date must not be after to_date")
    name = str(payload["name"])
    session.execute(update(Tag).where(Tag.id == row.id).values(
        encrypted_payload=encrypt_payload(
            dek, domain="tag", record_id=row.id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION,
        name_blind=private_name_index(dek, "tag", name),
    ))
    session.flush(); session.expire(row)
    return decode_tag(row, dek)


def insert_assignment_payload(session: Session, dek: bytes, *, transaction_id: int,
                              tag_id: int, assigned_by: str = "manual",
                              confidence: Decimal = Decimal("1"),
                              reason: str | None = None) -> TransactionTag:
    return _insert_payload(
        session, dek, TransactionTag, "transaction-tag",
        {"transaction_id": transaction_id, "tag_id": tag_id},
        {"assigned_by": assigned_by, "confidence": confidence, "reason": reason},
    )


def _date(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value is not None else None


def decode_category(row: Category, dek: bytes) -> CategoryData:
    if row.id is None:
        raise ValueError("Persisted category is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return CategoryData(
        id=row.id,
        name=str(payload.get("name") or ""),
        slug=row.slug,
        color=str(payload.get("color") or "#64748b"),
        is_system=row.is_system,
        created_at=row.created_at,
        description=str(payload.get("description") or ""),
        color_key=str(payload.get("color_key") or row.slug or "other"),
        icon=str(payload.get("icon") or row.slug or "other"),
    )


def decode_rule(row: CategoryRule, dek: bytes) -> CategoryRuleData:
    if row.id is None:
        raise ValueError("Persisted category rule is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return CategoryRuleData(
        id=row.id,
        category_id=row.category_id,
        pattern=str(payload.get("pattern") or ""),
        is_regex=bool(payload.get("is_regex")),
        priority=int(payload.get("priority") or 0),
        is_active=bool(payload.get("is_active")),
        created_at=row.created_at,
    )


def decode_tag(row: Tag, dek: bytes) -> TagData:
    if row.id is None:
        raise ValueError("Persisted tag is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return TagData(
        id=row.id,
        name=str(payload.get("name") or ""),
        tag_type=TagType(str(payload.get("tag_type") or TagType.GENERAL.value)),
        color=str(payload.get("color") or "#b9c8ea"),
        from_date=_date(payload.get("from_date")),
        to_date=_date(payload.get("to_date")),
        created_by=str(payload.get("created_by") or "manual"),
        created_at=row.created_at,
    )


def decode_assignment(row: TransactionTag, dek: bytes) -> TransactionTagData:
    if row.id is None:
        raise ValueError("Persisted tag assignment is missing its id")
    payload = decrypted_financial_payload(row, dek)
    return TransactionTagData(
        id=row.id,
        transaction_id=row.transaction_id,
        tag_id=row.tag_id,
        assigned_by=str(payload.get("assigned_by") or "manual"),
        confidence=Decimal(str(payload.get("confidence") or "1")),
        reason=str(payload["reason"]) if payload.get("reason") is not None else None,
        created_at=row.created_at,
    )


def load_categories(session: Session, dek: bytes) -> list[CategoryData]:
    rows = session.exec(select(Category).order_by(Category.id)).all()
    return sorted((decode_category(row, dek) for row in rows), key=lambda item: item.name.casefold())


def load_rules(session: Session, dek: bytes, *, active_only: bool = False) -> list[CategoryRuleData]:
    rows = session.exec(select(CategoryRule).order_by(CategoryRule.id)).all()
    decoded = [decode_rule(row, dek) for row in rows]
    if active_only:
        decoded = [rule for rule in decoded if rule.is_active]
    return sorted(decoded, key=lambda item: (item.priority, item.id))


def load_tags(session: Session, dek: bytes) -> list[TagData]:
    rows = session.exec(select(Tag).order_by(Tag.id)).all()
    return sorted((decode_tag(row, dek) for row in rows), key=lambda item: item.name.casefold())


def find_tag_by_name(session: Session, dek: bytes, name: str) -> Tag | None:
    blind = private_name_index(dek, "tag", name)
    return session.exec(select(Tag).where(Tag.name_blind == blind)).first()
