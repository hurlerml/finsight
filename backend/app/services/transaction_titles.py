"""Provider-specific helpers for human-friendly transaction titles."""

from __future__ import annotations

import re


# FinTS card booking texts vary between ``EUR 12,34`` and ``12,34 EUR``
# (and sometimes use the euro sign). Keep this parser deliberately tolerant,
# while requiring both a currency marker and an amount before extracting text.
_AMOUNT = r"[+-]?(?:\d{1,3}(?:[.\s]\d{3})*|\d+)(?:[,.]\d{1,2})?"
_CURRENCY = r"(?:EUR|EURO|€)"
_TITLE_BEFORE_CURRENCY = re.compile(
    rf"^(?P<title>.+?)\s+{_CURRENCY}\s*{_AMOUNT}(?:\s|$)",
    re.IGNORECASE,
)
_TITLE_BEFORE_AMOUNT = re.compile(
    rf"^(?P<title>.+?)\s+{_AMOUNT}\s*{_CURRENCY}(?:\b|$)",
    re.IGNORECASE,
)


def fints_card_transaction_title(raw_text: str | None) -> str | None:
    """Extract the merchant/title portion of a FinTS card booking.

    If a bank sends a different format, ``None`` is returned so the original
    booking text remains available instead of inventing a title.
    """

    text = " ".join(str(raw_text or "").split())
    if not text:
        return None
    match = _TITLE_BEFORE_CURRENCY.search(text) or _TITLE_BEFORE_AMOUNT.search(text)
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group("title")).strip(" |;,:-_")
    return title or None
