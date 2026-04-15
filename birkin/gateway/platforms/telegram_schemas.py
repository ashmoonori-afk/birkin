"""Telegram Bot API update schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class User(BaseModel):
    """Telegram User object."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class Chat(BaseModel):
    """Telegram Chat object."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    type: str  # "private", "group", "supergroup", "channel"
    title: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PhotoSize(BaseModel):
    """Telegram PhotoSize object."""

    file_id: str
    file_unique_id: str
    width: int
    height: int
    file_size: Optional[int] = None


class Document(BaseModel):
    """Telegram Document object."""

    file_id: str
    file_unique_id: str
    thumbnail: Optional[PhotoSize] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None


class Message(BaseModel):
    """Telegram Message object (subset of fields)."""

    model_config = ConfigDict(populate_by_name=True)

    message_id: int
    date: int
    chat: Chat
    from_user: User = Field(..., alias="from")
    text: Optional[str] = None
    document: Optional[Document] = None
    photo: Optional[list[PhotoSize]] = None
    reply_to_message: Optional[Message] = None


class Update(BaseModel):
    """Telegram Update object (webhook payload)."""

    model_config = ConfigDict(populate_by_name=True)

    update_id: int
    message: Optional[Message] = None
