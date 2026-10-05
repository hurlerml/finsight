"""Chat and conversation endpoints for the local, read-only finance agent."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func
from sqlmodel import Session, col, select

from app.db import engine, get_session
from app.deps import require_unlocked
from app.models import AgentConversation, AgentConversationMessage
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationDetail,
    AgentConversationSummary,
    AgentMessage,
    AgentStoredMessage,
)
from app.services.agent import chat, stream_chat
from app.services.llm_categorize import probe_ollama
from app.services.secure_repository import (
    decrypted_conversation_payload,
    decrypted_message_payload,
    insert_conversation_payload,
    insert_message_payload,
    update_conversation_payload,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Keep chat runs alive after a browser disconnects. The task set also keeps a
# strong reference until each run has persisted its final answer, preventing
# the event loop from collecting a detached task while Ollama is working.
_chat_tasks: set[asyncio.Task[None]] = set()


@dataclass
class _PreparedChat:
    conversation: AgentConversation | None
    replaced_message: AgentConversationMessage | None
    messages_before_replacement: list[AgentConversationMessage]
    agent_messages: list[AgentMessage]


def _conversation_title(text: str, max_length: int = 72) -> str:
    """Build a compact title without spending a second model request."""
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    shortened = normalized[: max_length - 1].rsplit(" ", 1)[0]
    return f"{shortened or normalized[: max_length - 1]}…"


def _stored_context(
    conversation: AgentConversation, dek: bytes
) -> list[AgentMessage]:
    context: list[AgentMessage] = []
    payload = decrypted_conversation_payload(conversation, dek)
    for item in payload.get("context") or []:
        try:
            context.append(AgentMessage.model_validate(item))
        except (TypeError, ValueError):
            continue
    return context


def _messages_for(session: Session, conversation_id: int) -> list[AgentConversationMessage]:
    return list(
        session.exec(
            select(AgentConversationMessage)
            .where(AgentConversationMessage.conversation_id == conversation_id)
            .order_by(col(AgentConversationMessage.created_at), col(AgentConversationMessage.id))
        ).all()
    )


def _summary(
    conversation: AgentConversation,
    messages: list[AgentConversationMessage],
    dek: bytes,
) -> AgentConversationSummary:
    if conversation.id is None:
        raise RuntimeError("Conversation has not been persisted")
    private_conversation = decrypted_conversation_payload(conversation, dek)
    preview = (
        str(decrypted_message_payload(messages[-1], dek).get("content") or "")
        if messages
        else ""
    )
    if len(preview) > 120:
        preview = f"{preview[:119].rstrip()}…"
    return AgentConversationSummary(
        id=conversation.id,
        title=str(private_conversation.get("title") or ""),
        preview=preview,
        message_count=len(messages),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _prepare_chat(session: Session, body: AgentChatRequest, dek: bytes) -> _PreparedChat:
    conversation: AgentConversation | None = None
    replaced_message: AgentConversationMessage | None = None
    messages_before_replacement: list[AgentConversationMessage] = []
    agent_messages = body.messages
    if body.conversation_id is None:
        return _PreparedChat(
            conversation=None,
            replaced_message=None,
            messages_before_replacement=[],
            agent_messages=agent_messages,
        )

    conversation = session.get(AgentConversation, body.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if body.replace_message_id is None:
        return _PreparedChat(
            conversation=conversation,
            replaced_message=None,
            messages_before_replacement=[],
            agent_messages=[*_stored_context(conversation, dek), body.messages[-1]],
        )

    replaced_message = session.get(AgentConversationMessage, body.replace_message_id)
    if (
        replaced_message is None
        or replaced_message.conversation_id != conversation.id
        or decrypted_message_payload(replaced_message, dek).get("role") != "user"
    ):
        raise HTTPException(status_code=404, detail="Editable message not found")
    messages_before_replacement = list(
        session.exec(
            select(AgentConversationMessage)
            .where(
                AgentConversationMessage.conversation_id == conversation.id,
                AgentConversationMessage.id < replaced_message.id,
            )
            .order_by(col(AgentConversationMessage.id))
        ).all()
    )
    agent_messages = [
        *[
            AgentMessage(
                role=str(decrypted_message_payload(message, dek).get("role") or ""),
                content=str(decrypted_message_payload(message, dek).get("content") or ""),
            )
            for message in messages_before_replacement
            if decrypted_message_payload(message, dek).get("role") in {"user", "assistant"}
        ],
        body.messages[-1],
    ]
    return _PreparedChat(
        conversation=conversation,
        replaced_message=replaced_message,
        messages_before_replacement=messages_before_replacement,
        agent_messages=agent_messages,
    )


def _persist_chat(
    session: Session,
    body: AgentChatRequest,
    prepared: _PreparedChat,
    answer: str,
    context: list[AgentMessage],
    dek: bytes,
) -> AgentChatResponse:
    conversation = prepared.conversation
    if conversation is None:
        conversation = insert_conversation_payload(
            session,
            dek,
            title=_conversation_title(body.messages[-1].content),
            context=[],
        )
    if conversation.id is None:
        raise HTTPException(status_code=500, detail="Could not save conversation")

    replaced_message = prepared.replaced_message
    if replaced_message is not None and replaced_message.id is not None:
        session.exec(
            delete(AgentConversationMessage).where(
                AgentConversationMessage.conversation_id == conversation.id,
                AgentConversationMessage.id >= replaced_message.id,
            )
        )
        if not any(
            decrypted_message_payload(message, dek).get("role") == "user"
            for message in prepared.messages_before_replacement
        ):
            update_conversation_payload(
                session, conversation, dek,
                title=_conversation_title(body.messages[-1].content),
            )

    update_conversation_payload(
        session, conversation, dek,
        context=[item.model_dump() for item in context],
        updated_at=datetime.now(timezone.utc),
    )
    user_message = insert_message_payload(
        session,
        dek,
        conversation_id=conversation.id,
        role="user",
        content=body.messages[-1].content,
    )
    assistant_message = insert_message_payload(
        session,
        dek,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
    )
    if user_message.id is None or assistant_message.id is None:
        raise HTTPException(status_code=500, detail="Could not save messages")
    session.commit()
    session.refresh(conversation)

    return AgentChatResponse(
        conversation_id=conversation.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        message=AgentMessage(role="assistant", content=answer),
        context=context,
    )


@router.get("/conversations", response_model=list[AgentConversationSummary])
def list_conversations(
    limit: int = 30,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> list[AgentConversationSummary]:
    safe_limit = max(1, min(limit, 100))
    conversations = list(
        session.exec(
            select(AgentConversation)
            .order_by(col(AgentConversation.updated_at).desc())
            .limit(safe_limit)
        ).all()
    )
    conversation_ids = [item.id for item in conversations if item.id is not None]
    if not conversation_ids:
        return []
    counts = dict(
        session.exec(
            select(
                AgentConversationMessage.conversation_id,
                func.count(AgentConversationMessage.id),
            )
            .where(col(AgentConversationMessage.conversation_id).in_(conversation_ids))
            .group_by(AgentConversationMessage.conversation_id)
        ).all()
    )
    latest_message_ids = (
        select(func.max(AgentConversationMessage.id))
        .where(col(AgentConversationMessage.conversation_id).in_(conversation_ids))
        .group_by(AgentConversationMessage.conversation_id)
    )
    latest_messages = list(
        session.exec(
            select(AgentConversationMessage).where(
                col(AgentConversationMessage.id).in_(latest_message_ids)
            )
        ).all()
    )
    previews = {
        message.conversation_id: str(
            decrypted_message_payload(message, _dek).get("content") or ""
        )
        for message in latest_messages
    }
    summaries: list[AgentConversationSummary] = []
    for conversation in conversations:
        if conversation.id is None:
            continue
        preview = previews.get(conversation.id, "")
        if len(preview) > 120:
            preview = f"{preview[:119].rstrip()}…"
        summaries.append(
            AgentConversationSummary(
                id=conversation.id,
                title=str(
                    decrypted_conversation_payload(conversation, _dek).get("title") or ""
                ),
                preview=preview,
                message_count=counts.get(conversation.id, 0),
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
    return summaries


@router.get("/conversations/{conversation_id}", response_model=AgentConversationDetail)
def get_conversation(
    conversation_id: int,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> AgentConversationDetail:
    conversation = session.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = _messages_for(session, conversation_id)
    summary = _summary(conversation, messages, _dek)
    return AgentConversationDetail(
        **summary.model_dump(),
        messages=[
            AgentStoredMessage(
                id=message.id,
                role=str(decrypted_message_payload(message, _dek).get("role") or ""),
                content=str(decrypted_message_payload(message, _dek).get("content") or ""),
                created_at=message.created_at,
            )
            for message in messages
            if message.id is not None
            and decrypted_message_payload(message, _dek).get("role") in {"user", "assistant"}
        ],
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> Response:
    conversation = session.get(AgentConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    session.exec(
        delete(AgentConversationMessage).where(
            AgentConversationMessage.conversation_id == conversation_id
        )
    )
    session.delete(conversation)
    session.commit()
    return Response(status_code=204)


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    body: AgentChatRequest,
    session: Session = Depends(get_session),
    _dek: bytes = Depends(require_unlocked),
) -> AgentChatResponse:
    if not probe_ollama():
        raise HTTPException(status_code=503, detail="Local model is unavailable")
    prepared = _prepare_chat(session, body, _dek)

    try:
        answer, context = await chat(
            session,
            prepared.agent_messages,
            current_date=body.local_date,
            timezone=body.timezone,
            web_search_enabled=body.web_search_enabled,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Antwort des lokalen Modells fehlgeschlagen: {exc}") from exc
    return _persist_chat(session, body, prepared, answer, context, _dek)


@router.post("/chat/stream")
async def agent_chat_stream(
    body: AgentChatRequest,
    _dek: bytes = Depends(require_unlocked),
) -> StreamingResponse:
    if not probe_ollama():
        raise HTTPException(status_code=503, detail="Local model is unavailable")

    events: asyncio.Queue[str | None] = asyncio.Queue()
    client_connected = True

    async def emit(event: dict[str, object]) -> None:
        if client_connected:
            await events.put(json.dumps(event, ensure_ascii=False))

    async def run_chat() -> None:
        with Session(engine) as session:
            try:
                prepared = _prepare_chat(session, body, _dek)
                async for event in stream_chat(
                    session,
                    prepared.agent_messages,
                    current_date=body.local_date,
                    timezone=body.timezone,
                    web_search_enabled=body.web_search_enabled,
                ):
                    if event.get("type") != "result":
                        await emit(event)
                        continue
                    response = _persist_chat(
                        session,
                        body,
                        prepared,
                        str(event["answer"]),
                        list(event["context"]),
                        _dek,
                    )
                    await emit(
                        {
                            "type": "complete",
                            "response": response.model_dump(mode="json"),
                        }
                    )
                    return
            except HTTPException as exc:
                session.rollback()
                await emit({"type": "error", "detail": str(exc.detail)})
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                await emit(
                    {
                        "type": "error",
                        "detail": f"Antwort des lokalen Modells fehlgeschlagen: {exc}",
                    }
                )
            finally:
                # A disconnected client does not consume this sentinel, but
                # leaving it in the unbounded queue is harmless and keeps the
                # normal streaming path explicit and deterministic.
                await events.put(None)

    task = asyncio.create_task(run_chat(), name="finsight-agent-chat")
    _chat_tasks.add(task)
    task.add_done_callback(_chat_tasks.discard)

    async def generate() -> AsyncIterator[str]:
        nonlocal client_connected
        try:
            while True:
                event = await events.get()
                if event is None:
                    return
                yield f"{event}\n"
        except asyncio.CancelledError:
            # The browser closing only cancels this response generator. The
            # detached chat task above continues, persists the final answer,
            # and the next history refresh can display it.
            return
        finally:
            client_connected = False

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
