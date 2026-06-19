from typing import Literal

from pydantic import BaseModel, Field


ChatRole = Literal["user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(..., min_length=1, max_length=8000)


class ChatAttachment(BaseModel):
    type: Literal["video"] = "video"
    url: str
    filename: str
    duration_seconds: float | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Conversation history ending with the latest user message",
    )


class ChatResponse(BaseModel):
    message: ChatMessage
    attachments: list[ChatAttachment] = Field(default_factory=list)
