"""Bank directory backed by the internal HBCI4Java gateway."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings

router = APIRouter(prefix="/api/banks", tags=["banks"])


@router.get("")
async def search_banks(
    query: str = Query(min_length=3, max_length=100),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    settings = get_settings()
    url = f"{settings.fints_gateway_url.rstrip('/')}/banks"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, params={"query": query, "limit": limit})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = "FinTS bank directory rejected the request"
        try:
            detail = exc.response.json().get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="FinTS bank directory is unavailable") from exc
    return response.json()
