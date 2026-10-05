"""FinTS bank profiles and technical defaults offered by the UI."""

from dataclasses import dataclass, field

from app.models.enums import AccountSource


@dataclass(frozen=True)
class BankProfile:
    key: str
    name: str
    source: AccountSource
    defaults: dict[str, str] = field(default_factory=dict)


GENERIC_FINTS_PROFILE = "generic_fints"
# Kept only so encrypted connections created before the HBCI4Java directory
# migration remain readable. New connections always use generic_fints.
LEGACY_FINTS_PROFILE = "volksbank"

FINTS_BANK_PROFILES: dict[str, BankProfile] = {
    GENERIC_FINTS_PROFILE: BankProfile(
        key=GENERIC_FINTS_PROFILE,
        name="Andere Bank (FinTS)",
        source=AccountSource.VOLKSBANK,
    ),
}


def default_provider(source: AccountSource) -> str:
    if source == AccountSource.VOLKSBANK:
        return GENERIC_FINTS_PROFILE
    return source.value


def validate_provider(source: AccountSource, provider: str | None) -> str:
    key = provider or default_provider(source)
    if source == AccountSource.VOLKSBANK:
        if key not in {*FINTS_BANK_PROFILES, LEGACY_FINTS_PROFILE}:
            raise ValueError(f"Unknown FinTS bank profile: {key}")
        return key
    if key != source.value:
        raise ValueError(f"Provider {key} does not match source {source.value}")
    return key


def apply_bank_defaults(
    source: AccountSource,
    provider: str,
    secrets: dict[str, object],
) -> dict[str, object]:
    """Apply hidden provider details without replacing explicit legacy values."""
    merged = dict(secrets)
    profile = FINTS_BANK_PROFILES.get(provider) if source == AccountSource.VOLKSBANK else None
    for key, value in (profile.defaults if profile else {}).items():
        if not merged.get(key):
            merged[key] = value
    return merged
