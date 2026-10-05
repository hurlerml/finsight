"""Local Ollama embeddings for encrypted transaction representations."""

from __future__ import annotations

import hashlib
import math
import threading
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from sqlmodel import Session, select

from app.config import get_settings
from app.models import TransactionEmbedding
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload
from app.services.secure_transactions import TransactionData, load_transactions
from app.db import engine

EMBEDDING_SCHEMA_VERSION = 1
_backfill_lock = threading.Lock()
_backfill_running = False
_backfill_requested = False


def _semantic_payload_hints(payload: dict[str, Any] | None) -> list[str]:
    """Keep a small, non-sensitive subset of provider metadata in the embedding text."""
    hints: list[str] = []
    allowed_parts = ("merchant", "brand", "city", "country", "airport", "location", "description")
    blocked_parts = ("token", "secret", "password", "authorization", "credential", "card", "iban")

    def visit(value: Any, path: tuple[str, ...], depth: int) -> None:
        if len(hints) >= 12 or depth > 5:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                visit(child, (*path, str(key)), depth + 1)
            return
        if isinstance(value, list):
            for child in value[:5]:
                visit(child, path, depth + 1)
            return
        if value is None or not path:
            return
        normalized = "".join(part.lower() for part in path)
        if any(part in normalized for part in blocked_parts):
            return
        if not any(part in normalized for part in allowed_parts):
            return
        rendered = str(value).strip()
        if rendered and rendered not in hints:
            hints.append(rendered[:160])

    visit(payload or {}, (), 0)
    return hints


def _semantic_text(tx: TransactionData) -> str:
    direction = {
        "income": "Money received / income",
        "expense": "Money spent / expense",
        "transfer": "Internal transfer",
        "ignore": "Ignored transaction",
    }.get(tx.kind.value, tx.kind.value)
    parts = [
        direction,
        f"Counterparty: {tx.counterparty or 'unknown'}",
        f"Booking text: {tx.raw_text or 'unknown'}",
        f"Category ID: {tx.category_id if tx.category_id is not None else 'unknown'}",
        f"Account ID: {tx.account_id}",
    ]
    parts.extend(f"Provider hint: {hint}" for hint in _semantic_payload_hints(tx.raw_payload))
    return "\n".join(part for part in parts if part)


def _feature_vector(tx: TransactionData) -> list[float]:
    """Compact, normalized behavioral features kept beside the semantic vector."""
    amount = float(abs(tx.amount))
    day_of_year = tx.booking_date.timetuple().tm_yday
    month = tx.booking_date.month
    weekday = tx.booking_date.weekday()
    direction = tx.kind.value
    return [
        math.log1p(amount),
        1.0 if direction == "income" else 0.0,
        1.0 if direction == "expense" else 0.0,
        1.0 if direction == "transfer" else 0.0,
        math.sin(2 * math.pi * month / 12),
        math.cos(2 * math.pi * month / 12),
        math.sin(2 * math.pi * weekday / 7),
        math.cos(2 * math.pi * weekday / 7),
        math.sin(2 * math.pi * day_of_year / 365.25),
        math.cos(2 * math.pi * day_of_year / 365.25),
    ]


def _source_hash(tx: TransactionData, semantic_text: str) -> str:
    raw = f"{EMBEDDING_SCHEMA_VERSION}|{semantic_text}|{tx.booking_date.isoformat()}|{tx.amount}|{tx.currency}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def embed_texts(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    settings = get_settings()
    selected_model = model or settings.ollama_embedding_model
    if not settings.ollama_base_url.strip():
        raise RuntimeError("Ollama is not configured")
    response = httpx.post(
        settings.ollama_base_url.rstrip("/") + "/api/embed",
        json={"model": selected_model, "input": texts},
        timeout=300.0,
    )
    response.raise_for_status()
    embeddings = response.json().get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError("Ollama returned an invalid embedding response")
    return [[float(value) for value in vector] for vector in embeddings]


