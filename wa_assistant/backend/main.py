"""
WhatsApp Assistant — FastAPI backend

Startup sequence:
  1. Verify DB is reachable
  2. Start APScheduler (morning brief + outbox flush)
  3. Mount routers

The neonize daemon runs in its own container and calls:
  POST /ingest/message  — for every inbound WA message
  POST /ingest/command  — for messages from the owner to the assistant's number
"""

import logging

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers.ingest import router as ingest_router
from routers.commands import router as commands_router
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("wa_backend")

app = FastAPI(title="WhatsApp Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(commands_router)


@app.on_event("startup")
async def on_startup() -> None:
    start_scheduler()
    log.info("Backend started — owner JID: %s", settings.owner_wa_jid)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/neonize/status")
async def neonize_status() -> dict:
    """Proxy the neonize daemon's /status endpoint for convenience."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.neonize_url}/status")
            return r.json()
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


@app.get("/neonize/qr")
async def neonize_qr() -> dict:
    """Proxy the neonize daemon's /qr endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.neonize_url}/qr")
            return r.json()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
