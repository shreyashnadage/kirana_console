"""
LangGraph node implementations.

Each node receives the full PipelineState, updates a subset of it,
and returns the delta dict that LangGraph merges back into state.

External calls:
  - Sarvam AI REST API  (ASR + translate)
  - Anthropic Claude    (classify + draft)
"""

import json
import logging
from typing import Any

import httpx
from anthropic import AsyncAnthropic

from config import settings
from pipeline.state import PipelineState

log = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"
INDIC_LANG_CODES = {"hi", "mr", "gu", "bn", "ta", "te", "kn", "ml", "pa", "or"}

_claude = AsyncAnthropic(api_key=settings.anthropic_api_key)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _sarvam_translate(text: str, source_lang: str, target_lang: str = "en-IN") -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{SARVAM_BASE}/translate",
            headers={"api-subscription-key": settings.sarvam_api_key},
            json={
                "input": text,
                "source_language_code": source_lang,
                "target_language_code": target_lang,
                "speaker_gender": "Male",
                "mode": "formal",
                "enable_preprocessing": True,
            },
        )
        r.raise_for_status()
        return r.json()["translated_text"]


async def _sarvam_detect_lang(text: str) -> str:
    """Use translate endpoint to detect language (source=auto)."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"{SARVAM_BASE}/translate",
            headers={"api-subscription-key": settings.sarvam_api_key},
            json={
                "input": text[:500],  # detection only needs a snippet
                "source_language_code": "auto",
                "target_language_code": "en-IN",
                "enable_preprocessing": False,
            },
        )
        r.raise_for_status()
        data = r.json()
        return data.get("source_language_code", "en")


# ── nodes ─────────────────────────────────────────────────────────────────────

async def intake_node(state: PipelineState) -> dict[str, Any]:
    """Filter out empty messages; pass everything else to the pipeline."""
    filtered = [m for m in state["messages"] if m.get("body_raw") or m.get("has_voice")]
    return {"messages": filtered}


async def sarvam_asr_node(state: PipelineState) -> dict[str, Any]:
    """
    Transcribe voice notes via Sarvam Saarika ASR.
    Phase 1: voice_s3_key is not yet stored, so this node is a pass-through
    placeholder. When audio storage lands, fetch the file from S3 and POST
    to /speech-to-text.
    """
    transcriptions: dict[str, str] = {}
    chars_used = state["sarvam_chars_used"]

    for msg in state["messages"]:
        if not msg.get("has_voice"):
            continue
        # TODO Phase 2: fetch audio bytes from S3/R2, POST to Sarvam ASR
        # For now mark as placeholder so downstream nodes don't crash
        transcriptions[msg["id"]] = "[voice note — transcription pending]"

    return {"voice_transcriptions": transcriptions, "sarvam_chars_used": chars_used}


async def sarvam_translate_node(state: PipelineState) -> dict[str, Any]:
    """
    Detect language and translate Indic messages to English.
    Already-English messages are passed through unchanged.
    """
    source_langs: dict[str, str] = {}
    english_texts: dict[str, str] = {}
    chars_used = state["sarvam_chars_used"]

    for msg in state["messages"]:
        msg_id = msg["id"]
        # prefer ASR transcription over raw body for voice notes
        text = state["voice_transcriptions"].get(msg_id) or msg.get("body_raw") or ""
        if not text.strip():
            continue

        try:
            lang = await _sarvam_detect_lang(text)
        except Exception as exc:
            log.warning("lang detect failed for %s: %s", msg_id, exc)
            lang = "en"

        source_langs[msg_id] = lang

        if lang in INDIC_LANG_CODES:
            try:
                translated = await _sarvam_translate(text, lang)
                chars_used += len(text)
            except Exception as exc:
                log.warning("translate failed for %s: %s", msg_id, exc)
                translated = text  # fall back to raw
            english_texts[msg_id] = translated
        else:
            english_texts[msg_id] = text

    return {
        "source_languages": source_langs,
        "english_texts": english_texts,
        "sarvam_chars_used": chars_used,
    }


_CLASSIFY_SYSTEM = """You are an intelligent assistant that processes WhatsApp messages for a busy professional in India.

For each message, output a JSON object with:
  - msg_id: the message id
  - label: one of "noise" | "info" | "action" | "reply_needed"
  - confidence: 0.0–1.0
  - summary: one-sentence English summary (max 15 words)
  - action_items: list of {description, due_hint} — non-empty only when label is "action"

