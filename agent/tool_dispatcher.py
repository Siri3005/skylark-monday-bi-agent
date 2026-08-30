"""
Tool dispatcher — maps tool names to their Python implementations.
This is the only place where tool name → function mapping lives.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def dispatch_tool(tool_name: str, args: dict) -> Any:
    """
    Call the named tool with the given arguments.
    Returns JSON-serializable result dict.
    Catches exceptions and returns error dict rather than crashing the agent loop.
    """
    try:
        if tool_name == "get_deals":
            from tools.retrieval import get_deals
            return get_deals(
                status_filter=args.get("status_filter"),
                sector_filter=args.get("sector_filter"),
                date_from=_parse_date(args.get("date_from")),
                date_to=_parse_date(args.get("date_to")),
                date_field=args.get("date_field", "tentative_close_date"),
            )

        elif tool_name == "get_work_orders":
            from tools.retrieval import get_work_orders
            return get_work_orders(
                status_filter=args.get("status_filter"),
                sector_filter=args.get("sector_filter"),
                date_from=_parse_date(args.get("date_from")),
                date_to=_parse_date(args.get("date_to")),
            )

        elif tool_name == "calculate_pipeline":
            from tools.calculations import calculate_pipeline
            return calculate_pipeline(
                sector=args.get("sector"),
                stage=args.get("stage"),
                period=args.get("period"),
                weighted=args.get("weighted", False),
                status=args.get("status"),
            )

        elif tool_name == "calculate_revenue":
            from tools.calculations import calculate_revenue
            return calculate_revenue(
                basis=args.get("basis", "billed"),
                sector=args.get("sector"),
                period=args.get("period"),
            )

        elif tool_name == "calculate_operational_metrics":
            from tools.calculations import calculate_operational_metrics
            return calculate_operational_metrics(
                status=args.get("status"),
                sector=args.get("sector"),
            )

        elif tool_name == "calculate_sector_performance":
            from tools.calculations import calculate_sector_performance
            return calculate_sector_performance(sector=args.get("sector"))

        elif tool_name == "cross_board_metric":
            from tools.cross_board import cross_board_metric
            return cross_board_metric(
                question_type=args.get("question_type", "pipeline_vs_execution"),
                sector=args.get("sector"),
            )

        elif tool_name == "check_data_quality":
            from tools.data_quality import check_data_quality
            return check_data_quality(board=args.get("board"))

        else:
            logger.warning(f"Unknown tool: {tool_name}")
            return {"error": f"Unknown tool '{tool_name}'. Available tools are listed in the tool schemas."}

    except Exception as e:
        logger.exception(f"Tool {tool_name} raised an exception: {e}")
        return {
            "error": f"Tool '{tool_name}' encountered an error: {type(e).__name__}: {e}",
            "tool": tool_name,
            "args": args,
        }


def _parse_date(date_str: str | None):
    """Parse ISO date string to date object, or return None."""
    if not date_str:
        return None
    from datetime import date
    try:
        return date.fromisoformat(date_str)
    except (ValueError, AttributeError):
        return None
