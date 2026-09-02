-- WhatsApp Assistant — PostgreSQL schema
-- All tables carry user_id so the schema is multi-tenant-ready from day one
-- even though Phase 1 runs single-user.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ── users ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wa_jid      TEXT NOT NULL UNIQUE,   -- 91XXXXXXXXXX@s.whatsapp.net
    display_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── wa_messages ───────────────────────────────────────────────────────────────
-- One row per inbound WA message. Outbound assistant messages are NOT stored here
-- (they live in wa_outbox while queued; delivered ones are ephemeral).
CREATE TABLE IF NOT EXISTS wa_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    wa_msg_id       TEXT NOT NULL,                    -- WA's own message ID
    chat_jid        TEXT NOT NULL,                    -- group or DM JID
    sender_jid      TEXT NOT NULL,                    -- individual sender JID
    sender_name     TEXT,                             -- push name at receipt time
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    body_raw        TEXT,                             -- original text (may be Indic)
    body_english    TEXT,                             -- Sarvam-translated English, if translated
    source_lang     TEXT,                             -- BCP-47 code detected by Sarvam, 'en' if already english
    has_voice       BOOLEAN NOT NULL DEFAULT FALSE,
    voice_s3_key    TEXT,                             -- future: store audio for replay
    label           TEXT,                             -- noise | info | action | reply_needed
    label_confidence REAL,
    pipeline_run_id UUID,                             -- which pipeline run classified this
    UNIQUE (user_id, wa_msg_id)
);
CREATE INDEX IF NOT EXISTS wa_messages_user_chat ON wa_messages (user_id, chat_jid, received_at DESC);
CREATE INDEX IF NOT EXISTS wa_messages_label ON wa_messages (user_id, label, received_at DESC);

-- ── wa_action_items ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wa_action_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message_id      UUID NOT NULL REFERENCES wa_messages(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,                    -- Claude-extracted action in English
    due_hint        TEXT,                             -- e.g. "tomorrow", "Monday", "end of week"
    status          TEXT NOT NULL DEFAULT 'open',     -- open | done | skipped
    briefed_at      TIMESTAMPTZ,                      -- when it appeared in a morning brief
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS wa_action_items_user_status ON wa_action_items (user_id, status, created_at DESC);

-- ── wa_contact_trust ─────────────────────────────────────────────────────────
-- Per-contact trust tier for outbound actions.
-- T0 = draft only, T1 = needs approval, T2 = template auto, T3 = autonomous narrow
CREATE TABLE IF NOT EXISTS wa_contact_trust (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    contact_jid TEXT NOT NULL,
    tier        SMALLINT NOT NULL DEFAULT 0 CHECK (tier BETWEEN 0 AND 3),
    note        TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, contact_jid)
);

-- ── wa_outbox ─────────────────────────────────────────────────────────────────
-- Queued outbound messages. Backend writes here; neonize daemon polls and sends.
CREATE TABLE IF NOT EXISTS wa_outbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_jid          TEXT NOT NULL,
    body            TEXT NOT NULL,
    reply_to_msg_id TEXT,                             -- WA quoted-reply ID, if any
    action_item_id  UUID REFERENCES wa_action_items(id),
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | failed
    trust_tier      SMALLINT NOT NULL DEFAULT 0,
    approved_by     TEXT,                             -- 'owner' or null if auto-approved
    queued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS wa_outbox_pending ON wa_outbox (user_id, status, queued_at)
    WHERE status = 'pending';

-- ── wa_pipeline_log ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wa_pipeline_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    messages_in     INT,
    actions_found   INT,
    replies_drafted INT,
    claude_tokens   INT,
    sarvam_chars    INT,
    error           TEXT
);
