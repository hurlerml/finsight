from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AccountSource


class VaultStatus(BaseModel):
    initialized: bool
    unlocked: bool
    recovery_configured: bool = False
    recovery_confirmed: bool = False


class VaultPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)


class VaultUnlockResponse(BaseModel):
    token: str
    message: str


class VaultSetupResponse(VaultUnlockResponse):
    recovery_phrase: str


class VaultRecoveryPhraseRequest(BaseModel):
    recovery_phrase: str = Field(min_length=1, max_length=512)


class VaultRecoveryConfirmRequest(VaultRecoveryPhraseRequest):
    replace: bool = False


class VaultRecoverRequest(VaultRecoveryPhraseRequest):
    new_password: str = Field(min_length=8, max_length=256)


class VaultRecoveryPhraseResponse(BaseModel):
    recovery_phrase: str


class EncryptionCollectionStatus(BaseModel):
    total: int
    encrypted: int
    pending: int


class PrivateEncryptionStatus(BaseModel):
    transactions: EncryptionCollectionStatus
    conversations: EncryptionCollectionStatus
    messages: EncryptionCollectionStatus
    accounts: EncryptionCollectionStatus
    account_balances: EncryptionCollectionStatus
    portfolios: EncryptionCollectionStatus
    asset_positions: EncryptionCollectionStatus
    portfolio_values: EncryptionCollectionStatus
    asset_trades: EncryptionCollectionStatus
    tags: EncryptionCollectionStatus
    transaction_tags: EncryptionCollectionStatus
    categories: EncryptionCollectionStatus
    category_rules: EncryptionCollectionStatus
    transaction_links: EncryptionCollectionStatus
    connections: EncryptionCollectionStatus
    sync_states: EncryptionCollectionStatus
    jobs: EncryptionCollectionStatus
    app_settings: EncryptionCollectionStatus


class EncryptionAuditCollection(BaseModel):
    total: int
    verified: int
    pending: int
    unreadable: int


class PrivateEncryptionAudit(BaseModel):
    transactions: EncryptionAuditCollection
    conversations: EncryptionAuditCollection
    messages: EncryptionAuditCollection
    accounts: EncryptionAuditCollection
    account_balances: EncryptionAuditCollection
    portfolios: EncryptionAuditCollection
    asset_positions: EncryptionAuditCollection
    portfolio_values: EncryptionAuditCollection
    asset_trades: EncryptionAuditCollection
    tags: EncryptionAuditCollection
    transaction_tags: EncryptionAuditCollection
    categories: EncryptionAuditCollection
    category_rules: EncryptionAuditCollection
    transaction_links: EncryptionAuditCollection
    connections: EncryptionAuditCollection
    connection_credentials: EncryptionAuditCollection
    sync_states: EncryptionAuditCollection
    jobs: EncryptionAuditCollection
    app_settings: EncryptionAuditCollection


class ConnectionCreate(BaseModel):
    source: AccountSource
    provider: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    secrets: dict[str, str]


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    secrets: dict[str, str] | None = None


class ConnectionRead(BaseModel):
    id: int
    source: AccountSource
    provider: str
    name: str
    created_at: datetime
    updated_at: datetime
    last_error: str | None
    # Non-secret hints for the UI (never includes pin/secret values)
    public_fields: dict[str, str]
