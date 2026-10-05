"""Read-only LangChain agent for questions about local finance data."""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import AsyncIterator, Callable
from contextlib import nullcontext
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ContextManager

from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core._api import LangChainBetaWarning
from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langchain_quickjs import CodeInterpreterMiddleware
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.config import get_settings
from app.models import (
    Account,
    AssetPositionSnapshot,
    Category,
    Portfolio,
    Tag,
    Transaction,
    TransactionEmbedding,
    TransactionTag,
)
from app.models.enums import TagType, TransactionKind
from app.schemas.agent import AgentMessage
from app.services.llm_categorize import search_web_safely
from app.services.embeddings import (
    find_similar_transaction_embeddings,
    search_transaction_embeddings,
)
from app.services.secure_accounts import decode_account
from app.services.secure_labels import decode_category, decode_tag, find_tag_by_name, insert_assignment_payload, insert_tag_payload
from app.services.secure_portfolios import decode_portfolio, decode_position
from app.services.secure_transactions import decode_transaction, load_transactions
from app.services.vault_session import vault_session

SYSTEM_PROMPT = """You are the private finance adviser in finsight. Be clear and calm, and respond in
the user's language. All available financial records are stored locally.

Use tools before making claims about amounts, accounts or transactions. Never invent financial data.
State the period used and explain incomplete or ambiguous data. Transfer and ignored transactions
are excluded from income and expenses. Plan your own research and combine tools as needed. Tags
are useful but potentially incomplete clues; a missing tag does not prove that no matching
transactions exist. Never end a contextual search solely because a literal text search failed.
For a trip, project or event, check existing tags and, if evidence is insufficient, load the entire
requested period without a search term, page by page. Evaluate each relevant transaction using
its counterparty, booking text, category, account and provider hints. Follow `next_offset` while
`has_more` is true. Separate confident matches from uncertain ones, explain the selection briefly,
and use the selection calculation tool to sum selected transaction IDs.
Create and assign new tags only after explicit user confirmation. For trip, project or event tags,
first review the complete period and identify the proposed transaction IDs.

Use `render_chart` when a visualization helps, supplying only calculated data. The application
controls colors and layout. A category such as Travel, Shopping or Dining is only a weak clue,
not proof of a transaction's context. Never answer trip, project or event questions using category
totals alone. During the first analysis pass, load all expenses in the relevant period with empty
`query`, empty `category` and no `tag_id`; read each transaction's text and counterparty.
Categories and tags may support your judgment but must not exclude relevant transactions outside
those groups or be accepted without inspection.
Do not announce further research and then stop. Call any necessary tools in the same run. Only
deliver a final answer after the analysis is complete or you can identify the missing information.
Do not give legal, tax or investment guarantees. Financial records are read-only; you cannot change
accounts, amounts or categories. Apart from explicitly confirmed tag operations, describe proposed
changes rather than claiming to have made them.
Be concise but include the figures needed to understand your answer. Use restrained Markdown and
tables only when they make a comparison clearer.

If a counterparty's identity or industry matters and is unclear from local records, use
`search_merchant_web`. Search only for merchants, brands or publicly known business names.
Never pass an IBAN, account number, email address, phone number, card details or the name of a
likely private individual. Web results are supporting evidence; explain uncertainty and do not
claim that a result proves the purpose of a personal transaction.

Choose transaction search tools deliberately. `listTransactions` performs literal text search
with optional filters; use it first for a specified name or exact description.
`semanticSearchTransactions` finds conceptual matches using encrypted embeddings, for queries
such as "something similar", "spending on my Portugal trip" or unfamiliar synonyms.
`hybridSearchTransactions` applies an optional literal `text_query` and structured filters first,
then ranks the remaining candidates semantically. Use it when a query combines a concrete anchor
with a broader context. `findSimilarTransactions` starts from a known transaction ID.
Date, account, category, tag and direction filters apply before semantic ranking. Semantic
similarity does not replace exact arithmetic: pass selected IDs to `calculateTransactionSelection`.
If embeddings are missing or the local embedding model is unavailable, explain this and fall back
to literal search or a full review of the requested period.

`code_interpreter` is a general, isolated calculation and analysis tool. It exposes the approved
read-only finance tools through `tools.*`. Use it whenever you need multiple pages, grouping,
addition, subtraction, multiplication, division, rounding, comparisons, totals, averages, shares,
percentages, changes, projections or any other derived values. Load, filter and calculate within
the same interpreter call instead of copying large result lists into the model context.
Tool results are structured JavaScript objects: use `await tools.<name>({...})` directly without
parsing again. For transaction lists, follow the exact `next_offset` field in a loop until
`has_more` is false. Never calculate in the language model or estimate arithmetic.
You may repeat a value already calculated by a finance tool without modifying it.

The JavaScript tool names differ from their Python names: `listAccounts`, `listAssetPositions`,
`getFinanceSummary`, `listTags`, `listTransactions`, `semanticSearchTransactions`,
`hybridSearchTransactions`, `findSimilarTransactions` and `calculateTransactionSelection`.
Never use underscores in `tools.*` names. `getFinanceSummary` accepts only `from_date`, `to_date`
and optional `account_id`; it cannot filter an individual category. For monthly or other grouped
category analyses, call `listTransactions` with `kind: "expense"` and at most `limit: 50`,
iterate over `page.results`, group in code and set `offset = page.next_offset`.
Do not invent fields: transaction rows are in `results`, never `transactions`.

Never treat money as JavaScript floating-point numbers. Finance tools return amounts as decimal
strings with two decimal places. Remove the decimal point, convert to integer cents with `BigInt`,
calculate only with these integers and format the final result with two decimal places.
Calculate each currency separately and never mix currencies. Return compact JSON containing the
period, filters, count, subgroups and grand total. Verify that subgroup totals exactly equal the
grand total and report any discrepancy. The interpreter has no direct access to files, network
or system commands. Report its result faithfully without adjusting it yourself.
Never print transaction lists with `console.log`; the final JavaScript expression must be the
compact result. A `null` result, error or truncated output is not a completed analysis: correct
the code and call the interpreter again in the same run before answering.
Never use `parseFloat`, `Number`, `toFixed` or floating-point accumulators for money. Do not use
`Date` for YYYY-MM-DD values; extract the month with `tx.date.slice(0, 7)`.

Use this pattern for paginated grouping, adapting the filters and grouping keys:
```javascript
const toCents = value => BigInt(value.replace(".", ""));
const absolute = value => value < 0n ? -value : value;
const money = value => `${value / 100n}.${(value % 100n).toString().padStart(2, "0")}`;
let offset = 0;
let count = 0;
const groups = {};
const totals = {};
while (true) {
  const page = await tools.listTransactions({
    from_date: "YYYY-MM-DD", to_date: "YYYY-MM-DD", category: "CATEGORY",
    kind: "expense", query: "", limit: 50, offset
  });
  for (const tx of page.results) {
    const cents = absolute(toCents(tx.amount));
    const key = `${tx.currency}:${tx.date.slice(0, 7)}`;
    groups[key] = (groups[key] || 0n) + cents;
    totals[tx.currency] = (totals[tx.currency] || 0n) + cents;
    count += 1;
  }
  if (!page.has_more) break;
  offset = page.next_offset;
}
const reconciled = Object.entries(totals).every(([currency, total]) =>
  Object.entries(groups)
    .filter(([key]) => key.startsWith(`${currency}:`))
    .reduce((sum, [, value]) => sum + value, 0n) === total
);
JSON.stringify({
  count,
  groups: Object.fromEntries(Object.entries(groups).map(([key, value]) => [key, money(value)])),
  totals: Object.fromEntries(Object.entries(totals).map(([key, value]) => [key, money(value)])),
  reconciled
});
```"""

