"""Cashflow stats: summary, timeseries trend, sankey flow."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_unlocked
from app.models import Transaction
from app.models.enums import TransactionKind
from app.models.vault import Connection
from app.schemas.stats import (
    CategoryBreakdown,
    FlowLink,
    FlowNode,
    FlowResponse,
    StatsSummary,
    TimeseriesBucket,
    TimeseriesResponse,
    TimeseriesSegment,
)
from app.services.secure_transactions import TransactionData, load_transactions
from app.services.secure_accounts import load_accounts
from app.services.secure_labels import CategoryData, load_categories

router = APIRouter(prefix="/api/stats", tags=["stats"])

# Keep uncategorized transactions distinct from the user-created/default
# "Other" category.  Both used to share the slug ``other``, which caused the
# Sankey node key to merge their amounts and highlighted both branches at once.
UNCATEGORIZED_SLUG = "uncategorized"


def _is_savings_transaction(
    transaction: Transaction | TransactionData, category_slugs: dict[int | None, str]
) -> bool:
    return (
        transaction.kind == TransactionKind.EXPENSE
        and category_slugs.get(transaction.category_id) == "savings"
    )


def _load_txs(
    session: Session, dek: bytes, from_date: date, to_date: date
) -> list[TransactionData]:
    return [
        transaction
        for transaction in load_transactions(
            session,
            dek,
            from_date=from_date,
            to_date=to_date,
        )
        if transaction.kind in (TransactionKind.EXPENSE, TransactionKind.INCOME)
    ]


def _breakdown(
    txs: list[TransactionData],
    *,
    kind: TransactionKind,
    categories: dict[int, CategoryData],
) -> list[CategoryBreakdown]:
    buckets: dict[int | None, list[Decimal]] = defaultdict(list)
    for t in txs:
        if t.kind != kind:
            continue
        buckets[t.category_id].append(abs(t.amount))
    return [
        CategoryBreakdown(
            category_id=cid,
            category_name=categories[cid].name if cid in categories else "Uncategorized",
            category_slug=categories[cid].slug if cid in categories else UNCATEGORIZED_SLUG,
            color=categories[cid].color if cid in categories else None,
            color_key=categories[cid].color_key if cid in categories else "other",
            icon=categories[cid].icon if cid in categories else "other",
            amount=sum(amounts, Decimal("0")),
            count=len(amounts),
        )
        for cid, amounts in sorted(
            buckets.items(), key=lambda kv: sum(kv[1], Decimal("0")), reverse=True
        )
    ]


@router.get("/summary", response_model=StatsSummary)
def summary(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> StatsSummary:
    today = date.today()
    if from_date is None:
        from_date = date(today.year, 1, 1)
    if to_date is None:
        to_date = today

    txs = _load_txs(session, _dek, from_date, to_date)
    income = sum((t.amount for t in txs if t.kind == TransactionKind.INCOME), Decimal("0"))
    expense = sum(
        (abs(t.amount) for t in txs if t.kind == TransactionKind.EXPENSE), Decimal("0")
    )
    category_rows = load_categories(session, _dek)
    categories = {c.id: c for c in category_rows}
    cat_slugs = {c.id: c.slug for c in category_rows}
    savings = sum(
        (
            abs(t.amount)
            for t in txs
            if _is_savings_transaction(t, cat_slugs)
        ),
        Decimal("0"),
    )

    return StatsSummary(
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        income=income,
        expense=expense,
        spending=expense - savings,
        savings=savings,
        net=income - expense,
        transaction_count=len(txs),
        by_category=_breakdown(txs, kind=TransactionKind.EXPENSE, categories=categories),
        income_by_category=_breakdown(txs, kind=TransactionKind.INCOME, categories=categories),
    )


def _period_key(d: date, grain: str) -> str:
    if grain == "day":
        return d.isoformat()
    if grain == "week":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if grain == "month":
        return f"{d.year}-{d.month:02d}"
    return str(d.year)


def _segment_label(
    tx: Transaction | TransactionData,
    group_by: str,
    categories: dict[int | None, str],
    accounts: dict[int, str],
) -> str:
    if group_by == "account":
        return accounts.get(tx.account_id, f"Account {tx.account_id}")
    return categories.get(tx.category_id, "Uncategorized")


@router.get("/timeseries", response_model=TimeseriesResponse)
def timeseries(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    grain: str = Query(default="month", pattern="^(day|week|month|year)$"),
    group_by: str = Query(default="category", pattern="^(category|account)$"),
) -> TimeseriesResponse:
    today = date.today()
    if from_date is None:
        from_date = date(today.year, 1, 1)
    if to_date is None:
        to_date = today
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")

    txs = _load_txs(session, _dek, from_date, to_date)
    category_rows = load_categories(session, _dek)
    categories = {c.id: c.name for c in category_rows}
    categories[None] = "Uncategorized"
    categories_by_name = {c.name: c for c in category_rows}
    accounts = {a.id: a.name for a in load_accounts(session, _dek)}

    # period -> kind -> segment -> amount
    nested: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(
        lambda: {"income": defaultdict(lambda: Decimal("0")), "expense": defaultdict(lambda: Decimal("0"))}
    )
    for t in txs:
        period = _period_key(t.booking_date, grain)
        label = _segment_label(t, group_by, categories, accounts)
        if t.kind == TransactionKind.INCOME:
            nested[period]["income"][label] += t.amount
        else:
            nested[period]["expense"][label] += abs(t.amount)

    def segment(key: str, amount: Decimal) -> TimeseriesSegment:
        if group_by != "category":
            return TimeseriesSegment(key=key, amount=amount)
        category = categories_by_name.get(key)
        return TimeseriesSegment(
            key=key,
            amount=amount,
            category_slug=category.slug if category else UNCATEGORIZED_SLUG,
            color=category.color if category else None,
            color_key=category.color_key if category else "other",
            icon=category.icon if category else "other",
        )

    buckets: list[TimeseriesBucket] = []
    for period in sorted(nested.keys()):
        inc = nested[period]["income"]
        exp = nested[period]["expense"]
        buckets.append(
            TimeseriesBucket(
                period=period,
                income_total=sum(inc.values(), Decimal("0")),
                expense_total=sum(exp.values(), Decimal("0")),
                income_segments=[
                    segment(k, v)
                    for k, v in sorted(inc.items(), key=lambda kv: kv[1], reverse=True)
                ],
                expense_segments=[
                    segment(k, v)
                    for k, v in sorted(exp.items(), key=lambda kv: kv[1], reverse=True)
                ],
            )
        )

    return TimeseriesResponse(
        grain=grain,
        group_by=group_by,
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        buckets=buckets,
    )


@router.get("/flow", response_model=FlowResponse)
def flow(
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    group_by: str = Query(default="category", pattern="^(category|account)$"),
) -> FlowResponse:
    today = date.today()
    if from_date is None:
        from_date = today - timedelta(days=30)
    if to_date is None:
        to_date = today
    if (to_date - from_date).days > 366:
        raise HTTPException(status_code=400, detail="Flow is limited to at most one year")

    txs = _load_txs(session, _dek, from_date, to_date)
    category_rows = load_categories(session, _dek)
    category_meta: dict[int | None, tuple[str, str]] = {
        c.id: (c.name, c.slug) for c in category_rows
    }
    category_meta[None] = ("Uncategorized", UNCATEGORIZED_SLUG)
    category_slugs = {c.id: c.slug for c in category_rows}
    categories_by_slug = {c.slug: c for c in category_rows}
    account_rows = load_accounts(session, _dek)
    accounts = {a.id: a.name for a in account_rows}
    account_sources = {a.id: a.source.value for a in account_rows}
    connection_providers = {
        connection.id: connection.provider
        for connection in session.exec(select(Connection)).all()
        if connection.id is not None
    }
    account_providers = {
        a.id: connection_providers.get(a.connection_id)
        for a in account_rows
    }

    def flow_group(transaction: TransactionData) -> tuple[str, str | None, str | None]:
        if group_by == "account":
            account_id = transaction.account_id
            return (
                accounts.get(account_id, f"Account {account_id}"),
                None,
                str(account_id),
            )
        name, slug = category_meta.get(
            transaction.category_id,
            ("Uncategorized", UNCATEGORIZED_SLUG),
        )
        return name, slug, slug

    income_by_group: dict[tuple[str, str | None, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    expense_by_group: dict[tuple[str, str | None, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    savings_by_group: dict[tuple[str, str | None, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    for t in txs:
        group = flow_group(t)
        if t.kind == TransactionKind.INCOME:
            income_by_group[group] += t.amount
        elif _is_savings_transaction(t, category_slugs):
            savings_by_group[group] += abs(t.amount)
        else:
            expense_by_group[group] += abs(t.amount)

    nodes: list[FlowNode] = []
    links: list[FlowLink] = []
    index: dict[str, int] = {}

    def node(
        name: str,
        role: Literal["hub", "income", "expense", "saving"],
        category_slug: str | None = None,
        group_key: str | None = None,
    ) -> int:
        if name not in index:
            category = categories_by_slug.get(category_slug or "")
            index[name] = len(nodes)
            nodes.append(
                FlowNode(
                    name=name,
                    role=role,
                    category_slug=category_slug,
                    color=category.color if category else None,
                    color_key=category.color_key if category else None,
                    icon=category.icon if category else None,
                    group_by=group_by if role != "hub" else None,
                    group_key=group_key,
                    account_source=(
                        account_sources.get(int(group_key))
                        if group_by == "account" and group_key and group_key.isdigit()
                        else None
                    ),
                    account_provider=(
                        account_providers.get(int(group_key))
                        if group_by == "account" and group_key and group_key.isdigit()
                        else None
                    ),
                )
            )
        return index[name]

    hub = node("Cashflow", "hub")
    for (name, slug, group_key), amount in sorted(income_by_group.items(), key=lambda item: item[1], reverse=True):
        if amount <= 0:
            continue
        links.append(
            FlowLink(source=node(f"In · {name}", "income", slug, group_key), target=hub, value=float(amount))
        )
    # Savings are an outflow, but visually and semantically build wealth rather than consume it.
    # Insert them before expenses so the Sankey layout keeps this branch separately at the top.
    for (name, slug, group_key), amount in sorted(savings_by_group.items(), key=lambda item: item[1], reverse=True):
        if amount <= 0:
            continue
        links.append(
            FlowLink(source=hub, target=node(f"Save · {name}", "saving", slug, group_key), value=float(amount))
        )
    for (name, slug, group_key), amount in sorted(expense_by_group.items(), key=lambda item: item[1], reverse=True):
        if amount <= 0:
            continue
        links.append(
            FlowLink(source=hub, target=node(f"Out · {name}", "expense", slug, group_key), value=float(amount))
        )
    return FlowResponse(
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
        group_by=group_by,
        nodes=nodes,
        links=links,
    )
