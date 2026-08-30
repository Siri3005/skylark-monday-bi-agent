"""
Skylark Drones – Monday.com BI Agent
Streamlit chat interface.

All data comes from live Monday.com queries — no local Excel files are loaded here.
"""
import os
import sys
import logging
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Skylark Drones BI Agent",
    page_icon="🚁",
    layout="wide",
)

st.title("🚁 Skylark Drones – BI Agent")
st.caption(
    "Ask questions about Skylark's deals pipeline and work order execution. "
    "Answers are pulled live from Monday.com at query time."
)

# ── Config check ───────────────────────────────────────────────────────────────
def _check_config() -> list[str]:
    """Return list of missing config keys."""
    missing = []
    if not os.environ.get("MONDAY_API_TOKEN"):
        missing.append("MONDAY_API_TOKEN")
    if not os.environ.get("DEALS_BOARD_ID"):
        missing.append("DEALS_BOARD_ID")
    if not os.environ.get("WORK_ORDERS_BOARD_ID"):
        missing.append("WORK_ORDERS_BOARD_ID")
    if not os.environ.get("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY")
    return missing

missing_config = _check_config()
if missing_config:
    st.error(
        f"⚠️ Missing configuration: **{', '.join(missing_config)}**\n\n"
        "Set these in your `.env` file (local) or as app secrets (Streamlit Cloud). "
        "See README.md for setup instructions."
    )

# ── Session state ──────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── Suggested questions ────────────────────────────────────────────────────────
SUGGESTED_QUESTIONS = [
    "How many deals and work orders do we have in total?",
    "What's our current open pipeline value?",
    "Break the pipeline down by sector.",
    "How many work orders are active vs completed?",
    "Compare pipeline and execution strength by sector.",
    "Prepare a leadership update.",
]

st.markdown("**Suggested questions:**")
cols = st.columns(3)
for i, q in enumerate(SUGGESTED_QUESTIONS):
    if cols[i % 3].button(q, key=f"sq_{i}"):
        st.session_state["prefill"] = q
        st.rerun()

st.divider()

# ── Chat history ───────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(msg["content"])
            if msg.get("caveat"):
                st.caption(f"ℹ️ {msg['caveat']}")
        else:
            st.markdown(msg["content"])

# ── Input ──────────────────────────────────────────────────────────────────────
prefill = st.session_state.pop("prefill", "")
user_input = st.chat_input("Ask a question about deals, pipeline, or work orders…", key="chat_input")
if prefill:
    user_input = prefill

if user_input:
    # Display user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Call agent
    with st.chat_message("assistant"):
        with st.spinner("Querying Monday.com…"):
            if missing_config:
                result = {
                    "answer": (
                        "⚠️ Cannot query Monday.com — required configuration is missing. "
                        "Please set the missing environment variables listed above."
                    ),
                    "tool_calls": [],
                    "error": "config_missing",
                }
            elif "leadership update" in user_input.lower() or "prepare a leadership" in user_input.lower():
                from agent.loop import run_leadership_update
                result = run_leadership_update()
            else:
                from agent.loop import run_agent
                # Pass conversation history (excluding current user message)
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]
                    if m["role"] in ("user", "assistant")
                ]
                result = run_agent(user_input, history)

        answer = result.get("answer", "No response generated.")
        tool_calls = result.get("tool_calls", [])
        error = result.get("error")

        if error and error not in ("config_missing",):
            st.error(answer)
        else:
            st.markdown(answer)

        # Extract and display data quality caveat separately
        caveat = _extract_caveat(answer)
        if caveat:
            st.caption(f"ℹ️ {caveat}")

        # Show tool call trace in expander for transparency
        if tool_calls:
            with st.expander("🔍 Tool calls (live Monday.com trace)", expanded=False):
                for tc in tool_calls:
                    st.code(
                        f"Tool: {tc.get('tool', 'unknown')}\n"
                        f"Args: {tc.get('args', {})}\n"
                        f"Result: {tc.get('result_summary', '')}",
                        language="text",
                    )

    # Store assistant message
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "caveat": caveat,
    })


def _extract_caveat(text: str) -> str:
    """
    Extract a data quality caveat from answer text if present.
    Looks for common caveat phrases.
    """
    lower = text.lower()
    caveat_phrases = [
        "missing deal value", "no recorded value", "pipeline may be understated",
        "may be higher", "null", "excluded from", "incomplete", "data quality",
        "100% empty", "not supported", "limitation",
    ]
    for phrase in caveat_phrases:
        if phrase in lower:
            # Find the sentence containing the phrase
            for sentence in text.replace("\n", " ").split("."):
                if phrase in sentence.lower() and len(sentence.strip()) > 20:
                    return sentence.strip() + "."
    return ""