SUMMARY_PROMPT = """Summarize this conversation concisely for a private finance adviser.
Preserve specific periods, accounts, amounts, user preferences, conclusions and open questions.
Do not invent information; omit small talk and repetition. This summary will replace older
messages so the financial conversation can continue without losing relevant context.
Use the user\'s language and return only the summary.

Previous messages:
{messages}"""


def _runtime_system_prompt(
    current_date: date,
    timezone: str,
    *,
    web_search_enabled: bool = True,
) -> str:
    month_start = current_date.replace(day=1)
    next_month = (
        date(current_date.year + 1, 1, 1)
        if current_date.month == 12
        else date(current_date.year, current_date.month + 1, 1)
    )
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    web_status = (
        "Web search is enabled for this request. Follow the rules above."
        if web_search_enabled
        else "Web search is disabled for this request. Do not use any public web tool. Mention this only when relevant to the answer."
    )
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"{web_status}\n"
        "Authoritative current date context:\n"
        f"- User's local date: {current_date.isoformat()}\n"
        f"- Browser timezone: {timezone}\n"
        f"- Month to date: {month_start.isoformat()} to {current_date.isoformat()}\n"
        f"- Full current month: {month_start.isoformat()} to "
        f"{(next_month - timedelta(days=1)).isoformat()}\n"
        f"- Previous month: {previous_month_start.isoformat()} to "
        f"{previous_month_end.isoformat()}\n"
        f"- Year to date: {current_date.year}-01-01 to {current_date.isoformat()}\n"
        "Use these dates to resolve relative terms such as today, this month, last month and this year. "
        "Always pass exact YYYY-MM-DD boundaries to finance tools. Never infer the current date "
        "from training knowledge."
    )


def _parse_date(value: str | None, *, fallback: date) -> date:
    if not value:
        return fallback
    return date.fromisoformat(value)


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _result(value: Any) -> Any:
    """Keep host-tool results structured for programmatic calls inside QuickJS."""
    return value


_SENSITIVE_HINT_PARTS = {
    "authorization",
    "cookie",
    "credential",
    "deviceid",
    "password",
    "pin",
    "secret",
    "session",
    "token",
}
_SEMANTIC_HINT_PARTS = {
    "airport",
    "category",
    "city",
    "country",
    "location",
    "mcc",
    "merchant",
}


def _provider_hints(payload: dict[str, Any] | None, max_items: int = 16) -> dict[str, str]:
    """Extract compact place/merchant hints without exposing an entire provider payload."""
    hints: dict[str, str] = {}

    def visit(value: Any, path: tuple[str, ...], depth: int) -> None:
        if len(hints) >= max_items or depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = "".join(character for character in str(key).lower() if character.isalnum())
                if any(part in normalized for part in _SENSITIVE_HINT_PARTS):
                    continue
                visit(child, (*path, str(key)), depth + 1)
            return
        if isinstance(value, list):
            for index, child in enumerate(value[:5]):
                visit(child, (*path, str(index)), depth + 1)
            return
        if value is None or not path:
            return
        normalized_path = "".join(
            character for segment in path for character in segment.lower() if character.isalnum()
        )
        if not any(part in normalized_path for part in _SEMANTIC_HINT_PARTS):
            return
        rendered = str(value).strip()
        if rendered:
            hints[".".join(path)] = rendered[:160]

    visit(payload or {}, (), 0)
    return hints


SessionSource = Session | Callable[[], ContextManager[Session]]


def _all(session_source: SessionSource, statement: Any) -> list[Any]:
    """Materialize a query in an invocation-local session for thread-safe PTC calls."""
    context = session_source() if callable(session_source) else nullcontext(session_source)
    with context as session:
        return list(session.exec(statement).all())


def _secure_transactions(
    session_source: SessionSource,
    dek: bytes,
    **filters: Any,
):
    context = session_source() if callable(session_source) else nullcontext(session_source)
    with context as session:
        return load_transactions(session, dek, **filters)


