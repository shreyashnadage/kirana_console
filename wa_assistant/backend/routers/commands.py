"""
POST /ingest/command — the neonize daemon also calls this for messages coming
FROM the owner's number TO the assistant's number.  That's the WA-as-UI
command channel.

Recognised commands (case-insensitive, prefix-matched):
  ok [N]              — mark action item N done
  skip [N]            — skip / dismiss action item N
  edit [N] [text]     — replace draft reply N with custom text
  done [N]            — same as ok
  !send [name] [msg]  — compose and approve a new outbound message
  !brief              — trigger an immediate morning brief
  !pause              — pause autonomous sends for 24 h
  !status             — reply with current system status
"""

import logging
import re
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db
from models import User, WAActionItem, WAOutbox

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ingest", tags=["commands"])

# Shared flag — a proper Redis-backed flag lands in Phase 2
_paused_until: datetime | None = None


class CommandMessage(BaseModel):
    sender_jid: str
    body: str
    timestamp: str | None = None


async def _send_to_owner(db: AsyncSession, user: User, text: str) -> None:
    """Queue an outbound message back to the owner (auto-approved, tier irrelevant)."""
    db.add(WAOutbox(
        user_id=user.id,
        to_jid=user.wa_jid,
        body=text,
        status="pending",
        trust_tier=3,
        approved_by="system",
        queued_at=datetime.now(timezone.utc),
    ))
    await db.commit()


@router.post("/command", status_code=202)
async def handle_command(cmd: CommandMessage, db: AsyncSession = Depends(get_db)):
    global _paused_until
    from config import settings

    # Only process commands from the owner
    if cmd.sender_jid != settings.owner_wa_jid:
        return {"status": "ignored"}

    user = (await db.execute(select(User).where(User.wa_jid == settings.owner_wa_jid))).scalar_one_or_none()
    if not user:
        return {"status": "no_user"}

    text = (cmd.body or "").strip()
    lower = text.lower()

    # ── ok / done ─────────────────────────────────────────────────────────
    m = re.match(r"^(?:ok|done)\s*(\d+)$", lower)
    if m:
        idx = int(m.group(1))
        item = await _get_action_item_by_index(db, user.id, idx)
        if item:
            item.status = "done"
            item.resolved_at = datetime.now(timezone.utc)
            await db.commit()
            await _send_to_owner(db, user, f"✅ Done — item {idx} marked complete.")
        else:
            await _send_to_owner(db, user, f"No open item #{idx}.")
        return {"status": "ok"}

    # ── skip ──────────────────────────────────────────────────────────────
    m = re.match(r"^skip\s*(\d+)$", lower)
    if m:
        idx = int(m.group(1))
        item = await _get_action_item_by_index(db, user.id, idx)
        if item:
            item.status = "skipped"
            item.resolved_at = datetime.now(timezone.utc)
            await db.commit()
            await _send_to_owner(db, user, f"⏭ Skipped item {idx}.")
        else:
            await _send_to_owner(db, user, f"No open item #{idx}.")
        return {"status": "ok"}

    # ── edit [N] [text] ───────────────────────────────────────────────────
    m = re.match(r"^edit\s+(\d+)\s+(.+)$", text, re.DOTALL | re.IGNORECASE)
    if m:
        idx = int(m.group(1))
        new_text = m.group(2).strip()
        # Find the pending outbox entry for this action item
        item = await _get_action_item_by_index(db, user.id, idx)
        if item:
            result = await db.execute(
                select(WAOutbox).where(
                    WAOutbox.action_item_id == item.id,
                    WAOutbox.status == "pending",
                )
            )
            outbox_row = result.scalar_one_or_none()
            if outbox_row:
                outbox_row.body = new_text
                await db.commit()
                await _send_to_owner(db, user, f"✏️ Draft {idx} updated.")
            else:
                await _send_to_owner(db, user, f"No pending draft for item {idx}.")
        else:
            await _send_to_owner(db, user, f"No open item #{idx}.")
        return {"status": "ok"}

    # ── !send [name] [message] ────────────────────────────────────────────
    m = re.match(r"^!send\s+(\S+)\s+(.+)$", text, re.DOTALL | re.IGNORECASE)
    if m:
        name_or_jid = m.group(1)
        body = m.group(2).strip()
        # Phase 1: treat name_or_jid as a literal JID; Phase 2 adds contact lookup
        to_jid = name_or_jid if "@" in name_or_jid else f"{name_or_jid}@s.whatsapp.net"
        db.add(WAOutbox(
            user_id=user.id,
            to_jid=to_jid,
            body=body,
            status="pending",
            trust_tier=3,  # owner-initiated → auto-approve
            approved_by="owner",
            queued_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        await _send_to_owner(db, user, f"📤 Queued to {to_jid}.")
        return {"status": "ok"}

    # ── !brief ────────────────────────────────────────────────────────────
    if lower.strip() == "!brief":
        from scheduler import run_morning_brief
        import asyncio
        asyncio.create_task(run_morning_brief(user))
        await _send_to_owner(db, user, "📋 Generating brief now…")
        return {"status": "ok"}

    # ── !pause ────────────────────────────────────────────────────────────
    if lower.strip() == "!pause":
        _paused_until = datetime.now(timezone.utc) + timedelta(hours=24)
        await _send_to_owner(db, user, "⏸ Autonomous sends paused for 24 h.")
        return {"status": "ok"}

    # ── !status ───────────────────────────────────────────────────────────
    if lower.strip() == "!status":
        open_count = (await db.execute(
            select(WAActionItem).where(WAActionItem.user_id == user.id, WAActionItem.status == "open")
        )).scalars().all()
        pending_out = (await db.execute(
            select(WAOutbox).where(WAOutbox.user_id == user.id, WAOutbox.status == "pending")
        )).scalars().all()
        paused_msg = f"\n⏸ Paused until {_paused_until.strftime('%H:%M UTC')}" if _paused_until and _paused_until > datetime.now(timezone.utc) else ""
        await _send_to_owner(
            db, user,
            f"📊 Status\n{len(open_count)} open action items\n{len(pending_out)} pending outbound{paused_msg}"
        )
        return {"status": "ok"}

    # unknown command — echo back help
    help_text = (
        "Commands:\n"
        "ok N / done N — mark item done\n"
        "skip N — dismiss item\n"
        "edit N [text] — update draft\n"
        "!send JID msg — send message\n"
        "!brief — show brief now\n"
        "!pause — pause 24 h\n"
        "!status — system status"
    )
    await _send_to_owner(db, user, help_text)
    return {"status": "unknown_command"}


async def _get_action_item_by_index(db: AsyncSession, user_id, idx: int) -> WAActionItem | None:
    """Fetch open action items ordered by created_at and return the Nth (1-based)."""
    result = await db.execute(
        select(WAActionItem)
        .where(WAActionItem.user_id == user_id, WAActionItem.status == "open")
        .order_by(WAActionItem.created_at)
    )
    items = result.scalars().all()
    if 1 <= idx <= len(items):
        return items[idx - 1]
    return None
