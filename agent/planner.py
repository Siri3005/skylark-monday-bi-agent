"""
Query planner — converts a ParsedQuery into an execution plan,
then runs the appropriate BI tools and returns structured results.
No external LLM. Fully deterministic.
"""
from __future__ import annotations
import logging
from datetime import date, datetime
from typing import Any, Optional

from agent.parser import ParsedQuery
from agent.tool_dispatcher import dispatch_tool

logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now().date()


def execute_plan(q: ParsedQuery) -> dict:
    """
    Convert a ParsedQuery into tool calls and return the combined result.
    Returns: {
        "data": {...},           # raw tool results
        "plan": {...},           # what was executed (for provenance display)
        "error": str | None
    }
    """
    plan = _make_plan(q)
    logger.info(f"Executing plan: {plan}")

    try:
        data = _execute(q, plan)
        return {"data": data, "plan": plan, "error": None}
    except Exception as e:
        logger.exception(f"Plan execution failed: {e}")
        return {"data": {}, "plan": plan, "error": str(e)}


def _make_plan(q: ParsedQuery) -> dict:
    """Describe the execution plan for provenance."""
    return {
        "intent": q.intent,
        "dataset": q.dataset,
        "metric": q.metric,
        "sector": q.sector,
        "period": q.period,
        "groupby": q.groupby,
        "deal_status": q.deal_status,
        "wo_status": q.wo_status,
    }


def _execute(q: ParsedQuery, plan: dict) -> dict:
    """Execute the plan against the BI tools."""

    # ── Leadership update ─────────────────────────────────────────────────────
    if q.intent == "leadership":
        pipeline = dispatch_tool("calculate_pipeline", {})
        revenue_billed = dispatch_tool("calculate_revenue", {"basis": "billed"})
        revenue_collected = dispatch_tool("calculate_revenue", {"basis": "collected"})
        ops = dispatch_tool("calculate_operational_metrics", {})
        sector = dispatch_tool("calculate_sector_performance", {})
        return {
            "pipeline": pipeline,
            "revenue_billed": revenue_billed,
            "revenue_collected": revenue_collected,
            "operations": ops,
            "sector_performance": sector,
        }

    # ── Data quality ──────────────────────────────────────────────────────────
    if q.intent == "quality":
        board = None
        if q.dataset == "deals":
            board = "deals"
        elif q.dataset == "work_orders":
            board = "work_orders"
        return dispatch_tool("check_data_quality", {"board": board})

    # ── Count ─────────────────────────────────────────────────────────────────
    if q.intent == "count":
        result = {}
        if q.dataset in ("deals", "both"):
            result["deals"] = dispatch_tool("get_deals", {
                "status_filter": q.deal_status,
                "sector_filter": q.sector,
            })
        if q.dataset in ("work_orders", "both"):
            result["work_orders"] = dispatch_tool("get_work_orders", {
                "status_filter": [q.wo_status] if q.wo_status else None,
                "sector_filter": q.sector,
            })
        return result

    # ── Pipeline ──────────────────────────────────────────────────────────────
    if q.intent == "pipeline":
        args: dict[str, Any] = {}
        if q.sector:
            args["sector"] = q.sector
        if q.period and q.period not in ("last_year", "this_year"):
            args["period"] = q.period
        if q.deal_status:
            args["status"] = q.deal_status
        if q.groupby == "stage":
            args["stage"] = None  # return all stages
        return dispatch_tool("calculate_pipeline", args)

    # ── Upcoming closures / at-risk ───────────────────────────────────────────
    if q.intent in ("upcoming_closures", "at_risk"):
        args = {}
        if q.sector:
            args["sector"] = q.sector
        args["period"] = q.period or "this_quarter"
        args["status"] = ["Open", "On Hold"]
        return dispatch_tool("calculate_pipeline", args)

    # ── Revenue ───────────────────────────────────────────────────────────────
    if q.intent == "revenue":
        basis = q.metric if q.metric in ("billed", "collected", "deal_value") else "billed"
        args = {"basis": basis}
        if q.sector:
            args["sector"] = q.sector
        if q.period and q.period not in ("last_year", "this_year"):
            args["period"] = q.period
        return dispatch_tool("calculate_revenue", args)

    # ── Billing ───────────────────────────────────────────────────────────────
    if q.intent == "billing":
        args = {"basis": "billed"}
        if q.sector:
            args["sector"] = q.sector
        if q.period and q.period not in ("last_year", "this_year"):
            args["period"] = q.period
        return dispatch_tool("calculate_revenue", args)

    # ── Collections ───────────────────────────────────────────────────────────
    if q.intent == "collections":
        args = {"basis": "collected"}
        if q.sector:
            args["sector"] = q.sector
        if q.period and q.period not in ("last_year", "this_year"):
            args["period"] = q.period
        return dispatch_tool("calculate_revenue", args)

    # ── Receivables ───────────────────────────────────────────────────────────
    if q.intent == "receivables":
        args = {}
        if q.sector:
            args["sector"] = q.sector
        if q.groupby == "customer":
            # Need raw records for per-customer breakdown
            return dispatch_tool("get_work_orders", {"sector_filter": q.sector})
        return dispatch_tool("calculate_operational_metrics", args)

    # ── Operations / Work Orders ──────────────────────────────────────────────
    if q.intent == "ops":
        args = {}
        if q.sector:
            args["sector"] = q.sector
        if q.wo_status:
            args["status"] = q.wo_status
        return dispatch_tool("calculate_operational_metrics", args)

    # ── Cross-board ───────────────────────────────────────────────────────────
    if q.intent == "cross_board":
        question_type = q.metric or "pipeline_vs_execution"
        args = {"question_type": question_type}
        if q.sector:
            args["sector"] = q.sector
        return dispatch_tool("cross_board_metric", args)

    # ── Sector performance ────────────────────────────────────────────────────
    if q.intent == "sector_performance":
        return dispatch_tool("calculate_sector_performance", {"sector": q.sector})

    # ── Summary / Overview ────────────────────────────────────────────────────
    if q.intent == "summary":
        pipeline = dispatch_tool("calculate_pipeline", {})
        ops = dispatch_tool("calculate_operational_metrics", {})
        return {"pipeline": pipeline, "operations": ops}

    # ── Fallback ──────────────────────────────────────────────────────────────
    return {"error": f"Could not map intent '{q.intent}' to a tool. Please rephrase your question."}
