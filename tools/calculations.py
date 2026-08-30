"""
Deterministic calculation tools.
ALL arithmetic happens here in pure Python — the LLM never computes numbers.
Every function returns a JSON-serializable dict with 'result' + 'data_quality'.
"""
from __future__ import annotations
import logging
from datetime import date, datetime
from typing import Any, Optional
from collections import defaultdict

from tools.retrieval import get_deals, get_work_orders
from monday.schema import CLOSURE_PROBABILITY_WEIGHTS, ACTIVE_EXECUTION_STATUSES

logger = logging.getLogger(__name__)


def _today() -> date:
    """Return today's date from system clock — never hardcoded."""
    return datetime.now().date()


def _quarter_bounds(d: date) -> tuple[date, date]:
    """Return (start, end) of the calendar quarter containing d."""
    q = (d.month - 1) // 3
    starts = [1, 4, 7, 10]
    ends = [3, 6, 9, 12]
    start = date(d.year, starts[q], 1)
    end_month = ends[q]
    end_day = 31 if end_month in [1, 3, 5, 7, 8, 10, 12] else 30 if end_month in [4, 6, 9, 11] else 28
    end = date(d.year, end_month, end_day)
    return (start, end)


def _last_quarter_bounds(d: date) -> tuple[date, date]:
    q = (d.month - 1) // 3
    if q == 0:
        start = date(d.year - 1, 10, 1)
        end = date(d.year - 1, 12, 31)
    else:
        starts = [None, 1, 4, 7]
        ends = [None, 3, 6, 9]
        end_days = [None, 31, 30, 30]
        start = date(d.year, starts[q], 1)
        end = date(d.year, ends[q], end_days[q])
    return (start, end)


def calculate_pipeline(
    sector: Optional[str] = None,
    stage: Optional[str] = None,
    period: Optional[str] = None,   # "this_quarter", "last_quarter", "this_month", or None
    weighted: bool = False,
    status: Optional[list[str]] = None,
) -> dict:
    """
    Calculate pipeline value from open deals.
    By default, 'Open' and 'On Hold' deals are included.
    Returns total value, count, breakdown by sector and stage.
    """
    statuses = status or ["Open", "On Hold"]
    result = get_deals(status_filter=statuses, sector_filter=sector)

    if "error" in result:
        return {"error": result["error"]}

    records = result["records"]
    dq = result["data_quality"]

    # Date filter for tentative close
    today = _today()
    date_from, date_to = None, None
    period_label = None
    if period == "this_quarter":
        date_from, date_to = _quarter_bounds(today)
        period_label = f"{date_from.strftime('%b')}–{date_to.strftime('%b %Y')} (current quarter)"
    elif period == "last_quarter":
        date_from, date_to = _last_quarter_bounds(today)
        period_label = f"{date_from.strftime('%b')}–{date_to.strftime('%b %Y')} (last quarter)"
    elif period == "this_month":
        date_from = today.replace(day=1)
        date_to = today
        period_label = today.strftime("%B %Y (current month)")

    if date_from or date_to:
        filtered = []
        for r in records:
            td = r.get("tentative_close_date")
            if td is None:
                continue
            td_date = date.fromisoformat(td)
            if date_from and td_date < date_from:
                continue
            if date_to and td_date > date_to:
                continue
            filtered.append(r)
        records = filtered

    if stage:
        records = [r for r in records if r.get("deal_stage", "") and stage.lower() in r["deal_stage"].lower()]

    # Calculate totals
    total_value = 0.0
    missing_value_count = 0
    sector_breakdown: dict[str, dict] = defaultdict(lambda: {"count": 0, "value": 0.0, "missing_value": 0})
    stage_breakdown: dict[str, dict] = defaultdict(lambda: {"count": 0, "value": 0.0})

    for r in records:
        s = r.get("sector") or "Unknown"
        st = r.get("deal_stage") or "Unknown"
        sector_breakdown[s]["count"] += 1
        stage_breakdown[st]["count"] += 1

        val = r.get("deal_value")
        if val is None:
            missing_value_count += 1
            sector_breakdown[s]["missing_value"] += 1
        else:
            if weighted:
                prob_key = (r.get("closure_probability") or "").lower()
                weight = CLOSURE_PROBABILITY_WEIGHTS.get(prob_key, 1.0)
                weighted_val = val * weight
                total_value += weighted_val
                sector_breakdown[s]["value"] += weighted_val
                stage_breakdown[st]["value"] += weighted_val
            else:
                total_value += val
                sector_breakdown[s]["value"] += val
                stage_breakdown[st]["value"] += val

    # At-risk deals: tentative close date has passed
    at_risk = [
        r for r in records
        if r.get("tentative_close_date") and date.fromisoformat(r["tentative_close_date"]) < today
    ]

    dq["records_after_filters"] = len(records)
    dq["records_with_missing_deal_value"] = missing_value_count
    dq["at_risk_deals"] = len(at_risk)

    if missing_value_count > 0:
        dq["note"] = (
            f"{missing_value_count} of {len(records)} deals have no recorded value "
            "and are excluded from the total — the true pipeline value may be higher."
        )

    return {
        "result": {
            "total_pipeline_value": round(total_value, 2),
            "deal_count": len(records),
            "weighted": weighted,
            "period": period_label or "All time",
            "statuses_included": statuses,
            "sector_breakdown": {
                k: {"count": v["count"], "value": round(v["value"], 2),
                    "missing_value_count": v.get("missing_value", 0)}
                for k, v in sorted(sector_breakdown.items(), key=lambda x: -x[1]["value"])
            },
            "stage_breakdown": {
                k: {"count": v["count"], "value": round(v["value"], 2)}
                for k, v in sorted(stage_breakdown.items(), key=lambda x: -x[1]["value"])
            },
            "at_risk_deals_count": len(at_risk),
            "at_risk_deals": [
                {"deal_name": r["deal_name"], "tentative_close": r["tentative_close_date"],
                 "sector": r["sector"], "value": r["deal_value"]}
                for r in at_risk[:10]
            ],
            "weighted_pipeline_note": (
                "Weighted pipeline uses assumed probability mapping: High=75%, Medium=50%, Low=25% "
                "(documented assumption — actual probabilities are categorical, not numeric in source data)."
                if weighted else None
            ),
        },
        "data_quality": dq,
        "_meta": result.get("_meta", {}),
    }


