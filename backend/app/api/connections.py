from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.deps import require_unlocked
from app.schemas.vault import ConnectionCreate, ConnectionRead, ConnectionUpdate
from app.services import connections as connections_service
from app.services.vault import VaultError

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _to_read(
    row,
    public_fields: dict[str, str],
    private: connections_service.ConnectionPrivateData,
) -> ConnectionRead:
    return ConnectionRead(
        id=row.id,
        source=row.source,
        provider=row.provider,
        name=private.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_error=private.last_error,
        public_fields=public_fields,
    )


@router.get("", response_model=list[ConnectionRead])
def list_connections(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> list[ConnectionRead]:
    rows = connections_service.list_connections(session, dek)
    return [_to_read(row, pubs, private) for row, pubs, private in rows]


@router.post("", response_model=ConnectionRead, status_code=201)
def create_connection(
    body: ConnectionCreate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> ConnectionRead:
    try:
        row = connections_service.create_connection(
            session,
            dek=dek,
            source=body.source,
            provider=body.provider,
            name=body.name,
            secrets=body.secrets,
        )
    except VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    pubs = connections_service.public_fields_from_secrets(
        row.source, row.provider, connections_service.connection_secrets(row, dek)
    )
    return _to_read(row, pubs, connections_service.connection_private_data(row, dek))


@router.patch("/{connection_id}", response_model=ConnectionRead)
def update_connection(
    connection_id: int,
    body: ConnectionUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> ConnectionRead:
    try:
        row = connections_service.update_connection(
            session,
            dek=dek,
            connection_id=connection_id,
            name=body.name,
            secrets=body.secrets,
        )
        pubs = connections_service.list_connections(session, dek)
        public = next((p for r, p, _private in pubs if r.id == row.id), {})
    except VaultError as exc:
        status = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return _to_read(
        row,
        public,
        connections_service.connection_private_data(row, dek),
    )


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: int,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> None:
    try:
        connections_service.delete_connection(session, connection_id)
    except VaultError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
