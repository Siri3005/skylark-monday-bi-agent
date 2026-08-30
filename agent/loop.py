"""
Tool-calling agent loop — Google Gemini backend.
Calls Gemini with tool schemas → executes Python tools → returns to Gemini → drafts answer.
All arithmetic and data retrieval happens in tool functions, never in the LLM.
"""
from __future__ import annotations
import os
import json
import re
import logging
from typing import Any

from dotenv import load_dotenv
from agent.system_prompt import SYSTEM_PROMPT, LEADERSHIP_UPDATE_PROMPT
from agent.tool_schemas import TOOL_SCHEMAS
from agent.tool_dispatcher import dispatch_tool

load_dotenv()
logger = logging.getLogger(__name__)

LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-1.5-flash")
MAX_TOOL_ROUNDS = 6


def _get_gemini_client():
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set. Check your .env file or hosting platform secrets.")
    genai.configure(api_key=api_key)
    return genai


def _build_gemini_tools():
    """Convert TOOL_SCHEMAS (OpenAI format) to Gemini FunctionDeclaration format."""
    import google.generativeai as genai
    from google.generativeai.types import FunctionDeclaration, Tool

    declarations = []
    for schema in TOOL_SCHEMAS:
        # Gemini expects parameters as a dict (same JSON Schema format)
        declarations.append(
            FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
            )
        )
    return Tool(function_declarations=declarations)


def run_agent(user_message: str, history: list[dict] | None = None) -> dict:
    """
    Run the tool-calling agent for one user turn using Gemini.
    Returns {"answer": str, "tool_calls": list, "error": str | None}
    history: list of {"role": "user"|"assistant", "content": str}
    """
    try:
        return _run_gemini(user_message, history or [])
    except Exception as e:
        logger.exception("Agent loop error")
        return {
            "answer": f"Something went wrong generating a response — please try again. ({type(e).__name__}: {e})",
            "tool_calls": [],
            "error": str(e),
        }


def _run_gemini(user_message: str, history: list[dict]) -> dict:
    genai = _get_gemini_client()
    import google.generativeai as genai_mod
    from google.generativeai.types import content_types

    tools = _build_gemini_tools()

    model = genai_mod.GenerativeModel(
        model_name=LLM_MODEL,
        system_instruction=SYSTEM_PROMPT,
        tools=[tools],
    )

    # Build conversation history for Gemini
    gemini_history = []
    for h in (history or [])[-10:]:
        role = "user" if h["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [h["content"]]})

    chat = model.start_chat(history=gemini_history)
    all_tool_calls_log = []

    # Send initial user message
    response = chat.send_message(user_message)

    for _round in range(MAX_TOOL_ROUNDS):
        # Check if Gemini wants to call tools
        fn_calls = _extract_function_calls(response)

        if not fn_calls:
            # Final answer
            answer_text = _extract_text(response)
            _check_numeric_provenance(answer_text, all_tool_calls_log)
            return {"answer": answer_text, "tool_calls": all_tool_calls_log, "error": None}

        # Execute all requested tool calls
        tool_response_parts = []
        for fn_name, fn_args in fn_calls:
            logger.info(f"Tool call: {fn_name}({fn_args})")
            tool_result = dispatch_tool(fn_name, fn_args)
            all_tool_calls_log.append({
                "tool": fn_name,
                "args": fn_args,
                "result_summary": _summarize(tool_result),
            })
            tool_response_parts.append(
                genai_mod.protos.Part(
                    function_response=genai_mod.protos.FunctionResponse(
                        name=fn_name,
                        response={"result": json.dumps(tool_result, default=str)},
                    )
                )
            )

        # Send tool results back to Gemini
        response = chat.send_message(tool_response_parts)

    return {
        "answer": "The agent did not produce a final answer after multiple tool calls. Please rephrase your question.",
        "tool_calls": all_tool_calls_log,
        "error": "max_rounds",
    }


def _extract_function_calls(response) -> list[tuple[str, dict]]:
    """Extract all function call requests from a Gemini response."""
    calls = []
    try:
        for part in response.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                name = part.function_call.name
                args = dict(part.function_call.args) if part.function_call.args else {}
                calls.append((name, args))
    except Exception:
        pass
    return calls


def _extract_text(response) -> str:
    """Extract text content from a Gemini response."""
    try:
        return response.text
    except Exception:
        try:
            parts = []
            for part in response.parts:
                if hasattr(part, "text") and part.text:
                    parts.append(part.text)
            return "\n".join(parts)
        except Exception:
            return "No response generated."


# ── Leadership update (multi-tool composition) ─────────────────────────────────

def run_leadership_update() -> dict:
    """
    Compose a leadership update by calling all core metrics tools,
    then synthesizing with Gemini.
    """
    pipeline = dispatch_tool("calculate_pipeline", {})
    revenue_billed = dispatch_tool("calculate_revenue", {"basis": "billed"})
    revenue_collected = dispatch_tool("calculate_revenue", {"basis": "collected"})
    ops = dispatch_tool("calculate_operational_metrics", {})
    sector_perf = dispatch_tool("calculate_sector_performance", {})

    combined = {
        "pipeline": pipeline,
        "revenue_billed": revenue_billed,
        "revenue_collected": revenue_collected,
        "operations": ops,
        "sector_performance": sector_perf,
    }

    synthesis_prompt = (
        f"{LEADERSHIP_UPDATE_PROMPT}\n\nDATA:\n{json.dumps(combined, default=str, indent=2)}"
    )

    try:
        genai = _get_gemini_client()
        import google.generativeai as genai_mod
        model = genai_mod.GenerativeModel(model_name=LLM_MODEL)
        resp = model.generate_content(synthesis_prompt)
        answer = resp.text or ""
    except Exception as e:
        answer = f"Error generating leadership update: {e}"

    return {
        "answer": answer,
        "tool_calls": [
            {"tool": "calculate_pipeline"},
            {"tool": "calculate_revenue(billed)"},
            {"tool": "calculate_revenue(collected)"},
            {"tool": "calculate_operational_metrics"},
            {"tool": "calculate_sector_performance"},
        ],
        "error": None,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _summarize(result: Any) -> str:
    if isinstance(result, dict):
        if "error" in result:
            return f"ERROR: {result['error']}"
        if "result" in result:
            r = result["result"]
            if isinstance(r, dict):
                keys = list(r.keys())[:4]
                return f"{{{', '.join(keys)}, ...}}"
    return str(result)[:120]


def _check_numeric_provenance(answer_text: str, tool_calls_log: list) -> None:
    """Log a warning if the answer contains numbers not present in tool results."""
    if not tool_calls_log:
        return
    answer_numbers = set(re.findall(r"\b\d[\d,\.]*\b", answer_text))
    all_tool_text = json.dumps([tc.get("result_summary", "") for tc in tool_calls_log])
    tool_numbers = set(re.findall(r"\b\d[\d,\.]*\b", all_tool_text))
    suspicious = {n for n in (answer_numbers - tool_numbers) if float(n.replace(",", "")) > 100}
    if suspicious:
        logger.warning(f"Possible hallucinated numbers (not in tool results): {suspicious}")