def calculate_revenue(
    basis: str = "billed",    # "deal_value" | "billed" | "collected"
    sector: Optional[str] = None,
    period: Optional[str] = None,
) -> dict:
    """
    Calculate revenue based on an explicit basis to force disambiguation.
    - "deal_value": Won deals from Deals board (Masked Deal value).
    - "billed": Billed Value Incl GST from Work Orders board.
    - "collected": Collected Amount Incl GST from Work Orders board.
    The LLM must specify basis — never guesses.
    """
    if basis not in ("deal_value", "billed", "collected"):
        return {"error": f"Invalid revenue basis '{basis}'. Must be one of: deal_value, billed, collected."}

    today = _today()
    date_from, date_to = None, None
    period_label = "All time"
    if period == "this_quarter":
        date_from, date_to = _quarter_bounds(today)
        period_label = f"{date_from.strftime('%b')}–{date_to.strftime('%b %Y')} (current quarter)"
    elif period == "last_quarter":
        date_from, date_to = _last_quarter_bounds(today)
        period_label = f"{date_from.strftime('%b')}–{date_to.strftime('%b %Y')} (last quarter)"
    elif period == "this_month":
        date_from = today.replace(day=1)
        date_to = today
        period_label = today.strftime("%B %Y")

    if basis == "deal_value":
        result = get_deals(status_filter=["Won"], sector_filter=sector)
        if "error" in result:
            return {"error": result["error"]}
        records = result["records"]
        if date_from or date_to:
            records = [
                r for r in records
                if r.get("close_date") and (
                    (not date_from or date.fromisoformat(r["close_date"]) >= date_from) and
                    (not date_to or date.fromisoformat(r["close_date"]) <= date_to)
                )
            ]
        total = sum(r["deal_value"] for r in records if r["deal_value"] is not None)
        missing = sum(1 for r in records if r["deal_value"] is None)
        sector_breakdown = defaultdict(lambda: {"count": 0, "value": 0.0})
        for r in records:
            s = r.get("sector") or "Unknown"
            sector_breakdown[s]["count"] += 1
            if r["deal_value"] is not None:
                sector_breakdown[s]["value"] += r["deal_value"]
        dq = result["data_quality"]
        dq["records_with_missing_deal_value"] = missing
        dq["records_after_filters"] = len(records)
        if missing:
            dq["note"] = f"{missing} Won deals have no deal value and are excluded."
    else:
        result = get_work_orders(sector_filter=sector)
        if "error" in result:
            return {"error": result["error"]}
        records = result["records"]
        field = "billed_incl_gst" if basis == "billed" else "collected"
        total = sum(r[field] for r in records if r.get(field) is not None)
        missing = sum(1 for r in records if r.get(field) is None)
        sector_breakdown = defaultdict(lambda: {"count": 0, "value": 0.0})
        for r in records:
            s = r.get("sector") or "Unknown"
            sector_breakdown[s]["count"] += 1
            if r.get(field) is not None:
                sector_breakdown[s]["value"] += r[field]
        dq = result["data_quality"]
        dq["records_with_missing_value"] = missing
        dq["records_after_filters"] = len(records)

    return {
        "result": {
            "total": round(total, 2),
            "basis": basis,
            "period": period_label,
            "record_count": len(records),
            "sector_breakdown": {
                k: {"count": v["count"], "value": round(v["value"], 2)}
                for k, v in sorted(sector_breakdown.items(), key=lambda x: -x[1]["value"])
            },
            "basis_explanation": {
                "deal_value": "Sum of Masked Deal value for Won deals on the Deals board.",
                "billed": "Sum of Billed Value (Incl GST) on the Work Orders board.",
                "collected": "Sum of Collected Amount (Incl GST) on the Work Orders board.",
            }[basis],
        },
        "data_quality": dq,
        "_meta": result.get("_meta", {}),
    }


