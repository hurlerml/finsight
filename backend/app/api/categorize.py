from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.deps import require_unlocked
from app.models import Account, Category
from app.schemas.categorize import (
    CategorizeCurrentRead,
    CategorizeDoneRead,
    CategorizeStatusRead,
    RecategorizeRead,
    RecategorizeRequest,
)
from app.services.categorize import reset_automatic_categories
from app.services.llm_categorize import (
    get_categorize_status,
    invalidate_classification_context,
    retry_transactions,
)

router = APIRouter(prefix="/api/categorize", tags=["categorize"])


@router.get("/status", response_model=CategorizeStatusRead)
def categorize_status(_dek: bytes = Depends(require_unlocked)) -> CategorizeStatusRead:
    st = get_categorize_status()
    return CategorizeStatusRead(
        ollama_configured=st.ollama_configured,
        ollama_reachable=st.ollama_reachable,
        phase=st.phase,
        queue_remaining=st.queue_remaining,
        queue_total=st.queue_total,
        queue_processed=st.queue_processed,
        current=(
            CategorizeCurrentRead(
                id=st.current.id,
                booking_date=st.current.booking_date,
                counterparty=st.current.counterparty,
                amount=st.current.amount,
            )
            if st.current
            else None
        ),
        last_done=[
            CategorizeDoneRead(id=item.id, slug=item.slug, confidence=item.confidence)
            for item in st.last_done
        ],
        llm_applied_session=st.llm_applied_session,
        message=st.message,
    )


@router.post("/reprocess", response_model=RecategorizeRead)
def reprocess_categories(
    body: RecategorizeRequest,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> RecategorizeRead:
    if body.account_id is not None and session.get(Account, body.account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if body.category_id is not None and session.get(Category, body.category_id) is None:
        raise HTTPException(status_code=404, detail="Category not found")
    invalidate_classification_context()
    reset_count, rules_applied, queued_ids = reset_automatic_categories(
        session,
        account_id=body.account_id,
        category_id=body.category_id,
        include_manual=body.include_manual,
    )
    retry_transactions(queued_ids)
    return RecategorizeRead(
        reset_count=reset_count,
        rules_applied=rules_applied,
        queued_for_agent=len(queued_ids),
    )