Definitions:
  noise       — spam, memes, forwards, greetings, irrelevant chatter
  info        — FYI, updates, news that requires no action from the recipient
  action      — something the recipient needs to DO (pay, attend, approve, call back, etc.)
  reply_needed — a direct question or request addressed to the recipient needing a response

Output a JSON array, one object per message. No prose outside JSON."""


async def claude_classify_node(state: PipelineState) -> dict[str, Any]:
    """Batch-classify all messages in one Claude call to minimise latency and cost."""
    texts = state["english_texts"]
    if not texts:
        return {"classifications": [], "action_items": [], "claude_tokens_used": state["claude_tokens_used"]}

    batch = [
        {"msg_id": mid, "chat": state["messages"][i]["chat_jid"], "text": t}
        for i, (mid, t) in enumerate(texts.items())
    ]
    # Rebuild index for fast lookup
    msg_by_id = {m["id"]: m for m in state["messages"]}

    prompt = json.dumps(batch, ensure_ascii=False)

    response = await _claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=_CLASSIFY_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    tokens_used = state["claude_tokens_used"] + (response.usage.input_tokens + response.usage.output_tokens)

    try:
        classifications = json.loads(response.content[0].text)
    except Exception as exc:
        log.error("classify parse failed: %s\nRaw: %s", exc, response.content[0].text[:500])
        return {
            "classifications": [],
            "action_items": [],
            "claude_tokens_used": tokens_used,
            "error": f"classify parse: {exc}",
        }

    flat_actions: list[dict] = []
    for item in classifications:
        for a in item.get("action_items", []):
            flat_actions.append({
                "msg_id": item["msg_id"],
                "description": a.get("description", ""),
                "due_hint": a.get("due_hint"),
            })

    return {
        "classifications": classifications,
        "action_items": flat_actions,
        "claude_tokens_used": tokens_used,
    }


_DRAFT_SYSTEM = """You are drafting WhatsApp replies on behalf of a stockist (B2B distributor) in India.
Keep replies concise, polite, and professional. Match the register of the original message.
Output only the reply text — no preamble, no quotes, no formatting characters.
If you are unsure what to say, output exactly: [NEEDS_REVIEW]"""


async def claude_draft_node(state: PipelineState) -> dict[str, Any]:
    """Draft replies for messages classified as reply_needed."""
    reply_msgs = [c for c in state["classifications"] if c.get("label") == "reply_needed"]
    if not reply_msgs:
        return {"reply_drafts_english": {}, "claude_tokens_used": state["claude_tokens_used"]}

    msg_by_id = {m["id"]: m for m in state["messages"]}
    drafts: dict[str, str] = {}
    tokens_used = state["claude_tokens_used"]

    for item in reply_msgs:
        mid = item["msg_id"]
        text = state["english_texts"].get(mid, "")
        msg = msg_by_id.get(mid, {})
        context = f"From: {msg.get('sender_name', 'unknown')} in chat {msg.get('chat_jid', '')}\n\n{text}"

        response = await _claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=_DRAFT_SYSTEM,
            messages=[{"role": "user", "content": context}],
        )
        tokens_used += response.usage.input_tokens + response.usage.output_tokens
        drafts[mid] = response.content[0].text.strip()

    return {"reply_drafts_english": drafts, "claude_tokens_used": tokens_used}


async def sarvam_translate_back_node(state: PipelineState) -> dict[str, Any]:
    """Translate English reply drafts back to the sender's language."""
    final: dict[str, str] = {}
    chars_used = state["sarvam_chars_used"]

    for mid, draft in state["reply_drafts_english"].items():
        lang = state["source_languages"].get(mid, "en")
        if lang in INDIC_LANG_CODES:
            try:
                translated = await _sarvam_translate(draft, "en-IN", lang)
                chars_used += len(draft)
                final[mid] = translated
            except Exception as exc:
                log.warning("translate-back failed for %s: %s", mid, exc)
                final[mid] = draft
        else:
            final[mid] = draft

    return {"final_replies": final, "sarvam_chars_used": chars_used}


async def persist_node(state: PipelineState) -> dict[str, Any]:
    """
    Write classification results, action items, and reply drafts back to
    PostgreSQL. The actual DB write is done by the caller (scheduler.py /
    routers/ingest.py) after the graph completes, using the returned state.
    This node is a no-op placeholder — keeping the graph structure clean so
    Phase 2 can swap in a real async DB write here without touching the graph.
    """
    return {}
