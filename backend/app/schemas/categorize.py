from pydantic import BaseModel, Field


class CategorizeCurrentRead(BaseModel):
    id: int
    booking_date: str
    counterparty: str | None
    amount: str


class CategorizeDoneRead(BaseModel):
    id: int
    slug: str
    confidence: float


class CategorizeStatusRead(BaseModel):
    ollama_configured: bool
    ollama_reachable: bool
    phase: str
    queue_remaining: int
    queue_total: int = 0
    queue_processed: int = 0
    current: CategorizeCurrentRead | None = None
    last_done: list[CategorizeDoneRead] = Field(default_factory=list)
    llm_applied_session: int = 0
    message: str | None = None


class RecategorizeRequest(BaseModel):
    account_id: int | None = None
    category_id: int | None = None
    include_manual: bool = False


class RecategorizeRead(BaseModel):
    reset_count: int
    rules_applied: int
    queued_for_agent: int
