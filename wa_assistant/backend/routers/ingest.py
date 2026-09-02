"""
POST /ingest/message — called by the neonize daemon on every inbound WA message.

Phase 1: write to wa_messages and return 202.  The LangGraph pipeline runs on a
schedule (morning brief), not per-message, so no pipeline is triggered here.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, WAMessage

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["ingest"])


class InboundMessage(BaseModel):
    wa_msg_id: str
    chat_jid: str
    sender_jid: str
    sender_name: str | None = None
    body: str | None = None
    has_voice: bool = False
    timestamp: str | None = None  # ISO8601


@router.post("/message", status_code=202)
async def ingest_message(msg: InboundMessage, db: AsyncSession = Depends(get_db)):
    from config import settings

    # Resolve (or create) the user record keyed on OWNER_WA_JID.
    # Phase 1 is single-user; in Phase 2 this becomes a proper auth lookup.
    user = (await db.execute(select(User).where(User.wa_jid == settings.owner_wa_jid))).scalar_one_or_none()
    if not user:
        user = User(wa_jid=settings.owner_wa_jid)
        db.add(user)
        await db.flush()

    # Deduplicate by WA message ID
    existing = (await db.execute(
        select(WAMessage).where(WAMessage.user_id == user.id, WAMessage.wa_msg_id == msg.wa_msg_id)
    )).scalar_one_or_none()
    if existing:
        return {"status": "duplicate"}

    received_at = None
    if msg.timestamp:
        try:
            received_at = datetime.fromisoformat(msg.timestamp.replace("Z", "+00:00"))
        except ValueError:
            pass

    record = WAMessage(
        user_id=user.id,
        wa_msg_id=msg.wa_msg_id,
        chat_jid=msg.chat_jid,
        sender_jid=msg.sender_jid,
        sender_name=msg.sender_name,
        body_raw=msg.body,
        has_voice=msg.has_voice,
        received_at=received_at or datetime.now(timezone.utc),
    )
    db.add(record)
    await db.commit()

    log.info("ingested msg %s from %s (voice=%s)", msg.wa_msg_id, msg.sender_jid, msg.has_voice)
    return {"status": "ok"}
