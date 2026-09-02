"""
LangGraph pipeline assembly.

Flow:
  intake → asr? → translate_in → classify → draft? → translate_back? → persist

Conditional branches:
  - intake → asr      only if any message has has_voice=True
  - draft → translate_back  only if any reply_draft is non-English
"""

from langgraph.graph import StateGraph, END

from pipeline.state import PipelineState
from pipeline.nodes import (
    intake_node,
    sarvam_asr_node,
    sarvam_translate_node,
    claude_classify_node,
    claude_draft_node,
    sarvam_translate_back_node,
    persist_node,
)


def _route_voice(state: PipelineState) -> str:
    if any(m.get("has_voice") for m in state["messages"]):
        return "asr"
    return "translate_in"


def _route_drafts(state: PipelineState) -> str:
    # If any draft targets an Indic sender, translate back; else skip
    from pipeline.nodes import INDIC_LANG_CODES
    needs = any(
        state["source_languages"].get(mid) in INDIC_LANG_CODES
        for mid in state["reply_drafts_english"]
    )
    return "translate_back" if needs else "persist"


def build_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("intake",         intake_node)
    g.add_node("asr",            sarvam_asr_node)
    g.add_node("translate_in",   sarvam_translate_node)
    g.add_node("classify",       claude_classify_node)
    g.add_node("draft",          claude_draft_node)
    g.add_node("translate_back", sarvam_translate_back_node)
    g.add_node("persist",        persist_node)

    g.set_entry_point("intake")

    g.add_conditional_edges("intake", _route_voice, {
        "asr":          "asr",
        "translate_in": "translate_in",
    })
    g.add_edge("asr", "translate_in")
    g.add_edge("translate_in", "classify")
    g.add_edge("classify", "draft")
    g.add_conditional_edges("draft", _route_drafts, {
        "translate_back": "translate_back",
        "persist":        "persist",
    })
    g.add_edge("translate_back", "persist")
    g.add_edge("persist", END)

    return g.compile()


# singleton — compiled once at import time
pipeline = build_graph()
