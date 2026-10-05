"""Embedding backfill and point-cloud endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.deps import require_unlocked
from app.services.embeddings import backfill_transaction_embeddings, load_embedding_points
from app.services.secure_transactions import load_transactions

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


@router.get("/point-cloud")
def point_cloud(
    limit: int = Query(default=2000, ge=1, le=10000),
    _dek: bytes = Depends(require_unlocked),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    points = load_embedding_points(session, _dek, limit=limit)
    clusters = sorted({int(point["cluster"]) for point in points if int(point.get("cluster", -1)) >= 0})
    return {"points": points, "clusters": clusters}


@router.post("/backfill")
def backfill(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    dek: bytes = Depends(require_unlocked),
    session: Session = Depends(get_session),
) -> dict[str, int]:
    transactions = load_transactions(session, dek, from_date=from_date, to_date=to_date)[:limit]
    processed = backfill_transaction_embeddings(session, dek, transactions)
    return {"candidates": len(transactions), "embedded": processed}
