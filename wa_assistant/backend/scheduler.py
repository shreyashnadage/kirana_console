"""
APScheduler jobs:
  1. morning_brief  — run pipeline on overnight messages, send brief to owner
  2. outbox_flush   — poll wa_outbox and send pending messages via neonize daemon

Both jobs share the async DB session factory directly (no FastAPI dependency injection).
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from config import settings
from db import AsyncSessionLocal
from models import User, WAMessage, WAActionItem, WAOutbox, WAPipelineLog
from pipeline.graph import pipeline

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


# ── morning brief ─────────────────────────────────────────────────────────────

async def run_morning_brief(user: User | None = None) -> None:
    async with AsyncSessionLocal() as db:
        if user is None:
            user = (await db.execute(
                select(User).where(User.wa_jid == settings.owner_wa_jid)
            )).scalar_one_or_none()
        if not user:
            log.warning("morning brief: no owner user found")
            return

        # Fetch messages since the last brief (last 24 h as a safe default)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        msgs_result = await db.execute(
            select(WAMessage).where(
                WAMessage.user_id == user.id,
                WAMessage.received_at >= cutoff,
                WAMessage.label.is_(None),  # unclassified only
            ).order_by(WAMessage.received_at)
        )
        messages = msgs_result.scalars().all()

        if not messages:
            log.info("morning brief: no new messages to process")
            await _send_wa(user.wa_jid, "☀️ Good morning! No new action items since yesterday.")
            return

        run_id = uuid.uuid4()
        log_row = WAPipelineLog(
            id=run_id,
            user_id=user.id,
            messages_in=len(messages),
        )
        db.add(log_row)
        await db.flush()

        # Run LangGraph pipeline
        msg_dicts = [
            {
                "id": str(m.id),
                "wa_msg_id": m.wa_msg_id,
                "chat_jid": m.chat_jid,
                "sender_jid": m.sender_jid,
                "sender_name": m.sender_name,
                "body_raw": m.body_raw,
                "has_voice": m.has_voice,
            }
            for m in messages
        ]
        initial_state = {
            "user_id": str(user.id),
            "run_id": str(run_id),
            "messages": msg_dicts,
            "voice_transcriptions": {},
            "source_languages": {},
            "english_texts": {},
            "classifications": [],
            "action_items": [],
            "reply_drafts_english": {},
            "final_replies": {},
            "claude_tokens_used": 0,
            "sarvam_chars_used": 0,
            "error": None,
        }

        try:
            result = await pipeline.ainvoke(initial_state)
        except Exception as exc:
            log.error("pipeline failed: %s", exc)
            log_row.error = str(exc)
            log_row.finished_at = datetime.now(timezone.utc)
            await db.commit()
            return

        # Persist classifications back to WAMessage rows
        cls_by_id = {c["msg_id"]: c for c in result["classifications"]}
        for m in messages:
            cls = cls_by_id.get(str(m.id))
            if cls:
                m.label = cls["label"]
                m.label_confidence = cls.get("confidence")
                m.body_english = result["english_texts"].get(str(m.id))
                m.source_lang = result["source_languages"].get(str(m.id), "en")
                m.pipeline_run_id = run_id

        # Persist action items
        new_items: list[WAActionItem] = []
        for a in result["action_items"]:
            item = WAActionItem(
                user_id=user.id,
                message_id=uuid.UUID(a["msg_id"]),
                description=a["description"],
                due_hint=a.get("due_hint"),
                briefed_at=datetime.now(timezone.utc),
            )
            db.add(item)
            new_items.append(item)

        # Queue reply drafts as pending outbox rows (trust tier 0 = draft only)
        for mid, draft in result["final_replies"].items():
            m_obj = next((m for m in messages if str(m.id) == mid), None)
            if not m_obj:
                continue
            db.add(WAOutbox(
                user_id=user.id,
                to_jid=m_obj.sender_jid,
                body=draft,
                reply_to_msg_id=m_obj.wa_msg_id,
                status="pending",
                trust_tier=0,  # needs owner approval before sending
            ))

        # Update pipeline log
        log_row.finished_at = datetime.now(timezone.utc)
        log_row.actions_found = len(result["action_items"])
        log_row.replies_drafted = len(result["final_replies"])
        log_row.claude_tokens = result["claude_tokens_used"]
        log_row.sarvam_chars = result["sarvam_chars_used"]

        await db.commit()

        # Format and send morning brief message
        brief = _format_brief(result, new_items)
        await _send_wa(user.wa_jid, brief)
        log.info("morning brief sent — %d actions, %d drafts", log_row.actions_found, log_row.replies_drafted)


def _format_brief(result: dict, action_items: list) -> str:
    lines = ["☀️ *Morning Brief*\n"]

    open_actions = [a for a in action_items]
    if open_actions:
        lines.append(f"*{len(open_actions)} Action Item(s):*")
        for i, item in enumerate(open_actions, 1):
            due = f" (due: {item.due_hint})" if item.due_hint else ""
            lines.append(f"  {i}. {item.description}{due}")
        lines.append("")

    reply_count = len(result.get("final_replies", {}))
    if reply_count:
        lines.append(f"*{reply_count} Reply Draft(s) awaiting review*")
        lines.append("  Reply `ok N` to approve, `edit N [text]` to modify")
        lines.append("")

    if not open_actions and not reply_count:
        lines.append("All clear — no open items.")

    lines.append("_Reply `!status` for system info_")
    return "\n".join(lines)


# ── outbox flush ──────────────────────────────────────────────────────────────

async def flush_outbox() -> None:
    """Send pending outbox rows that are auto-approved (trust_tier >= 1) or owner-approved."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WAOutbox).where(
                WAOutbox.status == "pending",
                WAOutbox.trust_tier >= 1,   # tier 0 = draft only, never auto-send
            ).order_by(WAOutbox.queued_at).limit(20)
        )
        rows = result.scalars().all()
        for row in rows:
            try:
                ok = await _send_wa(row.to_jid, row.body)
                row.status = "sent" if ok else "failed"
                row.sent_at = datetime.now(timezone.utc)
            except Exception as exc:
                row.status = "failed"
                row.error = str(exc)
                log.error("outbox flush failed for %s: %s", row.id, exc)
        await db.commit()


async def _send_wa(to_jid: str, body: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{settings.neonize_url}/send",
                json={"to": to_jid, "body": body},
            )
            return r.status_code == 200 and r.json().get("ok")
    except Exception as exc:
        log.error("_send_wa to %s failed: %s", to_jid, exc)
        return False


# ── scheduler setup ───────────────────────────────────────────────────────────

def start_scheduler() -> None:
    hour, minute = settings.brief_time_utc.split(":")
    scheduler.add_job(
        run_morning_brief,
        trigger="cron",
        hour=int(hour),
        minute=int(minute),
        id="morning_brief",
        replace_existing=True,
    )
    scheduler.add_job(
        flush_outbox,
        trigger="interval",
        minutes=1,
        id="outbox_flush",
        replace_existing=True,
    )
    scheduler.start()
    log.info("Scheduler started — brief at %s UTC, outbox flush every 1 min", settings.brief_time_utc)
