"""Request and response models for the local finance agent."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentMessage(BaseModel):
    role: Literal["user", "assistant", "summary"]
    content: str = Field(min_length=1, max_length=8_000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        return value.strip()


class AgentChatRequest(BaseModel):
    messages: list[AgentMessage] = Field(min_length=1, max_length=200)
    conversation_id: int | None = Field(default=None, gt=0)
    replace_message_id: int | None = Field(default=None, gt=0)
    local_date: date | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+./:-]+$")
    web_search_enabled: bool = True

    @field_validator("messages")
    @classmethod
    def require_last_user_message(cls, value: list[AgentMessage]) -> list[AgentMessage]:
        if value[-1].role != "user":
            raise ValueError("The last message must be from the user")
        return value

    @model_validator(mode="after")
    def replacement_requires_conversation(self):
        if self.replace_message_id is not None and self.conversation_id is None:
            raise ValueError("replace_message_id requires conversation_id")
        return self


class AgentChatResponse(BaseModel):
    conversation_id: int
    user_message_id: int
    assistant_message_id: int
    message: AgentMessage
    context: list[AgentMessage] = Field(default_factory=list)


class AgentStoredMessage(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class AgentConversationSummary(BaseModel):
    id: int
    title: str
    preview: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AgentConversationDetail(AgentConversationSummary):
    messages: list[AgentStoredMessage] = Field(default_factory=list)
