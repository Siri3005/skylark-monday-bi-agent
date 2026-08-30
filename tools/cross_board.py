"""
Cross-board analysis tools.
Join is ONLY at sector level and owner/BD level — per verified §3.3 findings.
Customer-level join is explicitly NOT supported (different coding namespaces).
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Optional

from tools.retrieval import get_deals, get_work_orders
from monday.schema import ACTIVE_EXECUTION_STATUSES

logger = logging.getLogger(__name__)


def cross_board_metric(
    question_type: str,
    sector: Optional[str] = None,
) -> dict:
    """
    Cross-board metrics at sector and owner/BD level.

    question_type options:
      - "pipeline_vs_execution": compare deal pipeline vs WO execution by sector
      - "strong_sales_weak_ops": sectors with strong pipeline but low execution
      - "owner_conversion": which BD owner's deals convert to billed WOs
      - "sector_overview": full sector-level comparison table

    Cross-board join is RELIABLE only at sector (same taxonomy) and owner/BD
    (same OWNER_00x masking scheme). Customer-level join is NOT supported.
    """
    if question_type == "customer_level":
        return {
            "result": None,
            "limitation": (
                "Customer-level cross-board analysis is not supported. "
                "The Deals board uses 'COMPANY0xx' client codes and the Work Orders board uses "
                "'WOCOMPANY_0xx' codes — these are different masking namespaces with no verified "
                "mapping between them. Fabricating a join here would be misleading. "
                "I can answer this at the sector level instead — would that help?"
            ),
        }

    deals_result = get_deals(sector_filter=sector)
    wo_result = get_work_orders(sector_filter=sector)

    if "error" in deals_result:
        return {"error": deals_result["error"]}
    if "error" in wo_result:
        return {"error": wo_result["error"]}

    deals = deals_result["records"]
    wos = wo_result["records"]

    if question_type in ("pipeline_vs_execution", "strong_sales_weak_ops", "sector_overview"):
        return _sector_comparison(deals, wos, question_type)
    elif question_type == "owner_conversion":
        return _owner_conversion(deals, wos)
    else:
        return {"error": f"Unknown question_type: '{question_type}'. Valid: pipeline_vs_execution, strong_sales_weak_ops, owner_conversion, sector_overview"}


def _sector_comparison(deals: list, wos: list, question_type: str) -> dict:
    sectors: set[str] = set()
    for r in deals:
        if r.get("sector"):
            sectors.add(r["sector"])
    for r in wos:
        if r.get("sector"):
            sectors.add(r["sector"])

    table = {}
    for sec in sorted(sectors):
        sec_deals = [r for r in deals if r.get("sector") == sec]
        sec_wos = [r for r in wos if r.get("sector") == sec]

        open_deals = [r for r in sec_deals if r.get("deal_status") in ("Open", "On Hold")]
        won_deals = [r for r in sec_deals if r.get("deal_status") == "Won"]
        pipeline_val = sum(r["deal_value"] for r in open_deals if r["deal_value"] is not None)
        billed = sum(r.get("billed_incl_gst") or 0 for r in sec_wos)
        active_wos = sum(1 for r in sec_wos if r.get("execution_status") in ACTIVE_EXECUTION_STATUSES)
        completed_wos = sum(1 for r in sec_wos if r.get("execution_status") == "Completed")

        signal = "neutral"
        if len(open_deals) >= 10 and len(sec_wos) < 5:
            signal = "strong_pipeline_weak_execution"
        elif len(active_wos) >= 5 and len(open_deals) < 5:
            signal = "strong_execution_low_new_pipeline"
        elif len(open_deals) >= 5 and active_wos >= 3:
            signal = "healthy_both"

        table[sec] = {
            "open_deals": len(open_deals),
            "won_deals": len(won_deals),
            "total_deals": len(sec_deals),
            "open_pipeline_value": round(pipeline_val, 2),
            "total_work_orders": len(sec_wos),
            "active_work_orders": active_wos,
            "completed_work_orders": completed_wos,
            "billed_value": round(billed, 2),
            "signal": signal,
        }

    if question_type == "strong_sales_weak_ops":
        filtered = {k: v for k, v in table.items() if v["signal"] == "strong_pipeline_weak_execution"}
        return {
            "result": {
                "sectors_with_strong_pipeline_but_weak_execution": filtered or "None identified",
                "full_table": table,
            },
            "note": (
                "Join is at sector level (reliable). "
                "Customer-level join not supported — see Decision Log."
            ),
        }

    return {
        "result": {
            "sector_comparison": table,
            "sectors_with_pipeline_no_wo": [
                k for k, v in table.items() if v["total_work_orders"] == 0 and v["open_deals"] > 0
            ],
        },
        "note": (
            "Cross-board join is at sector level only. "
            "Sectors appearing only in Deals (DSP, Tender, Manufacturing, Security and Surveillance, Aviation) "
            "have no corresponding Work Orders — this is expected."
        ),
    }


def _owner_conversion(deals: list, wos: list) -> dict:
    """
    Which BD owner has deals that convert to billed work orders?
    Uses Owner code (Deals) ↔ BD/KAM Personnel code (Work Orders) — same OWNER_00x scheme.
    """
    owner_deals: dict[str, dict] = defaultdict(lambda: {"open": 0, "won": 0, "dead": 0, "pipeline": 0.0})
    for r in deals:
        oc = r.get("owner_code") or "Unknown"
        status = r.get("deal_status") or ""
        if status == "Open":
            owner_deals[oc]["open"] += 1
        elif status == "Won":
            owner_deals[oc]["won"] += 1
        elif status == "Dead":
            owner_deals[oc]["dead"] += 1
        if r.get("deal_value") and status in ("Open", "On Hold"):
            owner_deals[oc]["pipeline"] += r["deal_value"]

    owner_wos: dict[str, dict] = defaultdict(lambda: {"total": 0, "active": 0, "billed": 0.0})
    for r in wos:
        bc = r.get("bd_personnel_code") or "Unknown"
        owner_wos[bc]["total"] += 1
        if r.get("execution_status") in ACTIVE_EXECUTION_STATUSES:
            owner_wos[bc]["active"] += 1
        if r.get("billed_incl_gst"):
            owner_wos[bc]["billed"] += r["billed_incl_gst"]

    all_owners = set(owner_deals.keys()) | set(owner_wos.keys())
    result = {}
    for owner in sorted(all_owners):
        d = owner_deals.get(owner, {"open": 0, "won": 0, "dead": 0, "pipeline": 0.0})
        w = owner_wos.get(owner, {"total": 0, "active": 0, "billed": 0.0})
        total_deals = d["open"] + d["won"] + d["dead"]
        win_rate = round(d["won"] / total_deals * 100, 1) if total_deals > 0 else None
        result[owner] = {
            "deals": {"open": d["open"], "won": d["won"], "dead": d["dead"], "win_rate_pct": win_rate},
            "open_pipeline_value": round(d["pipeline"], 2),
            "work_orders": {"total": w["total"], "active": w["active"]},
            "billed_value": round(w["billed"], 2),
        }

    # Sort by billed value desc
    result = dict(sorted(result.items(), key=lambda x: -x[1]["billed_value"]))

    return {
        "result": {
            "owner_conversion": result,
            "note": (
                "Owner code (Deals) ↔ BD/KAM Personnel code (Work Orders) join is reliable — "
                "same OWNER_00x masking scheme confirmed in §3.3."
            ),
        },
    }
