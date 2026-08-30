"""
Data quality checking tool.
Reports null counts, known data issues, board statistics.
"""
from __future__ import annotations
import logging
from collections import defaultdict
from typing import Optional

from tools.retrieval import get_deals, get_work_orders

logger = logging.getLogger(__name__)


def check_data_quality(board: Optional[str] = None) -> dict:
    """
    Return data quality report for one or both boards.
    board: "deals" | "work_orders" | None (both)
    """
    results = {}

    if board in (None, "deals"):
        deals_result = get_deals()
        if "error" in deals_result:
            results["deals"] = {"error": deals_result["error"]}
        else:
            results["deals"] = _analyze_deals(deals_result["records"])

    if board in (None, "work_orders"):
        wo_result = get_work_orders()
        if "error" in wo_result:
            results["work_orders"] = {"error": wo_result["error"]}
        else:
            results["work_orders"] = _analyze_work_orders(wo_result["records"])

    return {"result": results}


def _analyze_deals(records: list) -> dict:
    total = len(records)
    null_counts = defaultdict(int)
    fields = ["owner_code", "client_code", "deal_status", "close_date",
              "closure_probability", "deal_value", "tentative_close_date",
              "deal_stage", "product_deal", "sector", "created_date"]

    for r in records:
        for f in fields:
            if r.get(f) is None:
                null_counts[f] += 1

    status_dist = defaultdict(int)
    sector_dist = defaultdict(int)
    stage_dist = defaultdict(int)
    for r in records:
        status_dist[r.get("deal_status") or "null"] += 1
        sector_dist[r.get("sector") or "null"] += 1
        if r.get("deal_stage"):
            stage_dist[r["deal_stage"]] += 1

    duplicates_note = (
        "12 duplicate rows were identified in the source Excel during pre-import cleaning. "
        "They were kept (not deleted) to avoid silently removing real business records without confirmation."
    )

    return {
        "total_records": total,
        "null_counts": {k: v for k, v in sorted(null_counts.items(), key=lambda x: -x[1])},
        "null_pct": {k: round(v / total * 100, 1) for k, v in null_counts.items()},
        "deal_status_distribution": dict(status_dist),
        "sector_distribution": dict(sorted(sector_dist.items(), key=lambda x: -x[1])),
        "deal_stage_count": len(stage_dist),
        "notes": [
            "2 junk rows (embedded column headers) were removed before import.",
            duplicates_note,
            f"'Masked Deal value' is null for {null_counts['deal_value']} of {total} records "
            f"({round(null_counts['deal_value']/total*100,1)}%) — pipeline totals are materially understated.",
            f"'Close Date (A)' is null for {null_counts['close_date']} of {total} records — "
            "actual close date is only known for a small fraction of deals.",
        ],
    }


def _analyze_work_orders(records: list) -> dict:
    total = len(records)
    null_counts = defaultdict(int)
    fields = [
        "execution_status", "sector", "bd_personnel_code", "billed_incl_gst",
        "collected", "receivable", "invoice_status", "billing_status",
        "qty_ops", "qty_po_magnitude", "qty_billed",
    ]
    for r in records:
        for f in fields:
            if r.get(f) is None:
                null_counts[f] += 1

    exec_dist = defaultdict(int)
    sector_dist = defaultdict(int)
    billing_dist = defaultdict(int)
    for r in records:
        exec_dist[r.get("execution_status") or "null"] += 1
        sector_dist[r.get("sector") or "null"] += 1
        billing_dist[r.get("billing_status") or "null"] += 1

    return {
        "total_records": total,
        "null_counts": {k: v for k, v in sorted(null_counts.items(), key=lambda x: -x[1])},
        "null_pct": {k: round(v / total * 100, 1) for k, v in null_counts.items()},
        "execution_status_distribution": dict(exec_dist),
        "sector_distribution": dict(sorted(sector_dist.items(), key=lambda x: -x[1])),
        "billing_status_distribution": dict(billing_dist),
        "notes": [
            "4 columns are 100% empty and were not imported: "
            "'Expected Billing Month', 'Actual Collection Month', 'Collection status', 'Collection Date'.",
            "Invoice Status 'Billed- Visit N' values normalized to 'Partially Billed (per-visit)'.",
            "Billing Status 'BIlled' typo corrected to 'Billed'.",
            "'Quantities as per PO' contains embedded units (e.g. '5360 HA') — "
            "not summed across sectors due to unit inconsistency.",
            "'Executed until current month' (recurring contracts) counted as ACTIVE, not Completed.",
        ],
    }
