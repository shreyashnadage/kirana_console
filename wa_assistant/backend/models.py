"""SQLAlchemy ORM models — mirror the init.sql schema."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wa_jid: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["WAMessage"]] = relationship(back_populates="user")
    action_items: Mapped[list["WAActionItem"]] = relationship(back_populates="user")
    outbox: Mapped[list["WAOutbox"]] = relationship(back_populates="user")
    contact_trusts: Mapped[list["WAContactTrust"]] = relationship(back_populates="user")


class WAMessage(Base):
    __tablename__ = "wa_messages"
    __table_args__ = (UniqueConstraint("user_id", "wa_msg_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    wa_msg_id: Mapped[str] = mapped_column(String, nullable=False)
    chat_jid: Mapped[str] = mapped_column(String, nullable=False)
    sender_jid: Mapped[str] = mapped_column(String, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    body_raw: Mapped[str | None] = mapped_column(Text)
    body_english: Mapped[str | None] = mapped_column(Text)
    source_lang: Mapped[str | None] = mapped_column(String(16))
    has_voice: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_s3_key: Mapped[str | None] = mapped_column(String)
    label: Mapped[str | None] = mapped_column(String(32))
    label_confidence: Mapped[float | None] = mapped_column(Float)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    user: Mapped["User"] = relationship(back_populates="messages")
    action_items: Mapped[list["WAActionItem"]] = relationship(back_populates="message")


class WAActionItem(Base):
    __tablename__ = "wa_action_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wa_messages.id", ondelete="CASCADE"))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_hint: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="open")
    briefed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="action_items")
    message: Mapped["WAMessage"] = relationship(back_populates="action_items")


class WAContactTrust(Base):
    __tablename__ = "wa_contact_trust"
    __table_args__ = (UniqueConstraint("user_id", "contact_jid"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    contact_jid: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(SmallInteger, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="contact_trusts")


class WAOutbox(Base):
    __tablename__ = "wa_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    to_jid: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    reply_to_msg_id: Mapped[str | None] = mapped_column(String)
    action_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("wa_action_items.id"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    trust_tier: Mapped[int] = mapped_column(SmallInteger, default=0)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="outbox")


class WAPipelineLog(Base):
    __tablename__ = "wa_pipeline_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    messages_in: Mapped[int | None] = mapped_column(Integer)
    actions_found: Mapped[int | None] = mapped_column(Integer)
    replies_drafted: Mapped[int | None] = mapped_column(Integer)
    claude_tokens: Mapped[int | None] = mapped_column(Integer)
    sarvam_chars: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