def search_transaction_embeddings(
    session: Session,
    dek: bytes,
    query: str,
    transactions: list[TransactionData],
    *,
    limit: int = 20,
) -> list[dict[str, float | int]]:
    """Rank an already-filtered transaction set by encrypted semantic vectors.

    The database only stores ciphertext.  Therefore the vector scan intentionally happens after
    vault unlock in the backend.  Callers should apply cheap, explicit filters (date, account,
    kind, category or a literal query) before invoking this function so the scan stays bounded.
    """
    clean_query = query.strip()
    if not clean_query:
        raise ValueError("query must not be empty")
    if not transactions:
        return []

    transaction_ids = [tx.id for tx in transactions]
    if not transaction_ids:
        return []
    model_name = get_settings().ollama_embedding_model
    rows = session.exec(
        select(TransactionEmbedding).where(
            TransactionEmbedding.transaction_id.in_(transaction_ids),  # type: ignore[union-attr]
            TransactionEmbedding.model_name == model_name,
        )
    ).all()
    if not rows:
        return []
    query_vector = embed_texts([clean_query])[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    if query_norm <= 0:
        return []
    candidates = {tx.id: tx for tx in transactions}
    scored: list[dict[str, float | int]] = []
    from app.services.secure_data import decrypt_payload

    for row in rows:
        if row.id is None or not row.encrypted_payload or row.transaction_id not in candidates:
            continue
        try:
            payload = decrypt_payload(
                dek,
                domain="transaction-embedding",
                record_id=row.id,
                blob=row.encrypted_payload,
            )
            vector = [float(value) for value in payload.get("semantic_vector", [])]
            if len(vector) != len(query_vector):
                continue
            vector_norm = math.sqrt(sum(value * value for value in vector))
            if vector_norm <= 0:
                continue
            similarity = sum(a * b for a, b in zip(query_vector, vector)) / (query_norm * vector_norm)
            scored.append({"transaction_id": row.transaction_id, "similarity": round(similarity, 6)})
        except Exception:
            # A malformed/stale encrypted embedding should not make the whole search unavailable.
            continue

    scored.sort(key=lambda item: float(item["similarity"]), reverse=True)
    return scored[: max(1, min(limit, 100))]


def find_similar_transaction_embeddings(
    session: Session,
    dek: bytes,
    transaction_id: int,
    transactions: list[TransactionData],
    *,
    limit: int = 20,
) -> list[dict[str, float | int]]:
    """Find transactions close to one known transaction without another Ollama request."""
    if not any(tx.id == transaction_id for tx in transactions):
        return []
    from app.services.secure_data import decrypt_payload

    target_row = session.exec(
        select(TransactionEmbedding).where(
            TransactionEmbedding.transaction_id == transaction_id,
            TransactionEmbedding.model_name == get_settings().ollama_embedding_model,
        )
    ).first()
    if target_row is None or target_row.id is None or not target_row.encrypted_payload:
        return []
    try:
        target_payload = decrypt_payload(
            dek,
            domain="transaction-embedding",
            record_id=target_row.id,
            blob=target_row.encrypted_payload,
        )
        target_vector = [float(value) for value in target_payload.get("semantic_vector", [])]
    except Exception:
        return []
    target_norm = math.sqrt(sum(value * value for value in target_vector))
    if target_norm <= 0:
        return []

    ranked = search_transaction_embeddings_by_vector(
        session,
        dek,
        target_vector,
        transactions,
        exclude_id=transaction_id,
        limit=limit,
    )
    return ranked


def search_transaction_embeddings_by_vector(
    session: Session,
    dek: bytes,
    query_vector: list[float],
    transactions: list[TransactionData],
    *,
    exclude_id: int | None = None,
    limit: int = 20,
) -> list[dict[str, float | int]]:
    """Internal cosine scan shared by free-text and known-transaction searches."""
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    if query_norm <= 0 or not transactions:
        return []
    transaction_ids = [tx.id for tx in transactions if tx.id != exclude_id]
    if not transaction_ids:
        return []
    rows = session.exec(
        select(TransactionEmbedding).where(
            TransactionEmbedding.transaction_id.in_(transaction_ids),  # type: ignore[union-attr]
            TransactionEmbedding.model_name == get_settings().ollama_embedding_model,
        )
    ).all()
    from app.services.secure_data import decrypt_payload
    scored: list[dict[str, float | int]] = []
    for row in rows:
        if row.id is None or not row.encrypted_payload:
            continue
        try:
            payload = decrypt_payload(
                dek,
                domain="transaction-embedding",
                record_id=row.id,
                blob=row.encrypted_payload,
            )
            vector = [float(value) for value in payload.get("semantic_vector", [])]
            if len(vector) != len(query_vector):
                continue
            vector_norm = math.sqrt(sum(value * value for value in vector))
            if vector_norm <= 0:
                continue
            similarity = sum(a * b for a, b in zip(query_vector, vector)) / (query_norm * vector_norm)
            scored.append({"transaction_id": row.transaction_id, "similarity": round(similarity, 6)})
        except Exception:
            continue
    scored.sort(key=lambda item: float(item["similarity"]), reverse=True)
    return scored[: max(1, min(limit, 100))]


def backfill_transaction_embeddings(
    session: Session,
    dek: bytes,
    transactions: list[TransactionData],
    *,
    batch_size: int = 32,
    model: str | None = None,
) -> int:
    """Embed transactions in batches and persist only encrypted payloads."""
    settings = get_settings()
    model_name = model or settings.ollama_embedding_model
    changed = 0
    for offset in range(0, len(transactions), max(1, batch_size)):
        batch = transactions[offset : offset + max(1, batch_size)]
        texts = [_semantic_text(tx) for tx in batch]
        vectors = embed_texts(texts, model=model_name)
        for tx, semantic_text, vector in zip(batch, texts, vectors, strict=True):
            source_hash = _source_hash(tx, semantic_text)
            existing = session.exec(
                select(TransactionEmbedding).where(TransactionEmbedding.transaction_id == tx.id)
            ).first()
            if existing and existing.encrypted_payload:
                # Re-embedding is idempotent; skip when the source fingerprint is unchanged.
                from app.services.secure_data import decrypt_payload
                try:
                    previous = decrypt_payload(dek, domain="transaction-embedding", record_id=existing.id or 0, blob=existing.encrypted_payload)
                    if previous.get("source_hash") == source_hash and previous.get("model_name") == model_name:
                        continue
                except Exception:
                    pass
            payload: dict[str, Any] = {
                "schema_version": EMBEDDING_SCHEMA_VERSION,
                "model_name": model_name,
                "source_hash": source_hash,
                "semantic_text": semantic_text,
                "semantic_vector": vector,
                "feature_vector": _feature_vector(tx),
            }
            if existing is None:
                existing = TransactionEmbedding(transaction_id=tx.id, model_name=model_name, dimensions=len(vector))
                session.add(existing)
                session.flush()
            existing.model_name = model_name
            existing.dimensions = len(vector)
            existing.encryption_version = ENCRYPTION_VERSION
            existing.encrypted_payload = encrypt_payload(dek, domain="transaction-embedding", record_id=existing.id or 0, payload=payload)
            changed += 1
    session.commit()
    return changed


def load_embedding_points(session: Session, dek: bytes, *, limit: int = 2000) -> list[dict[str, Any]]:
    """Project encrypted embeddings into a stable 2D point cloud for the UI."""
    from app.services.secure_data import decrypt_payload
    rows = session.exec(
        select(TransactionEmbedding)
        .where(TransactionEmbedding.model_name == get_settings().ollama_embedding_model)
        .limit(limit)
    ).all()
    points: list[dict[str, Any]] = []
    for row in rows:
        if row.id is None or not row.encrypted_payload:
            continue
        try:
            payload = decrypt_payload(dek, domain="transaction-embedding", record_id=row.id, blob=row.encrypted_payload)
            vector = [float(value) for value in payload.get("semantic_vector", [])]
            features = [float(value) for value in payload.get("feature_vector", [])]
            if len(vector) < 2:
                continue
            # Fixed signed projections avoid an additional ML dependency while keeping
            # the same transaction in the same place across unlocks.
            x = sum(value * (1.0 if (index * 17 + 3) % 7 < 3 else -1.0) for index, value in enumerate(vector)) / math.sqrt(len(vector))
            y = sum(value * (1.0 if (index * 29 + 5) % 11 < 5 else -1.0) for index, value in enumerate(vector)) / math.sqrt(len(vector))
            if features:
                x += 0.35 * features[0]
                y += 0.45 * (features[1] - features[2])
            points.append({"id": row.transaction_id, "x": round(x, 5), "y": round(y, 5), "kind": "income" if features[1] > 0.5 else "expense" if features[2] > 0.5 else "other"})
        except Exception:
            continue
    if len(points) < 4:
        return points

    # Lightweight DBSCAN on the stable 2D projection. This keeps the local
    # visualization dependency-free; the full semantic vectors remain encrypted.
    mean_x = sum(point["x"] for point in points) / len(points)
    mean_y = sum(point["y"] for point in points) / len(points)
    scale_x = max((sum((point["x"] - mean_x) ** 2 for point in points) / len(points)) ** 0.5, 1e-6)
    scale_y = max((sum((point["y"] - mean_y) ** 2 for point in points) / len(points)) ** 0.5, 1e-6)
    normalized = [((point["x"] - mean_x) / scale_x, (point["y"] - mean_y) / scale_y) for point in points]
    eps = 0.42
    min_samples = 5
    labels = [-1] * len(points)
    cluster = 0
    for index, (x, y) in enumerate(normalized):
        if labels[index] != -1:
            continue
        neighbours = [j for j, (nx, ny) in enumerate(normalized) if (x - nx) ** 2 + (y - ny) ** 2 <= eps ** 2]
        if len(neighbours) < min_samples:
            continue
        labels[index] = cluster
        queue = list(neighbours)
        cursor = 0
        while cursor < len(queue):
            current = queue[cursor]
            cursor += 1
            if labels[current] == -1:
                labels[current] = cluster
            if labels[current] != cluster:
                continue
            cx, cy = normalized[current]
            expanded = [j for j, (nx, ny) in enumerate(normalized) if (cx - nx) ** 2 + (cy - ny) ** 2 <= eps ** 2]
            if len(expanded) >= min_samples:
                queue.extend(j for j in expanded if j not in queue)
        cluster += 1
    for index, point in enumerate(points):
        point["cluster"] = labels[index]
    return points


def schedule_transaction_embedding_backfill(dek: bytes) -> bool:
    """Request a background backfill without mixing vectors from different models."""
    global _backfill_requested, _backfill_running
    with _backfill_lock:
        _backfill_requested = True
        if _backfill_running:
            return False
        _backfill_running = True

    def run() -> None:
        global _backfill_requested, _backfill_running
        try:
            while True:
                with _backfill_lock:
                    if not _backfill_requested:
                        _backfill_running = False
                        return
                    _backfill_requested = False
                model_name = get_settings().ollama_embedding_model
                with Session(engine) as session:
                    transactions = load_transactions(session, dek)
                    backfill_transaction_embeddings(
                        session,
                        dek,
                        transactions,
                        model=model_name,
                    )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Transaction embedding backfill failed")
            with _backfill_lock:
                retry_requested = _backfill_requested
                _backfill_running = False
            if retry_requested:
                schedule_transaction_embedding_backfill(dek)

    threading.Thread(target=run, name="transaction-embedding-backfill", daemon=True).start()
    return True
