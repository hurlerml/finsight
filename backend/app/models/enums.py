"""Shared domain enums."""

from enum import Enum


class AccountSource(str, Enum):
    VOLKSBANK = "volksbank"
    TRADE_REPUBLIC = "trade_republic"
    BINANCE = "binance"
    TRADING_212 = "trading_212"
    COINBASE = "coinbase"


class AccountType(str, Enum):
    CHECKING = "checking"
    CARD = "card"
    WALLET = "wallet"
    BROKER_CASH = "broker_cash"


class TransactionKind(str, Enum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    IGNORE = "ignore"


class CategorizedBy(str, Enum):
    RULE = "rule"
    MANUAL = "manual"
    LLM = "llm"


class LinkType(str, Enum):
    INTERNAL_TRANSFER = "internal_transfer"
    BROKER_FUNDING = "broker_funding"
    ACCOUNT_FUNDING = "account_funding"


class LinkStatus(str, Enum):
    CONFIRMED = "confirmed"
    SUGGESTED = "suggested"
    REJECTED = "rejected"


class LinkEvaluatedBy(str, Enum):
    RULE = "rule"
    LLM = "llm"
    MANUAL = "manual"


class TagType(str, Enum):
    GENERAL = "general"
    TRIP = "trip"
    PROJECT = "project"


class JobType(str, Enum):
    SYNC = "sync"
    NORMALIZE = "normalize"
    MATCH = "match"
    CATEGORIZE = "categorize"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    BACKFILLING = "backfilling"
    SUCCESS = "success"
    ERROR = "error"
