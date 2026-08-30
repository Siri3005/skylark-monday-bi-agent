"""
Deterministic agent loop — NO external LLM API.
Architecture:
  User text → Parser → Planner → BI Tools → Monday.com → Responder → User

The architecture is explicitly designed so an LLM could be plugged in
at the Parser/Responder level later, but operates fully without one.
"""
from __future__ import annotations
import logging
from agent.parser import parse_query
from agent.planner import execute_plan
from agent.responder import generate_response

logger = logging.getLogger(__name__)


def run_agent(user_message: str, history: list[dict] | None = None) -> dict:
    """
    Run the deterministic BI agent for one user turn.
    Returns {"answer": str, "tool_calls": list, "error": str | None, "plan": dict}

    No LLM API is called. Query understanding, planning, and response
    generation are all deterministic Python.
    """
    try:
        # Step 1: Parse intent, entities, filters
        parsed = parse_query(user_message)
        logger.info(f"Parsed query: {parsed}")

        # Step 2: If ambiguous, return a clarifying question immediately
        if parsed.ambiguous:
            return {
                "answer": parsed.clarify_message or "Could you be more specific?",
                "tool_calls": [],
                "plan": {"intent": "clarify", "clarify_on": parsed.clarify_on},
                "error": None,
                "is_clarifying": True,
            }

        # Step 3: Execute the query plan (calls BI tools → Monday.com)
        plan_result = execute_plan(parsed)
        plan = plan_result.get("plan", {})
        data = plan_result.get("data", {})
        exec_error = plan_result.get("error")

        if exec_error:
            return {
                "answer": (
                    f"I couldn't retrieve the data from Monday.com right now.\n\n"
                    f"> {exec_error}\n\n"
                    "Please check the connection and try again."
                ),
                "tool_calls": [],
                "plan": plan,
                "error": exec_error,
            }

        # Step 4: Generate conversational response from structured data
        answer = generate_response(parsed, plan, data)

        # Build tool call log for the trace expander
        tool_calls = [{"tool": plan.get("intent", "unknown"), "args": plan}]

        return {
            "answer": answer,
            "tool_calls": tool_calls,
            "plan": plan,
            "error": None,
        }

    except Exception as e:
        logger.exception("Agent loop error")
        return {
            "answer": (
                "Something went wrong while processing your question. "
                "Please try again.\n\n"
                f"*(Error: {type(e).__name__})*"
            ),
            "tool_calls": [],
            "plan": {},
            "error": str(e),
        }


def run_leadership_update() -> dict:
    """Run the leadership update — deterministic multi-tool composition."""
    from agent.parser import ParsedQuery
    from agent.planner import execute_plan
    from agent.responder import generate_response

    q = ParsedQuery()
    q.intent = "leadership"
    q.dataset = "both"
    q.raw = "Prepare a leadership update."

    plan_result = execute_plan(q)
    data = plan_result.get("data", {})
    plan = plan_result.get("plan", {})
    error = plan_result.get("error")

    if error:
        return {
            "answer": f"Could not generate leadership update: {error}",
            "tool_calls": [],
            "plan": plan,
            "error": error,
        }

    answer = generate_response(q, plan, data)
    return {
        "answer": answer,
        "tool_calls": [
            {"tool": "calculate_pipeline"},
            {"tool": "calculate_revenue(billed)"},
            {"tool": "calculate_revenue(collected)"},
            {"tool": "calculate_operational_metrics"},
            {"tool": "calculate_sector_performance"},
        ],
        "plan": plan,
        "error": None,
    }