def _build_tools(
    session_source: SessionSource,
    current_date: date | None = None,
    dek: bytes | None = None,
    web_search_enabled: bool = True,
):
    reference_date = current_date or date.today()

    @tool
    def search_merchant_web(query: str) -> str:
        """Search public web results for an unclear merchant, brand or business purpose.

        Use only public merchant/brand keywords. Never pass an IBAN, account or card number, email,
        phone number, transaction reference, or a likely private person's name. Search results are
        supporting evidence and do not prove what the user personally purchased.
        """
        return search_web_safely(query)

    @tool
    def list_accounts() -> list[dict[str, Any]]:
        """List active accounts and their latest provider-reported balances.

        A missing balance is unknown, not zero. Balances are current account state and must not be
        reconstructed by summing an incomplete transaction period.
        """
        stored_accounts = _all(
            session_source,
            select(Account).where(Account.is_active.is_(True)).order_by(Account.id)  # type: ignore[union-attr]
        )
        if dek is None:
            return _result({"error": "Vault is locked"})
        accounts = [decode_account(account, dek) for account in stored_accounts]
        accounts.sort(key=lambda account: account.name.casefold())
        return _result(
            [
                {
                    "id": account.id,
                    "name": account.name,
                    "source": account.source.value,
                    "type": account.account_type.value,
                    "currency": account.currency,
                    "current_balance": (
                        str(account.current_balance)
                        if account.current_balance is not None
                        else None
                    ),
                    "available_balance": (
                        str(account.available_balance)
                        if account.available_balance is not None
                        else None
                    ),
                    "balance_updated_at": (
                        account.balance_updated_at.isoformat()
                        if account.balance_updated_at is not None
                        else None
                    ),
                }
                for account in accounts
            ]
        )

    @tool
    def list_asset_positions() -> list[dict[str, Any]]:
        """List the latest read-only investment positions, excluding all cash balances."""
        stored_portfolios = _all(session_source, select(Portfolio).order_by(Portfolio.id))
        if dek is None:
            return _result({"error": "Vault is locked"})
        portfolios = [decode_portfolio(item, dek) for item in stored_portfolios]
        portfolios.sort(key=lambda item: item.name.casefold())
        result: list[dict[str, Any]] = []
        for portfolio in portfolios:
            stored_positions = (
                _all(
                    session_source,
                    select(AssetPositionSnapshot)
                    .where(
                        AssetPositionSnapshot.portfolio_id == portfolio.id,
                        AssetPositionSnapshot.captured_at == portfolio.last_synced_at,
                    )
                    .order_by(AssetPositionSnapshot.id),
                )
                if portfolio.last_synced_at is not None
                else []
            )
            positions = [decode_position(item, dek) for item in stored_positions]
            positions.sort(
                key=lambda item: item.market_value or Decimal("0"), reverse=True
            )
            result.append(
                {
                    "portfolio": portfolio.name,
                    "source": portfolio.source.value,
                    "currency": portfolio.currency,
                    "as_of": (
                        portfolio.last_synced_at.isoformat()
                        if portfolio.last_synced_at is not None
                        else None
                    ),
                    "positions": [
                        {
                            "name": position.name,
                            "isin": position.isin,
                            "asset_type": position.asset_type,
                            "quantity": str(position.quantity),
                            "average_buy_in": (
                                str(position.average_buy_in)
                                if position.average_buy_in is not None
                                else None
                            ),
                            "current_price": (
                                str(position.current_price)
                                if position.current_price is not None
                                else None
                            ),
                            "market_value": (
                                str(position.market_value)
                                if position.market_value is not None
                                else None
                            ),
                            "currency": position.currency,
                        }
                        for position in positions
                    ],
                }
            )
        return _result(result)

    @tool
    def get_finance_summary(
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Calculate income, expenses, net cashflow and expense categories for a date range.

        Dates must use YYYY-MM-DD. Empty dates default to January 1 of the current year and today.
        Pass account_id only when the user asks about one particular account.
        This aggregate is not sufficient for attributing transactions to a personal context such as
        a particular trip, project or event. Use list_transactions and inspect the individual entries
        for those questions; a category total alone cannot establish contextual membership.
        """
        today = reference_date
        try:
            start = _parse_date(from_date, fallback=date(today.year, 1, 1))
            end = _parse_date(to_date, fallback=today)
        except ValueError:
            return _result({"error": "Dates must use YYYY-MM-DD"})
        if start > end:
            return _result({"error": "from_date must not be after to_date"})

        if dek is None:
            return _result({"error": "Vault is locked"})
        transactions = [
            transaction
            for transaction in _secure_transactions(
                session_source, dek, from_date=start, to_date=end,
                account_id=account_id,
            )
            if transaction.kind in (TransactionKind.INCOME, TransactionKind.EXPENSE)
        ]
        stored_categories = _all(session_source, select(Category))
        categories = {
            category.id: category.name
            for category in [decode_category(item, dek) for item in stored_categories]
        }

        currency_totals: dict[str, dict[str, Decimal]] = {}
        category_totals: dict[tuple[str, str], Decimal] = {}
        for tx in transactions:
            totals = currency_totals.setdefault(
                tx.currency,
                {"income": Decimal("0"), "expenses": Decimal("0")},
            )
            if tx.kind == TransactionKind.INCOME:
                totals["income"] += tx.amount
            if tx.kind != TransactionKind.EXPENSE:
                continue
            totals["expenses"] += abs(tx.amount)
            name = categories.get(tx.category_id, "Unkategorisiert")
            key = (tx.currency, name)
            category_totals[key] = category_totals.get(key, Decimal("0")) + abs(tx.amount)

        return _result(
            {
                "from": start,
                "to": end,
                "account_id": account_id,
                "transaction_count": len(transactions),
                "totals_by_currency": [
                    {
                        "currency": currency,
                        "income": _money(totals["income"]),
                        "expenses": _money(totals["expenses"]),
                        "net": _money(totals["income"] - totals["expenses"]),
                    }
                    for currency, totals in sorted(currency_totals.items())
                ],
                "expense_categories": [
                    {"currency": currency, "category": name, "amount": _money(amount)}
                    for (currency, name), amount in sorted(
                        category_totals.items(), key=lambda item: item[1], reverse=True
                    )
                ],
            }
        )

    @tool
    def render_chart(
        chart_type: str,
        title: str,
        labels: list[str],
        series: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build a safe chart specification for the chat UI.

        Allowed types are line, bar, stacked_bar and donut. Series may contain only
        name and numeric values; visual colors are assigned by the frontend schema.
        """
        allowed = {"line", "bar", "stacked_bar", "donut"}
        if chart_type not in allowed:
            return _result({"error": f"chart_type must be one of {sorted(allowed)}"})
        if not labels or len(labels) > 120 or not series or len(series) > 8:
            return _result({"error": "Chart has invalid labels or series"})
        normalized = []
        for item in series:
            values = item.get("values") if isinstance(item, dict) else None
            if not isinstance(values, list) or len(values) != len(labels):
                return _result({"error": "Every series must contain one numeric value per label"})
            try:
                normalized.append({"name": str(item.get("name") or "Series"), "values": [float(value) for value in values]})
            except (TypeError, ValueError):
                return _result({"error": "Chart values must be numeric"})
        return _result({"chart": {"type": chart_type, "title": title[:160], "labels": labels, "series": normalized}, "render_hint": "Include this chart in your response as a ```chart JSON``` block."})

    @tool
    def create_tag(
        name: str,
        tag_type: str = "general",
        from_date: str = "",
        to_date: str = "",
        confirmed: bool = False,
        transaction_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Create a contextual tag after explicit user confirmation."""
        if not confirmed:
            return _result({"needs_confirmation": True, "name": name, "tag_type": tag_type, "from_date": from_date or None, "to_date": to_date or None, "transaction_ids": transaction_ids or []})
        try:
            parsed_type = TagType(tag_type.strip().lower() or "general")
            start = _parse_date(from_date) if from_date.strip() else None
            end = _parse_date(to_date) if to_date.strip() else None
        except (ValueError, TypeError):
            return _result({"error": "Tag type or date is invalid."})
        if start and end and start > end:
            return _result({"error": "from_date must not be after to_date"})
        clean_name = name.strip()
        if not clean_name:
            return _result({"error": "Tag name must not be empty"})
        if find_tag_by_name(session_source, dek, clean_name):
            return _result({"error": "Tag already exists", "name": clean_name})
        tag = insert_tag_payload(session_source, dek, name=clean_name, tag_type=parsed_type, color="#b9c8ea", from_date=start, to_date=end, created_by="agent")
        session_source.commit()
        session_source.refresh(tag)
        created = decode_tag(tag, dek)
        assigned = 0
        for transaction_id in transaction_ids or []:
            if not session_source.get(Transaction, transaction_id):
                continue
            insert_assignment_payload(session_source, dek, transaction_id=transaction_id, tag_id=created.id)
            assigned += 1
        session_source.commit()
        return _result({"created": True, "id": created.id, "name": created.name, "type": created.tag_type.value, "from_date": created.from_date, "to_date": created.to_date, "assigned_transaction_count": assigned})

    @tool
    def list_tags(
        query: str = "",
        tag_type: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """List contextual tags and their assignment counts.

        Tags can identify trips, projects or other personal contexts, but may be incomplete. query
        optionally matches a tag name. tag_type can be general, trip or project. Never conclude that
        no related transactions exist merely because this tool finds no matching tag.
        """
        stored_tags = _all(session_source, select(Tag))
        if dek is None:
            return _result({"error": "Vault is locked"})
        rows = [decode_tag(item, dek) for item in stored_tags]
        if query.strip():
            needle = query.strip().casefold()
            rows = [tag for tag in rows if needle in tag.name.casefold()]
        if tag_type.strip():
            try:
                parsed_type = TagType(tag_type.strip().lower())
            except ValueError:
                return _result({"error": "tag_type must be general, trip or project"})
            rows = [tag for tag in rows if tag.tag_type == parsed_type]
        rows = sorted(rows, key=lambda tag: tag.name.casefold())[: max(1, min(limit, 100))]
        tag_ids = [tag.id for tag in rows if tag.id is not None]
        counts: dict[int, int] = {}
        if tag_ids:
            counts = dict(
                _all(
                    session_source,
                    select(TransactionTag.tag_id, func.count(TransactionTag.id))
                    .where(col(TransactionTag.tag_id).in_(tag_ids))
                    .group_by(TransactionTag.tag_id),
                )
            )
        return _result(
            {
                "results": [
                    {
                        "id": tag.id,
                        "name": tag.name,
                        "type": tag.tag_type.value,
                        "from_date": tag.from_date,
                        "to_date": tag.to_date,
                        "assignment_count": counts.get(tag.id or -1, 0),
                    }
                    for tag in rows
                ]
            }
        )

    @tool
    def list_transactions(
        query: str = "",
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
        category: str = "",
        tag_id: int | None = None,
        kind: str = "",
        limit: int = 40,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List individual transactions for autonomous financial research.

        Dates use YYYY-MM-DD. Leave query empty to inspect every transaction in a period; this is
        required when a concept such as a trip is not encoded literally in booking text. query is an
        optional exact substring filter for booking text or counterparty. account_id comes from
        list_accounts, tag_id from list_tags, and category matches a category name. kind can be
        expense, income, transfer or ignore. Results are newest first. Follow next_offset until
        has_more is false whenever full coverage is needed. For a trip, project or event, the first
        pass must leave query and category empty and tag_id unset so every expense can be inspected;
        category and tag values are evidence, not authoritative membership. The returned object stores
        booking rows only in `results` (never `transactions`), plus `returned`, `has_more`, and the exact
        `next_offset`. The effective maximum page size is 50 even if a larger limit is requested.
        """
        today = reference_date
        try:
            start = _parse_date(from_date, fallback=date(today.year, 1, 1))
            end = _parse_date(to_date, fallback=today)
        except ValueError:
            return _result({"error": "Dates must use YYYY-MM-DD"})
        if start > end:
            return _result({"error": "from_date must not be after to_date"})

        parsed_kind: TransactionKind | None = None
        if kind.strip():
            try:
                parsed_kind = TransactionKind(kind.strip().lower())
            except ValueError:
                return _result({"error": "kind must be expense, income, transfer or ignore"})

        if dek is None:
            return _result({"error": "Vault is locked"})
        transactions = _secure_transactions(
            session_source, dek, from_date=start, to_date=end,
            account_id=account_id, kind=parsed_kind,
        )

        stored_accounts = _all(session_source, select(Account))
        accounts = {
            account.id: account
            for account in [decode_account(item, dek) for item in stored_accounts]
        }
        stored_categories = _all(session_source, select(Category))
        categories = {
            category_row.id: category_row
            for category_row in [decode_category(item, dek) for item in stored_categories]
        }
        allowed_tag_transaction_ids: set[int] | None = None
        if tag_id is not None:
            allowed_tag_transaction_ids = set(
                _all(
                    session_source,
                    select(TransactionTag.transaction_id).where(
                        TransactionTag.tag_id == tag_id
                    ),
                )
            )
        if query.strip():
            needle = query.strip().casefold()
            transactions = [
                transaction
                for transaction in transactions
                if needle in transaction.raw_text.casefold()
                or needle in (transaction.counterparty or "").casefold()
            ]
        if category.strip():
            category_needle = category.strip().casefold()
            transactions = [
                transaction
                for transaction in transactions
                if category_needle
                in (categories.get(transaction.category_id).name if categories.get(transaction.category_id) else "").casefold()
            ]
        if allowed_tag_transaction_ids is not None:
            transactions = [
                transaction
                for transaction in transactions
                if transaction.id in allowed_tag_transaction_ids
            ]
        transactions.sort(
            key=lambda transaction: (transaction.booking_date, transaction.id or 0),
            reverse=True,
        )

        page_size = max(1, min(limit, 50))
        safe_offset = max(0, offset)
        fetched = transactions[safe_offset : safe_offset + page_size + 1]
        has_more = len(fetched) > page_size
        rows = fetched[:page_size]
        transaction_ids = [tx.id for tx in rows]
        tags_by_transaction: dict[int, list[dict[str, Any]]] = {}
        if transaction_ids:
            assignment_rows = _all(
                session_source,
                select(TransactionTag.transaction_id, TransactionTag.tag_id)
                .where(col(TransactionTag.transaction_id).in_(transaction_ids))
            )
            stored_tags = _all(session_source, select(Tag))
            tag_lookup = {
                tag.id: tag
                for tag in [decode_tag(item, dek) for item in stored_tags]
            }
            for transaction_id, assigned_tag_id in assignment_rows:
                assigned_tag = tag_lookup.get(assigned_tag_id)
                if assigned_tag is None:
                    continue
                tags_by_transaction.setdefault(transaction_id, []).append(
                    {
                        "id": assigned_tag_id,
                        "name": assigned_tag.name,
                        "type": assigned_tag.tag_type.value,
                    }
                )
        return _result(
            {
                "from": start,
                "to": end,
                "offset": safe_offset,
                "returned": len(rows),
                "has_more": has_more,
                "next_offset": safe_offset + len(rows) if has_more else None,
                "scope": {
                    "query": query.strip() or None,
                    "category": category.strip() or None,
                    "tag_id": tag_id,
                    "kind": kind.strip().lower() or None,
                    "is_unfiltered_context_scan": not query.strip()
                    and not category.strip()
                    and tag_id is None,
                },
                "results": [
                    {
                        "id": tx.id,
                        "date": tx.booking_date,
                        "amount": _money(tx.amount),
                        "currency": tx.currency,
                        "kind": tx.kind.value,
                        "counterparty": tx.counterparty,
                        "text": tx.raw_text[:500],
                        "account": account.name,
                        "account_id": account.id,
                        "account_source": account.source.value,
                        "category": category_row.name if category_row else "Unkategorisiert",
                        "tags": tags_by_transaction.get(tx.id or -1, []),
                        "provider_hints": _provider_hints(tx.raw_payload),
                    }
                    for tx in rows
                    if (account := accounts.get(tx.account_id)) is not None
                    for category_row in [categories.get(tx.category_id)]
                ],
            }
        )

    def _semantic_search_result(
        *,
        query: str = "",
        text_query: str = "",
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
        category: str = "",
        tag_id: int | None = None,
        kind: str = "",
        limit: int = 20,
        similar_transaction_id: int | None = None,
    ) -> dict[str, Any]:
        """Apply structured filters before the encrypted in-memory vector scan."""
        if dek is None:
            return {"error": "Vault is locked"}
        if similar_transaction_id is None and not query.strip():
            return {"error": "query must not be empty"}
        try:
            start = date.fromisoformat(from_date) if from_date.strip() else None
            end = date.fromisoformat(to_date) if to_date.strip() else None
        except ValueError:
            return {"error": "Dates must use YYYY-MM-DD"}
        if start and end and start > end:
            return {"error": "from_date must not be after to_date"}
        parsed_kind: TransactionKind | None = None
        if kind.strip():
            try:
                parsed_kind = TransactionKind(kind.strip().lower())
            except ValueError:
                return {"error": "kind must be expense, income, transfer or ignore"}

        context = session_source() if callable(session_source) else nullcontext(session_source)
        with context as session:
            transactions = load_transactions(
                session,
                dek,
                from_date=start,
                to_date=end,
                account_id=account_id,
                kind=parsed_kind,
                search=text_query.strip() or None,
            )
            stored_categories = _all(session_source, select(Category))
            categories = {
                row.id: row for row in [decode_category(item, dek) for item in stored_categories]
            }
            if category.strip():
                category_needle = category.strip().casefold()
                transactions = [
                    tx for tx in transactions
                    if category_needle in (categories.get(tx.category_id).name if categories.get(tx.category_id) else "").casefold()
                ]
            if tag_id is not None:
                allowed_ids = set(
                    _all(
                        session_source,
                        select(TransactionTag.transaction_id).where(TransactionTag.tag_id == tag_id),
                    )
                )
                transactions = [tx for tx in transactions if tx.id in allowed_ids]

            if similar_transaction_id is not None:
                ranked = find_similar_transaction_embeddings(
                    session,
                    dek,
                    similar_transaction_id,
                    transactions,
                    limit=limit,
                )
                mode = "similar"
            else:
                if transactions:
                    embedding_exists = session.exec(
                        select(TransactionEmbedding.id)
                        .where(TransactionEmbedding.transaction_id.in_([tx.id for tx in transactions]))
                        .limit(1)
                    ).first()
                    if embedding_exists is None:
                        return {
                            "mode": "hybrid" if text_query.strip() else "semantic",
                            "query": query.strip() or None,
                            "text_query": text_query.strip() or None,
                            "returned": 0,
                            "results": [],
                            "reason": "No transaction embeddings available; run the embedding backfill first.",
                        }
                try:
                    ranked = search_transaction_embeddings(
                        session,
                        dek,
                        query,
                        transactions,
                        limit=limit,
                    )
                except (RuntimeError, ValueError) as exc:
                    return {"error": f"Semantic search unavailable: {exc}"}
                mode = "hybrid" if text_query.strip() else "semantic"

            scores = {int(item["transaction_id"]): float(item["similarity"]) for item in ranked}
            if not scores:
                return {
                    "mode": mode,
                    "query": query.strip() or None,
                    "text_query": text_query.strip() or None,
                    "returned": 0,
                    "results": [],
                    "reason": "No semantically similar transactions found.",
                }
            stored_accounts = _all(session_source, select(Account))
            accounts = {
                row.id: row for row in [decode_account(item, dek) for item in stored_accounts]
            }
            ids = list(scores)
            assignment_rows = _all(
                session_source,
                select(TransactionTag.transaction_id, TransactionTag.tag_id).where(
                    col(TransactionTag.transaction_id).in_(ids)
                ),
            )
            stored_tags = _all(session_source, select(Tag))
            tags = {row.id: row for row in [decode_tag(item, dek) for item in stored_tags]}
            tags_by_transaction: dict[int, list[dict[str, Any]]] = {}
            for tx_id, assigned_tag_id in assignment_rows:
                tag = tags.get(assigned_tag_id)
                if tag is not None:
                    tags_by_transaction.setdefault(tx_id, []).append(
                        {"id": assigned_tag_id, "name": tag.name, "type": tag.tag_type.value}
                    )
            transaction_by_id = {tx.id: tx for tx in transactions}
            results = []
            for tx_id, similarity in sorted(scores.items(), key=lambda item: item[1], reverse=True):
                tx = transaction_by_id.get(tx_id)
                account = accounts.get(tx.account_id) if tx else None
                if tx is None or account is None:
                    continue
                category_row = categories.get(tx.category_id)
                results.append(
                    {
                        "id": tx.id,
                        "date": tx.booking_date,
                        "amount": _money(tx.amount),
                        "currency": tx.currency,
                        "kind": tx.kind.value,
                        "counterparty": tx.counterparty,
                        "text": tx.raw_text[:500],
                        "account": account.name,
                        "account_id": account.id,
                        "account_source": account.source.value,
                        "category": category_row.name if category_row else "Unkategorisiert",
                        "tags": tags_by_transaction.get(tx.id or -1, []),
                        "provider_hints": _provider_hints(tx.raw_payload),
                        "similarity": round(similarity, 4),
                        "match_type": "semantic",
                    }
                )
            return {
                "mode": mode,
                "query": query.strip() or None,
                "text_query": text_query.strip() or None,
                "from": start,
                "to": end,
                "returned": len(results),
                "results": results,
            }

    @tool
    def semantic_search_transactions(
        query: str,
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
        category: str = "",
        tag_id: int | None = None,
        kind: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Find semantically similar transactions using encrypted local embeddings.

        Use this for concepts, synonyms and personal contexts that are not necessarily written
        literally in a booking. Dates, account, category, tag and kind are applied first. Results
        contain transaction ids and a similarity score; use calculate_transaction_selection for
        exact totals. This searches the whole local history when no dates are supplied.
        """
        return _result(
            _semantic_search_result(
                query=query,
                from_date=from_date,
                to_date=to_date,
                account_id=account_id,
                category=category,
                tag_id=tag_id,
                kind=kind,
                limit=limit,
            )
        )

    @tool
    def hybrid_search_transactions(
        query: str,
        text_query: str = "",
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
        category: str = "",
        tag_id: int | None = None,
        kind: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Filter by an optional literal text query, then rank those candidates semantically.

        Use this when the user gives both a concrete anchor (for example a merchant word) and a
        broader intent (for example similar travel purchases). Leave text_query empty for a pure
        semantic search. The literal prefilter is applied before embeddings are compared.
        """
        return _result(
            _semantic_search_result(
                query=query,
                text_query=text_query,
                from_date=from_date,
                to_date=to_date,
                account_id=account_id,
                category=category,
                tag_id=tag_id,
                kind=kind,
                limit=limit,
            )
        )

    @tool
    def find_similar_transactions(
        transaction_id: int,
        from_date: str = "",
        to_date: str = "",
        account_id: int | None = None,
        kind: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Find transactions similar to one known transaction id without re-embedding the query."""
        return _result(
            _semantic_search_result(
                from_date=from_date,
                to_date=to_date,
                account_id=account_id,
                kind=kind,
                limit=limit,
                similar_transaction_id=transaction_id,
            )
        )

    @tool
    def calculate_transaction_selection(transaction_ids: list[int]) -> dict[str, Any]:
        """Calculate exact totals for transaction ids selected during research.

        Use this after semantically deciding which transactions answer the user's question. Do not
        add displayed amounts yourself. The result reports missing ids and separates expenses,
        income, transfers and the signed total by currency. Maximum 200 unique ids per call.
        """
        unique_ids = list(dict.fromkeys(transaction_ids))
        if not unique_ids:
            return _result({"error": "transaction_ids must not be empty"})
        if len(unique_ids) > 200:
            return _result({"error": "maximum 200 unique transaction ids per call"})
        stored_rows = _all(
            session_source,
            select(Transaction)
            .where(col(Transaction.id).in_(unique_ids))
        )
        if dek is None:
            return _result({"error": "Vault is locked"})
        rows = [decode_transaction(row, dek) for row in stored_rows]
        rows.sort(key=lambda transaction: (transaction.booking_date, transaction.id or 0))
        stored_accounts = _all(session_source, select(Account))
        accounts = {
            account.id: account
            for account in [decode_account(item, dek) for item in stored_accounts]
        }
        stored_categories = _all(session_source, select(Category))
        categories = {
            category_row.id: category_row
            for category_row in [decode_category(item, dek) for item in stored_categories]
        }
        found_ids = {tx.id for tx in rows if tx.id is not None}
        totals: dict[str, dict[str, Decimal | int]] = {}
        for tx in rows:
            currency_totals = totals.setdefault(
                tx.currency,
                {
                    "expenses": Decimal("0"),
                    "income": Decimal("0"),
                    "transfers": Decimal("0"),
                    "signed_total": Decimal("0"),
                    "count": 0,
                },
            )
            currency_totals["count"] += 1
            currency_totals["signed_total"] += tx.amount
            if tx.kind == TransactionKind.EXPENSE:
                currency_totals["expenses"] += abs(tx.amount)
            elif tx.kind == TransactionKind.INCOME:
                currency_totals["income"] += tx.amount
            elif tx.kind == TransactionKind.TRANSFER:
                currency_totals["transfers"] += abs(tx.amount)
        return _result(
            {
                "selected_count": len(rows),
                "missing_ids": [item for item in unique_ids if item not in found_ids],
                "totals_by_currency": [
                    {
                        "currency": currency,
                        "count": values["count"],
                        "expenses": _money(values["expenses"]),
                        "income": _money(values["income"]),
                        "transfers": _money(values["transfers"]),
                        "signed_total": _money(values["signed_total"]),
                    }
                    for currency, values in sorted(totals.items())
                ],
                "transactions": [
                    {
                        "id": tx.id,
                        "date": tx.booking_date,
                        "amount": _money(tx.amount),
                        "currency": tx.currency,
                        "kind": tx.kind.value,
                        "counterparty": tx.counterparty,
                        "account": account.name,
                        "category": category_row.name if category_row else "Unkategorisiert",
                    }
                    for tx in rows
                    if (account := accounts.get(tx.account_id)) is not None
                    for category_row in [categories.get(tx.category_id)]
                ],
            }
        )

    tools = [
        list_accounts,
        list_asset_positions,
        get_finance_summary,
        render_chart,
        create_tag,
        list_tags,
        list_transactions,
        semantic_search_transactions,
        hybrid_search_transactions,
        find_similar_transactions,
        calculate_transaction_selection,
    ]
    if web_search_enabled:
        tools.insert(0, search_merchant_web)
    return tools


_PTC_TOOL_NAMES = frozenset(
    {
        "list_accounts",
        "list_asset_positions",
        "get_finance_summary",
        "render_chart",
        "create_tag",
        "list_tags",
        "list_transactions",
        "semantic_search_transactions",
        "hybrid_search_transactions",
        "find_similar_transactions",
        "calculate_transaction_selection",
    }
)


def _code_interpreter_middleware(ptc_tools: list[Any] | None = None) -> CodeInterpreterMiddleware:
    """Create the intentionally beta interpreter without logging a warning per chat request."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", LangChainBetaWarning)
        return CodeInterpreterMiddleware(
            tool_name="code_interpreter",
            mode="call",
            timeout=3.0,
            memory_limit=16 * 1024 * 1024,
            max_result_chars=8_000,
            max_ptc_calls=64,
            capture_console=True,
            ptc=[tool for tool in ptc_tools or [] if tool.name in _PTC_TOOL_NAMES] or None,
            subagents=False,
        )


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


# Match model output in both supported UI languages, not just the prompt language.
_UNFINISHED_ANSWER = re.compile(
    r"(?:"
    r"\b(?:werde ich|ich werde|ich führe|ich starte|ich beginne)\b.{0,600}\b(?:nun|jetzt)\b"
    r"|\b(?:i will|i am going to|let me)\b.{0,600}\bnow\b"
    r").{0,600}(?:durch|analysieren|prüfen|laden|suchen|berechnen|analysis|check|load|search)[\s*().]*$",
    re.IGNORECASE | re.DOTALL,
)


def _looks_like_unfinished_answer(content: str) -> bool:
    """Detect a final message that only announces work instead of performing it."""
    return bool(_UNFINISHED_ANSWER.search(content.strip()[-1_200:]))


def _tool_start_event(name: str) -> dict[str, Any]:
    codes = {
        "code_interpreter": "calculation_running",
        "list_accounts": "accounts_loading",
        "get_finance_summary": "summary_calculating",
        "list_tags": "tags_loading",
        "list_transactions": "transactions_loading",
        "semantic_search_transactions": "semantic_searching",
        "hybrid_search_transactions": "semantic_searching",
        "find_similar_transactions": "semantic_searching",
        "calculate_transaction_selection": "selection_calculating",
        "search_merchant_web": "merchant_searching",
    }
    return {"type": "activity", "code": codes.get(name, "tool_running")}


def _tool_complete_event(message: ToolMessage) -> dict[str, Any]:
    name = message.name or ""
    try:
        payload = json.loads(_message_content(message))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if name == "list_tags":
        return {
            "type": "activity",
            "code": "tags_loaded",
            "count": len(payload.get("results") or []),
        }
    if name == "list_transactions":
        return {
            "type": "activity",
            "code": "transactions_loaded",
            "count": int(payload.get("returned") or 0),
            "offset": int(payload.get("offset") or 0),
            "has_more": bool(payload.get("has_more")),
        }
    if name == "calculate_transaction_selection":
        return {
            "type": "activity",
            "code": "selection_calculated",
            "count": int(payload.get("selected_count") or 0),
        }
    if name in {
        "semantic_search_transactions",
        "hybrid_search_transactions",
        "find_similar_transactions",
    }:
        return {
            "type": "activity",
            "code": "semantic_searched",
            "count": int(payload.get("returned") or 0),
        }
    codes = {
        "code_interpreter": "calculation_finished",
        "list_accounts": "accounts_loaded",
        "get_finance_summary": "summary_calculated",
        "search_merchant_web": "merchant_searched",
        "semantic_search_transactions": "semantic_searched",
        "hybrid_search_transactions": "semantic_searched",
        "find_similar_transactions": "semantic_searched",
    }
    return {"type": "activity", "code": codes.get(name, "tool_finished")}


def _compact_context(messages: list[BaseMessage]) -> list[AgentMessage]:
    """Return the reusable conversational state without transient tool-call messages."""
    context: list[AgentMessage] = []
    for message in messages:
        content = _message_content(message)
        if not content:
            continue
        if isinstance(message, HumanMessage):
            if message.additional_kwargs.get("lc_source") == "continuation_guard":
                continue
            role = (
                "summary"
                if message.additional_kwargs.get("lc_source") == "summarization"
                else "user"
            )
            context.append(AgentMessage(role=role, content=content))
        elif (
            isinstance(message, AIMessage)
            and not message.tool_calls
            and not _looks_like_unfinished_answer(content)
        ):
            context.append(AgentMessage(role="assistant", content=content))
    return context


def _create_agent(
    session: Session,
    reference_date: date,
    timezone: str,
    web_search_enabled: bool = True,
):
    from app.db import engine

    settings = get_settings()
    model = ChatOllama(
        base_url=settings.ollama_base_url.rstrip("/"),
        model=settings.ollama_model,
        temperature=0.2,
        num_ctx=settings.ollama_context_window,
        num_predict=settings.ollama_output_tokens,
    )
    trigger_tokens = max(2_000, int(settings.ollama_context_window * 0.70))
    keep_tokens = max(1_000, int(settings.ollama_context_window * 0.25))
    finance_tools = _build_tools(
        lambda: Session(engine),
        reference_date,
        dek=vault_session.get_dek(),
        web_search_enabled=web_search_enabled,
    )
    return create_agent(
        model,
        tools=finance_tools,
        system_prompt=_runtime_system_prompt(
            reference_date,
            timezone,
            web_search_enabled=web_search_enabled,
        ),
        middleware=[
            SummarizationMiddleware(
                model,
                trigger=[("tokens", trigger_tokens), ("messages", 80)],
                keep=("tokens", keep_tokens),
                summary_prompt=SUMMARY_PROMPT,
                trim_tokens_to_summarize=max(2_000, int(settings.ollama_context_window * 0.50)),
            ),
            _code_interpreter_middleware(finance_tools),
        ],
    )


def _langchain_history(messages: list[AgentMessage]) -> list[BaseMessage]:
    return [
        HumanMessage(
            content=item.content,
            additional_kwargs={"lc_source": "summarization"},
        )
        if item.role == "summary"
        else HumanMessage(content=item.content)
        if item.role == "user"
        else AIMessage(content=item.content)
        for item in messages
    ]


async def stream_chat(
    session: Session,
    messages: list[AgentMessage],
    current_date: date | None = None,
    timezone: str = "UTC",
    web_search_enabled: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Stream safe activity updates, answer tokens and the reusable final context."""
    reference_date = current_date or date.today()
    agent = _create_agent(
        session,
        reference_date,
        timezone,
        web_search_enabled=web_search_enabled,
    )
    history = _langchain_history(messages)

    for attempt in range(2):
        latest_messages: list[BaseMessage] = history
        active_model_step: int | None = None
        async for mode, data in agent.astream(
            {"messages": history},
            stream_mode=["messages", "updates", "values"],
            config={"recursion_limit": 40},
        ):
            if mode == "messages":
                message, metadata = data
                if not isinstance(message, AIMessageChunk):
                    continue
                step = metadata.get("langgraph_step")
                if isinstance(step, int) and step != active_model_step:
                    active_model_step = step
                    yield {"type": "answer_reset"}
                if isinstance(message.content, str) and message.content:
                    yield {"type": "token", "content": message.content}
                continue
            if mode == "values":
                value_messages = data.get("messages") if isinstance(data, dict) else None
                if value_messages:
                    latest_messages = list(value_messages)
                continue
            if mode != "updates" or not isinstance(data, dict):
                continue
            for update in data.values():
                update_messages = update.get("messages") if isinstance(update, dict) else None
                for message in update_messages or []:
                    if isinstance(message, AIMessage):
                        for tool_call in message.tool_calls:
                            yield _tool_start_event(str(tool_call.get("name") or ""))
                    elif isinstance(message, ToolMessage):
                        yield _tool_complete_event(message)

        if not latest_messages:
            raise RuntimeError("The local model returned no response")
        answer = _message_content(latest_messages[-1])
        if not answer:
            raise RuntimeError("The local model returned an empty response")
        if attempt == 0 and _looks_like_unfinished_answer(answer):
            yield {"type": "answer_reset"}
            yield {"type": "activity", "code": "analysis_continuing"}
            history = [
                *latest_messages,
                HumanMessage(
                    content=(
                        "Complete the analysis you just announced using the available tools. "
                        "This is an internal continuation instruction, not a new user question. "
                        "Reply only with the result or a specific obstacle."
                    ),
                    additional_kwargs={"lc_source": "continuation_guard"},
                ),
            ]
            continue
        yield {
            "type": "result",
            "answer": answer,
            "context": _compact_context(latest_messages),
        }
        return
    raise RuntimeError("The local model did not complete the announced analysis")


async def chat(
    session: Session,
    messages: list[AgentMessage],
    current_date: date | None = None,
    timezone: str = "UTC",
    web_search_enabled: bool = True,
) -> tuple[str, list[AgentMessage]]:
    """Run one conversational turn against the configured local Ollama model."""
    async for event in stream_chat(
        session,
        messages,
        current_date=current_date,
        timezone=timezone,
        web_search_enabled=web_search_enabled,
    ):
        if event.get("type") == "result":
            return str(event["answer"]), list(event["context"])
    raise RuntimeError("The local model returned no final result")
