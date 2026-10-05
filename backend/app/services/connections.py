"""CRUD helpers for encrypted adapter connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, update
from sqlmodel import Session, select

from app.adapters.bank_profiles import (
    GENERIC_FINTS_PROFILE,
    apply_bank_defaults,
    validate_provider,
)
from app.models.enums import AccountSource
from app.models.vault import Connection
from app.services.vault import VaultError, decrypt_secrets, encrypt_secrets
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload, private_name_index
from app.services.secure_repository import decrypted_financial_payload


PUBLIC_KEYS: dict[AccountSource, tuple[str, ...]] = {
    AccountSource.VOLKSBANK: (
        "iban",
        "user",
    ),
    AccountSource.TRADE_REPUBLIC: ("phone",),
    # API credentials are secrets. Deliberately expose no Binance field.
    AccountSource.BINANCE: (),
    AccountSource.TRADING_212: (),
    AccountSource.COINBASE: (),
}

REQUIRED_KEYS: dict[AccountSource, tuple[str, ...]] = {
    AccountSource.VOLKSBANK: ("blz", "user", "pin", "endpoint"),
    AccountSource.TRADE_REPUBLIC: ("phone", "pin"),
    AccountSource.BINANCE: ("api_key", "api_secret"),
    AccountSource.TRADING_212: ("api_key", "api_secret"),
    AccountSource.COINBASE: ("api_key", "api_secret"),
}


@dataclass(frozen=True)
class ConnectionPrivateData:
    name: str
    last_error: str | None


def connection_private_data(row: Connection, dek: bytes) -> ConnectionPrivateData:
    payload = decrypted_financial_payload(row, dek)
    return ConnectionPrivateData(
        name=str(payload.get("name") or ""),
        last_error=(
            str(payload["last_error"])
            if payload.get("last_error") is not None
            else None
        ),
    )


def public_fields_from_secrets(
    source: AccountSource,
    provider: str,
    secrets: dict[str, Any],
) -> dict[str, str]:
    keys = PUBLIC_KEYS.get(source, ())
    if source == AccountSource.VOLKSBANK and provider == GENERIC_FINTS_PROFILE:
        keys = (
            *keys,
            "customer_id",
            "tan_medium",
            "bank_name",
            "bank_bic",
            "bank_brand",
        )
    fields = {k: str(secrets[k]) for k in keys if secrets.get(k)}
    if source == AccountSource.VOLKSBANK and fields.get("iban"):
        fields.pop("blz", None)
    return fields


def normalize_identifiers(
    source: AccountSource,
    provider: str,
    secrets: dict[str, Any],
) -> dict[str, Any]:
    """Normalize a German IBAN and derive the embedded eight-digit BLZ."""
    normalized = apply_bank_defaults(source, provider, secrets)
    if source != AccountSource.VOLKSBANK or not str(normalized.get("iban", "")).strip():
        return normalized

    iban = "".join(str(normalized["iban"]).upper().split())
    if len(iban) != 22 or not iban.startswith("DE") or not iban[2:].isdigit():
        raise VaultError("Please enter a valid German IBAN")
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(char) - 55) if char.isalpha() else char for char in rearranged)
    if int(numeric) % 97 != 1:
        raise VaultError("The IBAN checksum is invalid")

    iban_blz = iban[4:12]
    selected_blz = str(normalized.get("blz") or "").strip()
    if selected_blz and selected_blz != iban_blz:
        raise VaultError("The selected bank does not match the IBAN")
    normalized["iban"] = iban
    normalized["blz"] = iban_blz
    return normalized


def validate_secrets(source: AccountSource, secrets: dict[str, str], *, partial: bool = False) -> None:
    required = REQUIRED_KEYS[source]
    if partial:
        return
    missing = [k for k in required if not str(secrets.get(k, "")).strip()]
    if missing:
        raise VaultError(f"Missing required fields: {', '.join(missing)}")


def merge_secrets(existing: dict[str, Any], updates: dict[str, str]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in updates.items():
        if value is None:
            continue
        # Empty string means "leave unchanged" for secret fields on update
        if value == "" and key in existing:
            continue
        merged[key] = value
    return merged


def create_connection(
    session: Session,
    *,
    dek: bytes,
    source: AccountSource,
    provider: str | None,
    name: str,
    secrets: dict[str, str],
) -> Connection:
    try:
        provider = validate_provider(source, provider)
    except ValueError as exc:
        raise VaultError(str(exc)) from exc
    secrets = normalize_identifiers(source, provider, secrets)
    validate_secrets(source, secrets, partial=False)
    row_id = session.execute(insert(Connection).values(
        source=source, provider=provider,
        secrets_encrypted=encrypt_secrets(dek, secrets),
    ).returning(Connection.id)).scalar_one()
    payload = {"name": name, "last_error": None}
    session.execute(update(Connection).where(Connection.id == row_id).values(
        encrypted_payload=encrypt_payload(
            dek, domain="connection", record_id=row_id, payload=payload
        ), encryption_version=ENCRYPTION_VERSION,
        name_blind=private_name_index(dek, "connection", f"{source.value}:{name}"),
    ))
    session.commit()
    row = session.get(Connection, row_id)
    if row is None:
        raise RuntimeError("Ciphertext connection insert failed")
    session.refresh(row)
    return row


def update_connection(
    session: Session,
    *,
    dek: bytes,
    connection_id: int,
    name: str | None = None,
    secrets: dict[str, str] | None = None,
) -> Connection:
    row = session.get(Connection, connection_id)
    if row is None:
        raise VaultError("Connection not found")

    private = connection_private_data(row, dek)
    updated_name = name if name is not None else private.name
    values: dict[str, Any] = {}
    if secrets is not None:
        current = decrypt_secrets(dek, row.secrets_encrypted)
        merged = merge_secrets(current, secrets)
        merged = normalize_identifiers(row.source, row.provider, merged)
        validate_secrets(row.source, {k: str(v) for k, v in merged.items()}, partial=False)
        values["secrets_encrypted"] = encrypt_secrets(dek, merged)

    payload = {"name": updated_name, "last_error": private.last_error}
    values.update(
        encrypted_payload=encrypt_payload(
            dek, domain="connection", record_id=connection_id, payload=payload
        ),
        encryption_version=ENCRYPTION_VERSION,
        name_blind=private_name_index(
            dek, "connection", f"{row.source.value}:{updated_name}"
        ),
    )
    session.execute(update(Connection).where(Connection.id == connection_id).values(**values))
    session.commit()
    session.expire(row)
    session.refresh(row)
    return row


def set_connection_last_error(
    session: Session,
    *,
    dek: bytes,
    connection_id: int,
    error: str | None,
) -> None:
    row = session.get(Connection, connection_id)
    if row is None:
        return
    private = connection_private_data(row, dek)
    payload = {"name": private.name, "last_error": error[:2000] if error else None}
    session.execute(
        update(Connection)
        .where(Connection.id == connection_id)
        .values(
            encrypted_payload=encrypt_payload(
                dek, domain="connection", record_id=connection_id, payload=payload
            ),
            encryption_version=ENCRYPTION_VERSION,
        )
    )
    session.commit()


def delete_connection(session: Session, connection_id: int) -> None:
    row = session.get(Connection, connection_id)
    if row is None:
        raise VaultError("Connection not found")
    session.delete(row)
    session.commit()


def list_connections(
    session: Session, dek: bytes
) -> list[tuple[Connection, dict[str, str], ConnectionPrivateData]]:
    rows = session.exec(select(Connection).order_by(Connection.source, Connection.id)).all()
    result: list[tuple[Connection, dict[str, str], ConnectionPrivateData]] = []
    for row in rows:
        secrets = decrypt_secrets(dek, row.secrets_encrypted)
        result.append(
            (
                row,
                public_fields_from_secrets(row.source, row.provider, secrets),
                connection_private_data(row, dek),
            )
        )
    return sorted(result, key=lambda item: (item[0].source.value, item[2].name.casefold()))


def connection_secrets(row: Connection, dek: bytes) -> dict[str, Any]:
    return decrypt_secrets(dek, row.secrets_encrypted)
