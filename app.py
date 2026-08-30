"""
Skylark Drones – Monday.com BI Agent
Streamlit chat interface.

Deterministic agent — no external LLM API.
All data comes from live Monday.com queries at query time.
"""
import os
import sys
import logging
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)


def _extract_caveat(text: str) -> str:
    """Extract a data quality caveat sentence from answer text."""
    lower = text.lower()
    phrases = [
        "missing", "no recorded value", "may be higher", "excluded from",
        "data note", "100% empty", "not supported", "understated",
    ]
    for phrase in phrases:
        if phrase in lower:
            for sentence in text.replace("\n", " ").split("."):
                if phrase in sentence.lower() and len(sentence.strip()) > 25:
                    return sentence.strip() + "."
    return ""


def _check_config() -> list[str]:
    missing = []
    if not os.environ.get("MONDAY_API_TOKEN"):
        missing.append("MONDAY_API_TOKEN")
    if not os.environ.get("DEALS_BOARD_ID"):
        missing.append("DEALS_BOARD_ID")
    if not os.environ.get("WORK_ORDERS_BOARD_ID"):
        missing.append("WORK_ORDERS_BOARD_ID")
    return missing


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Skylark Drones BI Agent",
    page_icon="🚁",
    layout="wide",
)

st.title("🚁 Skylark Drones – BI Agent")
st.caption(
    "Ask founder-level questions about deals pipeline and work order execution. "
    "Answers are pulled live from Monday.com — no external AI API required."
)

missing_config = _check_config()
if missing_config:
    st.error(
        f"⚠️ Missing configuration: **{', '.join(missing_config)}**\n\n"
        "Set these in your `.env` file (local) or as app secrets (Streamlit Cloud)."
    )

# ── Session state ──────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Suggested questions ────────────────────────────────────────────────────────
SUGGESTED_QUESTIONS = [
    "How many deals and work orders do we have?",
    "What's our open pipeline value?",
    "Break the pipeline down by sector.",
    "How much is outstanding in receivables?",
    "How many work orders are active vs completed?",
    "Compare pipeline and execution by sector.",
    "Which deals are likely to close soon?",
    "Prepare a leadership update.",
]

st.markdown("**Try asking:**")
cols = st.columns(4)
for i, q in enumerate(SUGGESTED_QUESTIONS):
    if cols[i % 4].button(q, key=f"sq_{i}"):
        st.session_state["prefill"] = q
        st.rerun()

st.divider()

# ── Chat history ───────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Input ──────────────────────────────────────────────────────────────────────
prefill = st.session_state.pop("prefill", "")
user_input = st.chat_input("Ask about pipeline, billing, work orders, receivables…")
if prefill:
    user_input = prefill

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Querying Monday.com…"):
            if missing_config:
                result = {
                    "answer": "⚠️ Configuration missing — please set the required environment variables.",
                    "tool_calls": [], "error": "config_missing",
                }
            else:
                from agent.loop import run_agent, run_leadership_update
                if "leadership update" in user_input.lower() or "prepare a leadership" in user_input.lower():
                    result = run_leadership_update()
                else:
                    result = run_agent(user_input)

        answer = result.get("answer", "No response generated.")
        tool_calls = result.get("tool_calls", [])
        plan = result.get("plan", {})
        error = result.get("error")
        is_clarifying = result.get("is_clarifying", False)

        if error and error != "config_missing":
            st.error(answer)
        else:
            st.markdown(answer)

        # Show plan/provenance for non-clarifying responses
        if plan and not is_clarifying and not error:
            with st.expander("🔍 Query plan (how this was answered)", expanded=False):
                import json
                st.code(json.dumps(plan, default=str, indent=2), language="json")

    st.session_state.messages.append({"role": "assistant", "content": answer})
