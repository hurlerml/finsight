"""Bank/wallet adapters. Credentials come from the unlocked vault."""

from __future__ import annotations

from sqlmodel import Session

from app.adapters.base import (
    AdapterRegistry,
    BaseAdapter,
    RawAccount,
    RawAssetPosition,
    RawAssetTrade,
    RawBalance,
    RawPortfolio,
    RawTransaction,
)
from app.adapters.binance import BinanceAdapter
from app.adapters.coinbase import CoinbaseAdapter
from app.adapters.traderepublic import TradeRepublicAdapter
from app.adapters.trading212 import Trading212Adapter
from app.adapters.fints import FintsAdapter
from app.models.enums import AccountSource
from app.services.vault import decrypt_secrets, encrypt_secrets, list_connection_secrets
from app.services.vault_session import vault_session

__all__ = [
    "AdapterRegistry",
    "BaseAdapter",
    "BinanceAdapter",
    "CoinbaseAdapter",
    "FintsAdapter",
    "RawAccount",
    "RawAssetPosition",
    "RawAssetTrade",
    "RawBalance",
    "RawPortfolio",
    "RawTransaction",
    "TradeRepublicAdapter",
    "Trading212Adapter",
    "build_registry",
]


def build_registry(session: Session) -> AdapterRegistry:
    """Build adapters from encrypted connections. Empty if vault is locked."""
    from app.services.connections import connection_private_data

    registry = AdapterRegistry()
    dek = vault_session.get_dek()
    if dek is None:
        return registry

    for conn, secrets in list_connection_secrets(session, dek):
        private = connection_private_data(conn, dek)
        if conn.source == AccountSource.VOLKSBANK:
            adapter = FintsAdapter(secrets, label=private.name)
            adapter.connection_id = conn.id
            adapter.provider = conn.provider
            registry.register(adapter)
        elif conn.source == AccountSource.TRADE_REPUBLIC:
            def persist_trade_republic(
                updates: dict,
                *,
                connection=conn,
                connection_dek=dek,
                db_session=session,
            ) -> None:
                """Keep TR session material encrypted with the connection secrets."""
                current = decrypt_secrets(connection_dek, connection.secrets_encrypted)
                current.update(updates)
                connection.secrets_encrypted = encrypt_secrets(connection_dek, current)
                db_session.add(connection)
                db_session.commit()

            adapter = TradeRepublicAdapter(
                secrets,
                label=private.name,
                persist_secrets=persist_trade_republic,
            )
            adapter.connection_id = conn.id
            adapter.provider = conn.provider
            registry.register(adapter)
        elif conn.source == AccountSource.BINANCE:
            adapter = BinanceAdapter(secrets, label=private.name)
            adapter.connection_id = conn.id
            adapter.provider = conn.provider
            registry.register(adapter)
        elif conn.source == AccountSource.TRADING_212:
            adapter = Trading212Adapter(secrets, label=private.name)
            adapter.connection_id = conn.id
            adapter.provider = conn.provider
            registry.register(adapter)
        elif conn.source == AccountSource.COINBASE:
            adapter = CoinbaseAdapter(secrets, label=private.name)
            adapter.connection_id = conn.id
            adapter.provider = conn.provider
            registry.register(adapter)
    return registry
