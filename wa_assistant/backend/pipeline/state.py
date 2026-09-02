from typing import TypedDict


class PipelineState(TypedDict):
    user_id: str
    run_id: str

    # Raw message dicts fetched from DB before pipeline starts
    messages: list[dict]

    # msg_id → transcribed text (filled by sarvam_asr_node for voice notes)
    voice_transcriptions: dict[str, str]

    # msg_id → BCP-47 language code detected by Sarvam translate (e.g. "hi", "mr", "gu")
    source_languages: dict[str, str]

    # msg_id → English text ready for Claude
    # For already-English messages this is just body_raw; for Indic it's the translation
    english_texts: dict[str, str]

    # Claude classification output per message
    # [{msg_id, label, confidence, summary, action_items: [{description, due_hint}]}]
    classifications: list[dict]

    # Flat list of extracted action items across all messages
    action_items: list[dict]

    # msg_id → Claude draft reply in English (for label==reply_needed messages)
    reply_drafts_english: dict[str, str]

    # msg_id → final reply in the sender's language (translated back if needed)
    final_replies: dict[str, str]

    # Running token/char counters for cost tracking
    claude_tokens_used: int
    sarvam_chars_used: int

    error: str | None
