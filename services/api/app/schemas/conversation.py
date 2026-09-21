"""Conversation request and response models.

Mirrors `conversation.schema.json` and the conversation operations in `public-api.yaml`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.envelope import PageMeta, ResponseMeta


class ConversationModel(BaseModel):
    """A thread of assistant turns about a trip."""

    model_config = ConfigDict(frozen=True)

    conversation_id: UUID
    trip_id: UUID | None = None
    title: Annotated[str | None, Field(max_length=256)] = None
    last_message_preview: Annotated[str | None, Field(max_length=512)] = None
    last_recommendation_id: UUID | None = None
    message_count: Annotated[int, Field(ge=0)]
    created_at: datetime
    updated_at: datetime


class ConversationMessageRequest(BaseModel):
    """A follow-up question sent to an assistant thread.

    `extra="forbid"`, because unrecognised fields could bypass prompt boundaries.
    """

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=2000)]
    trip_id: UUID | None = None
    locale: Annotated[
        str | None,
        Field(max_length=35, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$"),
    ] = None


class ConversationListResponse(BaseModel):
    """Paginated list of conversation summaries."""

    model_config = ConfigDict(frozen=True)

    data: list[ConversationModel]
    meta: ResponseMeta
    page: PageMeta
