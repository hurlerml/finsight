from types import SimpleNamespace

from app.api.sync import _job_targets_account
from app.models.enums import AccountSource


class _Job:
    def __init__(self, payload: dict):
        self.payload = payload


def test_sync_job_scope_is_limited_to_selected_account(monkeypatch) -> None:
    account = SimpleNamespace(
        id=7,
        connection_id=3,
        source=AccountSource.BINANCE,
    )
    monkeypatch.setattr(
        "app.api.sync.decode_job",
        lambda job, _dek: SimpleNamespace(payload=job.payload),
    )

    assert _job_targets_account(_Job({"account_id": 7}), account, b"dek")
    assert not _job_targets_account(_Job({"account_id": 8}), account, b"dek")
    assert _job_targets_account(_Job({"connection_id": 3}), account, b"dek")
    assert not _job_targets_account(_Job({"connection_id": 4}), account, b"dek")
    assert _job_targets_account(_Job({"source": "binance"}), account, b"dek")
    assert not _job_targets_account(_Job({"source": "trade_republic"}), account, b"dek")
    assert _job_targets_account(_Job({}), account, b"dek")
