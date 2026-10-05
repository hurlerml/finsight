"""Public German monthly inflation reference data."""
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from app.db import get_session
from app.models import InflationIndex

router = APIRouter(prefix="/api/inflation", tags=["inflation"])
_cache: tuple[datetime, list[dict[str, str]]] | None = None


@router.get("/germany")
def germany_cpi(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return monthly German HICP values from Eurostat (offline-cached for 24h)."""
    global _cache
    now = datetime.now(timezone.utc)
    stored = session.exec(select(InflationIndex).where(InflationIndex.country == "DE", InflationIndex.source == "eurostat").order_by(InflationIndex.month)).all()
    if stored and _cache and now - _cache[0] < timedelta(hours=24):
        return {"country": "DE", "currency": "EUR", "source": "eurostat", "points": _cache[1]}
    # Eurostat migrated HICP monthly indices to the ECOICOP v2 dataset in 2026.
    # The former prc_hicp_midx series is archived at 2025-12.
    url = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
    params = {"geo": "DE", "coicop18": "TOTAL", "unit": "I15"}
    try:
        with httpx.Client(timeout=15) as client:
            payload = client.get(url, params=params).raise_for_status().json()
        times = payload.get("dimension", {}).get("time", {}).get("category", {})
        labels = times.get("index", {})
        values = payload.get("value", {})
        points = [
            {"month": month, "index": str(values[str(index)])}
            for month, index in sorted(labels.items(), key=lambda item: item[1])
            if str(index) in values
        ]
        if points:
            for point in points:
                existing = session.exec(select(InflationIndex).where(InflationIndex.country == "DE", InflationIndex.month == point["month"], InflationIndex.source == "eurostat")).first()
                if existing:
                    existing.index_value = point["index"]
                    existing.fetched_at = now
                else:
                    session.add(InflationIndex(month=point["month"], index_value=point["index"], fetched_at=now))
            session.commit()
            _cache = (now, points)
    except (httpx.HTTPError, ValueError, KeyError):
        points = ([{"month": row.month, "index": str(row.index_value)} for row in stored] if stored else (_cache[1] if _cache else []))
    return {"country": "DE", "currency": "EUR", "source": "eurostat", "points": points}
