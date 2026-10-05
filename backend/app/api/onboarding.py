"""First-run onboarding state stored inside the encrypted app settings."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.deps import require_unlocked
from app.services.secure_settings import (
    ensure_app_settings,
    update_model_preferences,
)
from app.services.ollama_setup import request_model_setup

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class OnboardingUpdate(BaseModel):
    completed: bool


@router.get("")
def onboarding_status(
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, bool]:
    preferences = ensure_app_settings(session, dek)
    return {"completed": preferences.onboarding_completed}


@router.put("")
def update_onboarding(
    update: OnboardingUpdate,
    session: Session = Depends(get_session),
    dek: bytes = Depends(require_unlocked),
) -> dict[str, bool]:
    preferences = update_model_preferences(
        session,
        dek,
        onboarding_completed=update.completed,
    )
    if preferences.onboarding_completed:
        request_model_setup()
    return {"completed": preferences.onboarding_completed}
