from types import SimpleNamespace

from app.services import secure_repository
from app.services.vault import encrypt_secrets


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _AuditSession:
    def __init__(self, connection):
        self.connection = connection

    def exec(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is secure_repository.Connection:
            return _Rows([self.connection])
        return _Rows([])


def test_audit_authenticates_connection_credentials() -> None:
    dek = b"a" * 32
    connection = SimpleNamespace(
        encrypted_payload=None,
        secrets_encrypted=encrypt_secrets(dek, {"username": "example"}),
    )

    audit = secure_repository.audit_private_payloads(
        _AuditSession(connection),  # type: ignore[arg-type]
        dek,
    )

    assert audit["connection_credentials"] == {
        "total": 1,
        "verified": 1,
        "pending": 0,
        "unreadable": 0,
    }


def test_audit_reports_corrupt_connection_credentials() -> None:
    connection = SimpleNamespace(
        encrypted_payload=None,
        secrets_encrypted=b"not-valid-ciphertext",
    )

    audit = secure_repository.audit_private_payloads(
        _AuditSession(connection),  # type: ignore[arg-type]
        b"a" * 32,
    )

    assert audit["connection_credentials"]["unreadable"] == 1
