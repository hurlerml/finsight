"""Persisted conversations for the local finance agent."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, func
from sqlmodel import Field, SQLModel


class AgentConversation(SQLModel, table=True):
    __tablename__ = "agent_conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
            index=True,
        )
    )


class AgentConversationMessage(SQLModel, table=True):
    __tablename__ = "agent_conversation_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(
        sa_column=Column(
            ForeignKey("agent_conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    encrypted_payload: Optional[bytes] = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    encryption_version: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    )
