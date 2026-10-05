"""Infer transaction kind (income / expense / transfer) from raw text."""

from app.adapters.base import RawTransaction
from app.models.enums import TransactionKind


def _fold(text: str) -> str:
    """Lowercase and fold common Latin diacritics for keyword matching."""
    table = str.maketrans(
        {
            "\u00e4": "ae",
            "\u00f6": "oe",
            "\u00fc": "ue",
            "\u00df": "ss",
            "\u00e1": "a",
            "\u00e0": "a",
            "\u00e9": "e",
            "\u00e8": "e",
        }
    )
    return text.lower().translate(table)


# ASCII patterns only — booking text is folded before matching.
TRANSFER_HINTS = (
    "trade republic",
    "traderepublic",
    "umbuchung",
    "uebertrag",
    "eigenueberweisung",
)

TRANSFER_ACTIONS = (
    "aufladung",
    "einzahlung",
    "auszahlung",
    "ueberweisung an",
    "transfer",
    "top up",
    "withdrawal",
    "deposit",
)


def infer_kind(raw: RawTransaction) -> TransactionKind:
    text = _fold(f"{raw.raw_text} {raw.counterparty or ''}")
    if any(h in text for h in TRANSFER_HINTS) and any(a in text for a in TRANSFER_ACTIONS):
        return TransactionKind.TRANSFER

    if raw.amount > 0:
        return TransactionKind.INCOME
    if raw.amount < 0:
        return TransactionKind.EXPENSE
    return TransactionKind.IGNORE
