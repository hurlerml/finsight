"""Application settings loaded from the root .env file."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_OLLAMA_MODEL = "gemma4:26b-mlx"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "qwen3-embedding:4b"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://finsight:finsight_change_me@postgres:5432/finsight"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    cors_origins: str = "http://localhost:5173"
    sync_overlap_days: int = 14
    sync_chunk_days: int = 30
    sync_max_chunks_per_job: int = 24
    # FinTS push-TAN / bank-app approval and similar user-action waits.
    sync_user_action_timeout_seconds: int = Field(default=60, ge=30, le=300)
    # Fail RUNNING jobs that exceed this wall time (worker crash / stuck gateway).
    sync_job_stale_seconds: int = Field(default=90, ge=45, le=600)
    vault_idle_timeout_minutes: int = 60
    # FinTS product identifier registered by the operator. Keep this out of
    # source control; connections may override it with an encrypted value.
    fints_product_id: str = ""
    # Internal HBCI4Java sidecar. It is intentionally not exposed publicly.
    fints_gateway_url: str = "http://fints-gateway:8082"
    # Host Ollama from Docker: http://host.docker.internal:11434
    ollama_base_url: str = ""
    # Initial onboarding defaults. The selected values are subsequently stored
    # as encrypted application preferences.
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_embedding_model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL
    # Automatic merchant research used only by background categorization.
    # Chat web search remains a separate per-request choice.
    categorization_web_search_enabled: bool = True
    ollama_context_window: int = Field(default=32768, ge=4096)
    # Maximum number of tokens the conversational agent may generate.  Keep
    # this separate from the context window: a large context does not imply a
    # useful answer budget, and Ollama otherwise falls back to a small model
    # default on some installations.
    ollama_output_tokens: int = Field(default=8192, ge=256, le=32768)
    # Opt-in diagnostics for local development. Keep disabled in normal use:
    # model output may contain merchant text and other transaction context.
    debug_llm: bool = False
    match_date_window_days: int = 3
    match_max_candidates: int = 30
    match_auto_confidence: float = 0.95
    match_suggest_confidence: float = 0.70

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ollama_configured(self) -> bool:
        return bool(self.ollama_base_url.strip() and self.ollama_model.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
