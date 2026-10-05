"""Product version shared by the API, frontend and FinTS gateway."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


def version_file() -> Path:
    """Locate version.json in a checkout or in the production image."""
    here = Path(__file__).resolve()
    candidates = (
        here.parents[2] / "version.json",  # repository root during development
        here.parents[1] / "version.json",  # /app/version.json in the backend image
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("version.json was not found")


@lru_cache
def product_version() -> str:
    payload = json.loads(version_file().read_text(encoding="utf-8"))
    version = str(payload.get("version", "")).strip()
    if not version:
        raise ValueError("version.json does not define a version")
    return version
