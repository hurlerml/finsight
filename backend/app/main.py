"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.api import accounts, agent, assets, banks, categories, categorize, connections, embeddings, inflation, llm, onboarding, stats, sync, tags, transactions, vault
from app.config import get_settings
from app.db import engine
from app.services.llm_categorize import llm_loop
from app.services.ollama_setup import ollama_model_setup_loop
from app.services.seed import seed_categories
from app.services.vault_session import vault_session
from app.version import product_version
from app.worker import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PUBLIC_PATHS = {
    "/api/health",
    "/api/vault/status",
    "/api/vault/setup",
    "/api/vault/unlock",
    "/api/vault/recover",
    "/api/inflation/germany",
    "/docs",
    "/openapi.json",
    "/redoc",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    with Session(engine) as session:
        seed_categories(session)
    worker_task = asyncio.create_task(worker_loop())
    llm_task = asyncio.create_task(llm_loop())
    ollama_setup_task = asyncio.create_task(ollama_model_setup_loop())
    logger.info("Finsight API ready")
    try:
        yield
    finally:
        vault_session.lock()
        worker_task.cancel()
        llm_task.cancel()
        ollama_setup_task.cancel()
        for task in (worker_task, llm_task, ollama_setup_task):
            try:
                await task
            except asyncio.CancelledError:
                pass


settings = get_settings()

app = FastAPI(
    title="Finsight",
    description="Insight-first personal finance API",
    version=product_version(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_vault_unlock(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS or not path.startswith("/api/"):
        return await call_next(request)

    auth = request.headers.get("authorization") or ""
    token = None
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
    if vault_session.get_dek(token) is None:
        return JSONResponse(status_code=401, content={"detail": "Vault is locked"})
    return await call_next(request)


app.include_router(vault.router)
app.include_router(connections.router)
app.include_router(accounts.router)
app.include_router(banks.router)
app.include_router(assets.router)
app.include_router(inflation.router)
app.include_router(embeddings.router)
app.include_router(llm.router)
app.include_router(onboarding.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(tags.router)
app.include_router(categorize.router)
app.include_router(sync.router)
app.include_router(stats.router)
app.include_router(agent.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": product_version()}