def calculate_operational_metrics(
    status: Optional[str] = None,
    sector: Optional[str] = None,
) -> dict:
    """
    Operational metrics for Work Orders.
    Returns counts and values by execution status, backlog breakdown.
    Note: 'Executed until current month' is ACTIVE (recurring), not Completed.
    """
    result = get_work_orders(sector_filter=sector)
    if "error" in result:
        return {"error": result["error"]}

    records = result["records"]
    dq = result["data_quality"]

    status_counts: dict[str, dict] = defaultdict(lambda: {"count": 0, "billed_value": 0.0, "total_value": 0.0})

    for r in records:
        es = r.get("execution_status") or "Unknown"
        if status and es.lower() != status.lower():
            continue
        status_counts[es]["count"] += 1
        if r.get("billed_incl_gst") is not None:
            status_counts[es]["billed_value"] += r["billed_incl_gst"]
        if r.get("amount_incl_gst") is not None:
            status_counts[es]["total_value"] += r["amount_incl_gst"]

    active_statuses = ACTIVE_EXECUTION_STATUSES
    active_count = sum(v["count"] for k, v in status_counts.items() if k in active_statuses)
    completed_count = status_counts.get("Completed", {}).get("count", 0)
    backlog_count = sum(
        v["count"] for k, v in status_counts.items()
        if k in {"Not Started", "Ongoing", "Executed until current month", "Partial Completed"}
    )

    total_billed = sum(r.get("billed_incl_gst") or 0 for r in records)
    total_receivable = sum(r.get("receivable") or 0 for r in records)
    total_to_bill = sum(r.get("to_bill_incl") or 0 for r in records)
    total_collected = sum(r.get("collected") or 0 for r in records)

    billing_status_dist = defaultdict(int)
    for r in records:
        bs = r.get("billing_status") or "Unknown"
        billing_status_dist[bs] += 1

    return {
        "result": {
            "total_work_orders": len(records),
            "active_work_orders": active_count,
            "completed_work_orders": completed_count,
            "backlog_count": backlog_count,
            "status_breakdown": {
                k: {"count": v["count"], "billed_value": round(v["billed_value"], 2),
                    "total_order_value": round(v["total_value"], 2)}
                for k, v in sorted(status_counts.items(), key=lambda x: -x[1]["count"])
            },
            "financials": {
                "total_billed_incl_gst": round(total_billed, 2),
                "total_receivable": round(total_receivable, 2),
                "total_still_to_bill": round(total_to_bill, 2),
                "total_collected": round(total_collected, 2),
            },
            "billing_status_distribution": dict(billing_status_dist),
            "note": (
                "'Executed until current month' (12 WOs) are recurring contracts "
                "counted as ACTIVE, not Completed."
            ),
        },
        "data_quality": dq,
        "_meta": result.get("_meta", {}),
    }


