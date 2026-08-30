"""
Tool-calling agent loop.
Calls LLM with tool schemas → executes Python tools → returns to LLM → drafts answer.
Supports OpenAI and Anthropic APIs.
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

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").lower()
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o")

MAX_TOOL_ROUNDS = 6   # prevent infinite loops


def run_agent(user_message: str, history: list[dict] | None = None) -> dict:
    """
    Run the tool-calling agent for one user turn.
    Returns {"answer": str, "tool_calls": list, "error": str | None}
    history: list of {"role": "user"|"assistant", "content": str}
    """
    try:
        if LLM_PROVIDER == "anthropic":
            return _run_anthropic(user_message, history or [])
        else:
            return _run_openai(user_message, history or [])
    except Exception as e:
        logger.exception("Agent loop error")
        return {
            "answer": f"Something went wrong generating a response — please try again. ({type(e).__name__})",
            "tool_calls": [],
            "error": str(e),
        }


# ── OpenAI path ────────────────────────────────────────────────────────────────

def _run_openai(user_message: str, history: list[dict]) -> dict:
    from openai import OpenAI, APIError, AuthenticationError, RateLimitError

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "answer": "OpenAI API key is not configured. Set OPENAI_API_KEY in your .env file.",
            "tool_calls": [], "error": "missing_api_key"
        }

    client = OpenAI(api_key=api_key)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history[-10:]:   # keep last 10 turns
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    tools = [{"type": "function", "function": t} for t in TOOL_SCHEMAS]
    all_tool_calls_log = []

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0,
            )
        except AuthenticationError:
            return {"answer": "OpenAI authentication failed — check OPENAI_API_KEY.", "tool_calls": [], "error": "auth"}
        except RateLimitError:
            return {"answer": "OpenAI rate limit reached — please try again shortly.", "tool_calls": [], "error": "rate_limit"}
        except APIError as e:
            return {"answer": f"OpenAI API error: {e}", "tool_calls": [], "error": str(e)}

        msg = response.choices[0].message
        finish = response.choices[0].finish_reason

        if finish == "tool_calls" and msg.tool_calls:
            messages.append(msg)   # assistant message with tool_calls
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}
                logger.info(f"Tool call: {fn_name}({fn_args})")
                tool_result = dispatch_tool(fn_name, fn_args)
                all_tool_calls_log.append({
                    "tool": fn_name, "args": fn_args, "result_summary": _summarize(tool_result)
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, default=str),
                })
            continue

        # Final answer
        answer_text = msg.content or ""
        _check_numeric_provenance(answer_text, all_tool_calls_log)
        return {"answer": answer_text, "tool_calls": all_tool_calls_log, "error": None}

    return {
        "answer": "The agent did not produce a final answer after multiple tool calls. Please rephrase your question.",
        "tool_calls": all_tool_calls_log, "error": "max_rounds"
    }


# ── Anthropic path ─────────────────────────────────────────────────────────────

def _run_anthropic(user_message: str, history: list[dict]) -> dict:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "answer": "Anthropic API key is not configured. Set ANTHROPIC_API_KEY in your .env file.",
            "tool_calls": [], "error": "missing_api_key"
        }

    client = anthropic.Anthropic(api_key=api_key)

    # Convert TOOL_SCHEMAS to Anthropic format
    tools = []
    for t in TOOL_SCHEMAS:
        tools.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        })

    messages = []
    for h in history[-10:]:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_message})

    all_tool_calls_log = []

    for _round in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=LLM_MODEL if "claude" in LLM_MODEL else "claude-3-5-sonnet-20241022",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    fn_name = block.name
                    fn_args = block.input or {}
                    logger.info(f"Tool call: {fn_name}({fn_args})")
                    tool_result = dispatch_tool(fn_name, fn_args)
                    all_tool_calls_log.append({
                        "tool": fn_name, "args": fn_args, "result_summary": _summarize(tool_result)
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(tool_result, default=str),
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Final answer
        answer_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                answer_text += block.text
        _check_numeric_provenance(answer_text, all_tool_calls_log)
        return {"answer": answer_text, "tool_calls": all_tool_calls_log, "error": None}

    return {
        "answer": "The agent did not produce a final answer after multiple tool calls.",
        "tool_calls": all_tool_calls_log, "error": "max_rounds"
    }


# ── Leadership update (multi-tool composition) ─────────────────────────────────

def run_leadership_update() -> dict:
    """
    Compose a leadership update by calling all core metrics tools,
    then synthesizing with LLM. This is NOT a scheduled report.
    """
    from agent.tool_dispatcher import dispatch_tool
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

    if LLM_PROVIDER == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
        resp = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            messages=[{"role": "user", "content": synthesis_prompt}],
        )
        answer = resp.content[0].text if resp.content else ""
    else:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0,
        )
        answer = resp.choices[0].message.content or ""

    return {
        "answer": answer,
        "tool_calls": [
            {"tool": "calculate_pipeline"}, {"tool": "calculate_revenue(billed)"},
            {"tool": "calculate_revenue(collected)"}, {"tool": "calculate_operational_metrics"},
            {"tool": "calculate_sector_performance"},
        ],
        "error": None,
    }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _summarize(result: Any) -> str:
    """Produce a brief summary of a tool result for logging."""
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
    """
    Lightweight hallucination check: extract numbers from the answer and
    verify they appear somewhere in tool results. Log warnings only.
    This is a soft check — not a hard block (per §14 note).
    """
    if not tool_calls_log:
        return
    answer_numbers = set(re.findall(r"\b\d[\d,\.]*\b", answer_text))
    all_tool_text = json.dumps([tc.get("result_summary", "") for tc in tool_calls_log])
    tool_numbers = set(re.findall(r"\b\d[\d,\.]*\b", all_tool_text))
    suspicious = answer_numbers - tool_numbers
    # Filter out common non-data numbers (years, small ordinals, etc.)
    suspicious = {n for n in suspicious if float(n.replace(",", "")) > 100}
    if suspicious:
        logger.warning(f"Possible hallucinated numbers (not in tool results): {suspicious}")
