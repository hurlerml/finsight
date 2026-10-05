from types import SimpleNamespace

from app.api import onboarding
from app.services import secure_repository, secure_settings, seed, sync, vault


def test_new_settings_start_with_incomplete_onboarding() -> None:
    assert secure_settings._payload()["onboarding_completed"] is False


def test_new_vault_backfill_explicitly_resets_onboarding(monkeypatch) -> None:
    updates: list[bool] = []
    session = SimpleNamespace(commit=lambda: None)

    monkeypatch.setattr(seed, "seed_categories", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        secure_settings,
        "ensure_app_settings",
        lambda *_args, **_kwargs: SimpleNamespace(onboarding_completed=True),
    )
    monkeypatch.setattr(
        secure_settings,
        "update_model_preferences",
        lambda *_args, onboarding_completed=None, **_kwargs: updates.append(
            onboarding_completed
        ),
    )
    monkeypatch.setattr(
        sync,
        "backfill_fints_card_titles",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        secure_repository,
        "audit_private_payloads",
        lambda *_args: {},
    )

    vault._backfill_and_verify_private_data(  # type: ignore[arg-type]
        session,
        b"dek",
        new_vault=True,
    )

    assert updates == [False]


def test_legacy_settings_without_onboarding_field_are_complete(monkeypatch) -> None:
    settings = secure_settings.get_settings()
    old_chat_model = settings.ollama_model
    old_embedding_model = settings.ollama_embedding_model
    old_web_search = settings.categorization_web_search_enabled

    class ExistingSettingsSession:
        def get(self, *_args):
            return object()

    monkeypatch.setattr(
        secure_settings,
        "decrypted_financial_payload",
        lambda *_args: {
            "chat_model": old_chat_model,
            "embedding_model": old_embedding_model,
            "categorization_web_search_enabled": old_web_search,
        },
    )

    try:
        preferences = secure_settings.ensure_app_settings(
            ExistingSettingsSession(),  # type: ignore[arg-type]
            b"dek",
        )
    finally:
        settings.ollama_model = old_chat_model
        settings.ollama_embedding_model = old_embedding_model
        settings.categorization_web_search_enabled = old_web_search

    assert preferences.onboarding_completed is True


def test_onboarding_status_reads_encrypted_preference(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding,
        "ensure_app_settings",
        lambda *_args: SimpleNamespace(onboarding_completed=False),
    )

    assert onboarding.onboarding_status(
        session=object(),  # type: ignore[arg-type]
        dek=b"dek",
    ) == {"completed": False}


def test_onboarding_completion_is_persisted(monkeypatch) -> None:
    captured: list[bool] = []
    setup_requests: list[bool] = []

    def update(_session, _dek, *, onboarding_completed=None, **_kwargs):
        captured.append(onboarding_completed)
        return SimpleNamespace(onboarding_completed=onboarding_completed)

    monkeypatch.setattr(onboarding, "update_model_preferences", update)
    monkeypatch.setattr(
        onboarding,
        "request_model_setup",
        lambda: setup_requests.append(True),
    )

    result = onboarding.update_onboarding(
        onboarding.OnboardingUpdate(completed=True),
        session=object(),  # type: ignore[arg-type]
        dek=b"dek",
    )

    assert result == {"completed": True}
    assert captured == [True]
    assert setup_requests == [True]
