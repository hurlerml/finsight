"""Versioned encrypted payloads and blind indexes for private user data.

Canonical private values live only in encrypted envelopes. Searchable identity
uses blind indexes; public technical columns (source, status, FKs, slugs) stay
unencrypted by design.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
from typing import Any

from app.services import crypto

ENVELOPE_MAGIC = b"FSE1"
ENCRYPTION_VERSION = 1


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    raise TypeError(f"Unsupported secure payload value: {type(value).__name__}")


def _aad(domain: str, record_id: int | str, version: int) -> bytes:
    return f"finsight|{version}|{domain}|{record_id}".encode("utf-8")


def canonical_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize domain values exactly as they are represented inside an envelope."""
    decoded = json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=_json_default,
        )
    )
    if not isinstance(decoded, dict):
        raise ValueError("Secure payload must contain an object")
    return decoded


def encrypt_payload(
    dek: bytes,
    *,
    domain: str,
    record_id: int | str,
    payload: dict[str, Any],
) -> bytes:
    plaintext = json.dumps(
        canonical_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    key = crypto.derive_subkey(dek, f"payload:{domain}:v{ENCRYPTION_VERSION}")
    ciphertext = crypto.encrypt(
        key,
        plaintext,
        _aad(domain, record_id, ENCRYPTION_VERSION),
    )
    return ENVELOPE_MAGIC + bytes([ENCRYPTION_VERSION]) + ciphertext


def decrypt_payload(
    dek: bytes,
    *,
    domain: str,
    record_id: int | str,
    blob: bytes,
) -> dict[str, Any]:
    prefix_len = len(ENVELOPE_MAGIC)
    if len(blob) <= prefix_len or blob[:prefix_len] != ENVELOPE_MAGIC:
        raise ValueError("Unsupported encrypted payload")
    version = blob[prefix_len]
    if version != ENCRYPTION_VERSION:
        raise ValueError(f"Unsupported encrypted payload version: {version}")
    key = crypto.derive_subkey(dek, f"payload:{domain}:v{version}")
    plaintext = crypto.decrypt(
        key,
        blob[prefix_len + 1 :],
        _aad(domain, record_id, version),
    )
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Encrypted payload must contain an object")
    return decoded


def transaction_month_index(dek: bytes, account_id: int, booking_date: date) -> bytes:
    return crypto.blind_index(
        dek,
        "transaction-month",
        f"{account_id}:{booking_date.year:04d}-{booking_date.month:02d}",
    )


def transaction_external_id_index(dek: bytes, account_id: int, external_id: str) -> bytes:
    return crypto.blind_index(
        dek,
        "transaction-external-id",
        f"{account_id}:{external_id}",
    )


def source_external_id_index(
    dek: bytes, domain: str, source: str, external_id: str
) -> bytes:
    """Index provider identifiers without exposing the original identifier."""
    return crypto.blind_index(
        dek,
        f"{domain}-external-id",
        f"{source}:{external_id}",
    )


def portfolio_trade_external_id_index(
    dek: bytes, portfolio_id: int, external_id: str
) -> bytes:
    return crypto.blind_index(
        dek,
        "asset-trade-external-id",
        f"{portfolio_id}:{external_id}",
    )


def private_name_index(dek: bytes, domain: str, name: str) -> bytes:
    """Case-insensitive lookup for private user-defined names."""
    normalized = " ".join(name.strip().casefold().split())
    return crypto.blind_index(dek, f"{domain}-name", normalized)
