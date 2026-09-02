"""
WhatsApp daemon — wraps neonize-python and exposes a tiny HTTP API so the
backend can fetch the QR code and trigger outbound sends without importing
the neonize library itself.

HTTP surface (port 9999):
  GET  /qr          → {qr: "<base64-png>", expires_in: N} or {status: "connected"}
  GET  /status       → {connected: bool, jid: str|null}
  POST /send         → {to: "JID", body: "text"} → {ok: bool}

On every inbound message the daemon POSTs to $BACKEND_URL/ingest/message.

neonize API targets: neonize >= 2.0
  Exact proto field names may shift across minor versions — check the neonize
  changelog if you see AttributeError on evt.Message fields.
"""

import asyncio
import base64
import io
import json
import logging
import os
import threading
import time
from typing import Optional

import httpx
import qrcode
from aiohttp import web

try:
    from neonize.client import NewClient
    from neonize.events import (
        ConnectedEv,
        MessageEv,
        QRUpdatedEv,
        PairStatusEv,
        DisconnectedEv,
    )
    from neonize.proto.Neonize_pb2 import Message  # outbound message builder
    import neonize.proto.waE2E.WAWebProtobufsE2E_pb2 as wae2e
except ImportError as e:
    raise SystemExit(f"neonize not installed: {e}") from e

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wa_daemon")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
SESSION_PATH = os.environ.get("SESSION_PATH", "/app/session")
DAEMON_PORT = int(os.environ.get("DAEMON_PORT", "9999"))

# ── shared state between neonize thread and aiohttp thread ───────────────────
_lock = threading.Lock()
_state: dict = {
    "connected": False,
    "jid": None,
    "qr_png_b64": None,        # current QR as base64-encoded PNG
    "qr_generated_at": None,   # epoch seconds
    "qr_ttl": 60,              # WA QR codes live ~60 s
}
_client: Optional[NewClient] = None


def _make_qr_png_b64(qr_string: str) -> str:
    img = qrcode.make(qr_string)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── neonize event handlers ────────────────────────────────────────────────────

def _on_qr(conn: "NewClient", evt: "QRUpdatedEv") -> None:
    png_b64 = _make_qr_png_b64(evt.Code)
    with _lock:
        _state.update(
            connected=False,
            qr_png_b64=png_b64,
            qr_generated_at=time.time(),
        )
    log.info("QR updated — scan within %ds", _state["qr_ttl"])


def _on_connected(conn: "NewClient", evt: "ConnectedEv") -> None:
    jid = str(conn.get_current_user_id()) if hasattr(conn, "get_current_user_id") else None
    with _lock:
        _state.update(connected=True, jid=jid, qr_png_b64=None)
    log.info("WhatsApp connected — JID: %s", jid)


def _on_pair_status(conn: "NewClient", evt: "PairStatusEv") -> None:
    log.info("Pair status: %s", evt)


def _on_disconnected(conn: "NewClient", evt: "DisconnectedEv") -> None:
    with _lock:
        _state["connected"] = False
    log.warning("WhatsApp disconnected")


def _extract_text(msg: "wae2e.Message") -> Optional[str]:
    if msg.conversation:
        return msg.conversation
    if msg.extendedTextMessage and msg.extendedTextMessage.text:
        return msg.extendedTextMessage.text
    return None


def _on_message(conn: "NewClient", evt: "MessageEv") -> None:
    info = evt.Info
    # skip messages this device sent
    if info.IsFromMe:
        return

    text = _extract_text(evt.Message) if evt.Message else None
    has_voice = bool(
        evt.Message and (evt.Message.audioMessage.url or evt.Message.audioMessage.fileLength)
    ) if evt.Message else False

    payload = {
        "wa_msg_id": info.ID,
        "chat_jid": str(info.Chat),
        "sender_jid": str(info.Sender),
        "sender_name": info.PushName or None,
        "body": text,
        "has_voice": has_voice,
        "timestamp": info.Timestamp.isoformat() if hasattr(info.Timestamp, "isoformat") else str(info.Timestamp),
    }

    # Fire-and-forget POST to backend; retry once on transient errors
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(f"{BACKEND_URL}/ingest/message", json=payload)
            if r.status_code not in (200, 202):
                log.warning("Backend ingest returned %d", r.status_code)
    except Exception as exc:
        log.error("Failed to POST message to backend: %s", exc)


# ── neonize thread ────────────────────────────────────────────────────────────

def _run_neonize() -> None:
    global _client
    os.makedirs(SESSION_PATH, exist_ok=True)
    _client = NewClient(os.path.join(SESSION_PATH, "session"))

    _client.event(QRUpdatedEv)(_on_qr)
    _client.event(ConnectedEv)(_on_connected)
    _client.event(PairStatusEv)(_on_pair_status)
    _client.event(DisconnectedEv)(_on_disconnected)
    _client.event(MessageEv)(_on_message)

    log.info("Starting neonize client…")
    _client.connect()   # blocks until disconnect


# ── aiohttp HTTP surface ──────────────────────────────────────────────────────

async def handle_qr(request: web.Request) -> web.Response:
    with _lock:
        s = dict(_state)

    if s["connected"]:
        return web.json_response({"status": "connected", "jid": s["jid"]})

    if not s["qr_png_b64"]:
        return web.json_response({"status": "idle"}, status=202)

    age = time.time() - (s["qr_generated_at"] or 0)
    expires_in = max(0, int(s["qr_ttl"] - age))
    return web.json_response({
        "status": "pairing",
        "qr": s["qr_png_b64"],
        "expires_in": expires_in,
    })


async def handle_status(request: web.Request) -> web.Response:
    with _lock:
        s = dict(_state)
    return web.json_response({"connected": s["connected"], "jid": s["jid"]})


async def handle_send(request: web.Request) -> web.Response:
    if _client is None or not _state["connected"]:
        return web.json_response({"ok": False, "error": "not connected"}, status=503)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "bad json"}, status=400)

    to_jid = body.get("to")
    text = body.get("body", "")
    if not to_jid or not text:
        return web.json_response({"ok": False, "error": "to and body required"}, status=400)

    try:
        from neonize.types import JID
        jid = JID.parse(to_jid)
        msg = Message(conversation=text)
        await asyncio.to_thread(_client.send_message, jid, msg)
        return web.json_response({"ok": True})
    except Exception as exc:
        log.error("send_message failed: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=500)


async def _run_http() -> None:
    app = web.Application()
    app.router.add_get("/qr", handle_qr)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/send", handle_send)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", DAEMON_PORT)
    await site.start()
    log.info("Daemon HTTP listening on :%d", DAEMON_PORT)
    # run forever
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    # neonize is blocking + not asyncio-native, so run it in a thread
    t = threading.Thread(target=_run_neonize, daemon=True, name="neonize")
    t.start()

    asyncio.run(_run_http())


if __name__ == "__main__":
    main()