def calculate_sector_performance(sector: Optional[str] = None) -> dict:
    """
    Side-by-side Deals pipeline vs Work Orders execution for each sector.
    Joins on the shared sector taxonomy (same values on both boards).
    """
    deals_result = get_deals(sector_filter=sector)
    wo_result = get_work_orders(sector_filter=sector)

    if "error" in deals_result:
        return {"error": deals_result["error"]}
    if "error" in wo_result:
        return {"error": wo_result["error"]}

    deals = deals_result["records"]
    wos = wo_result["records"]

    sectors_seen: set[str] = set()
    for r in deals:
        if r.get("sector"):
            sectors_seen.add(r["sector"])
    for r in wos:
        if r.get("sector"):
            sectors_seen.add(r["sector"])

    performance: dict[str, dict] = {}

    for sec in sorted(sectors_seen):
        sec_deals = [r for r in deals if r.get("sector") == sec]
        sec_wos = [r for r in wos if r.get("sector") == sec]

        # Deals stats
        open_deals = [r for r in sec_deals if r.get("deal_status") in ("Open", "On Hold")]
        won_deals = [r for r in sec_deals if r.get("deal_status") == "Won"]
        dead_deals = [r for r in sec_deals if r.get("deal_status") == "Dead"]
        total_deals = len(sec_deals)
        win_rate = round(len(won_deals) / total_deals * 100, 1) if total_deals > 0 else None
        pipeline_val = sum(r["deal_value"] for r in open_deals if r["deal_value"] is not None)
        pipeline_missing = sum(1 for r in open_deals if r["deal_value"] is None)

        # WO stats
        active_wos = [r for r in sec_wos if r.get("execution_status") in ACTIVE_EXECUTION_STATUSES]
        completed_wos = [r for r in sec_wos if r.get("execution_status") == "Completed"]
        billed_val = sum(r.get("billed_incl_gst") or 0 for r in sec_wos)

        performance[sec] = {
            "deals": {
                "total": total_deals,
                "open": len(open_deals),
                "won": len(won_deals),
                "dead": len(dead_deals),
                "win_rate_pct": win_rate,
                "open_pipeline_value": round(pipeline_val, 2),
                "pipeline_missing_value_count": pipeline_missing,
            },
            "work_orders": {
                "total": len(sec_wos),
                "active": len(active_wos),
                "completed": len(completed_wos),
                "billed_value_incl_gst": round(billed_val, 2),
            },
            "pipeline_vs_execution": (
                "Strong pipeline, limited execution" if len(open_deals) > 5 and len(sec_wos) < 5
                else "Active execution" if len(active_wos) >= 3
                else "Normal"
            ),
        }

    # Sort by open pipeline value descending
    sorted_perf = dict(
        sorted(performance.items(), key=lambda x: -x[1]["deals"]["open_pipeline_value"])
    )

    deals_only_sectors = [
        sec for sec in performance
        if performance[sec]["work_orders"]["total"] == 0 and performance[sec]["deals"]["open"] > 0
    ]

    return {
        "result": {
            "sectors_analyzed": list(sorted_perf.keys()),
            "sector_performance": sorted_perf,
            "sectors_with_pipeline_but_no_work_orders": deals_only_sectors,
            "note": (
                "Cross-board join is at sector level (reliable). "
                "Customer-level join is not supported — different client coding schemes. "
                "See Decision Log for details."
            ),
        },
        "data_quality": {
            "deals_records": len(deals),
            "work_orders_records": len(wos),
        },
        "_meta": {
            "deals_meta": deals_result.get("_meta", {}),
            "wo_meta": wo_result.get("_meta", {}),
        },
    }
