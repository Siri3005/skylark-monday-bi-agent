"""
Deterministic response generator.
Converts structured BI tool results into conversational founder-level text.
No external LLM. All text is generated from templates + live data.

Every response includes:
1. Direct answer
2. Key metric(s)
3. Supporting breakdown (table where useful)
4. Business interpretation
5. Data-quality caveat (when relevant)
6. Source provenance
"""
from __future__ import annotations
import logging
from datetime import date, datetime
from typing import Any, Optional

from agent.parser import ParsedQuery

logger = logging.getLogger(__name__)

INR = "₹"


def _fmt_inr(value: Optional[float], crore_threshold: float = 1_00_00_000) -> str:
    """Format a value in Indian Rupees with Cr/L suffix."""
    if value is None:
        return "N/A"
    if value >= crore_threshold:
        return f"{INR}{value/1_00_00_000:.1f} Cr"
    elif value >= 1_00_000:
        return f"{INR}{value/1_00_000:.1f} L"
    else:
        return f"{INR}{value:,.0f}"


def _fmt_count(n: int, singular: str, plural: str = "") -> str:
    if not plural:
        plural = singular + "s"
    return f"{n} {singular if n == 1 else plural}"


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{round(part / total * 100)}%"


def _sector_table(breakdown: dict, value_key: str = "value", count_key: str = "count") -> str:
    """Generate a markdown table from a sector breakdown dict."""
    if not breakdown:
        return ""
    rows = []
    total_val = sum(v.get(value_key, 0) for v in breakdown.values())
    rows.append("| Sector | Deals | Pipeline |")
    rows.append("|--------|------:|---------:|")
    for sector, data in list(breakdown.items())[:8]:
        val = data.get(value_key, 0)
        cnt = data.get(count_key, 0)
        rows.append(f"| {sector} | {cnt} | {_fmt_inr(val)} |")
    return "\n".join(rows)


def _wo_status_table(status_breakdown: dict) -> str:
    if not status_breakdown:
        return ""
    rows = ["| Status | Count |", "|--------|------:|"]
    for status, data in status_breakdown.items():
        rows.append(f"| {status} | {data.get('count', 0)} |")
    return "\n".join(rows)


def generate_response(q: ParsedQuery, plan: dict, data: dict) -> str:
    """
    Generate a conversational response from tool results.
    Returns markdown-formatted text.
    """
    if "error" in data and data["error"]:
        return (
            f"I ran into a problem retrieving that data:\n\n"
            f"> {data['error']}\n\n"
            "Please check that Monday.com is accessible and try again."
        )

    # Dispatch to intent-specific formatter
    intent = q.intent

    if intent == "leadership":
        return _format_leadership(data)
    elif intent == "quality":
        return _format_quality(q, data)
    elif intent == "count":
        return _format_count(q, data)
    elif intent == "pipeline":
        return _format_pipeline(q, data)
    elif intent in ("upcoming_closures", "at_risk"):
        return _format_at_risk(q, data)
    elif intent in ("revenue", "billing", "collections"):
        return _format_revenue(q, data)
    elif intent == "receivables":
        if q.groupby == "customer" and "records" in data:
            return _format_receivables_by_customer(q, data)
        return _format_receivables(q, data)
    elif intent == "ops":
        return _format_ops(q, data)
    elif intent == "cross_board":
        return _format_cross_board(q, data)
    elif intent == "summary":
        return _format_summary(q, data)
    else:
        return _format_generic(q, data)


# ── Intent-specific formatters ─────────────────────────────────────────────────

def _format_pipeline(q: ParsedQuery, data: dict) -> str:
    if "error" in data:
        return f"Could not retrieve pipeline data: {data['error']}"

    result = data.get("result", {})
    dq = data.get("data_quality", {})

    total = result.get("total_pipeline_value", 0)
    count = result.get("deal_count", 0)
    period = result.get("period", "All time")
    sector_bd = result.get("sector_breakdown", {})
    stage_bd = result.get("stage_breakdown", {})
    at_risk = result.get("at_risk_deals_count", 0)
    missing = dq.get("records_with_missing_deal_value", 0)
    retrieved = dq.get("records_retrieved_from_monday", 0)

    sector_clause = f" in **{q.sector}**" if q.sector else ""
    period_clause = f" ({period})" if period != "All time" else ""

    lines = []

    # Handle zero result — explain why rather than just showing ₹0
    if count == 0:
        lines.append(f"**No open deals found{sector_clause}{period_clause}.**")
        lines.append("")
        if q.period and q.sector:
            lines.append(
                f"There are no open deals in the **{q.sector}** sector with a tentative close date "
                f"falling in {period}. This could mean:"
            )
            lines.append(f"- All {q.sector} open deals have tentative close dates outside this period")
            lines.append(f"- Or the tentative close dates have not been set for this sector")
            lines.append("")
            lines.append(f"Try asking: *'What's the overall {q.sector} pipeline?'* (without a period filter) to see all open deals.")
        elif q.sector:
            lines.append(f"There are no open deals recorded for the **{q.sector}** sector.")
        elif q.period:
            lines.append(f"No open deals have tentative close dates in {period}.")
        return "\n".join(lines)

    lines.append(f"**Current open pipeline{sector_clause}{period_clause}: {_fmt_inr(total)} across {_fmt_count(count, 'deal')}.**")
    lines.append("")

    # Sector breakdown table (if no specific sector filter)
    if not q.sector and sector_bd:
        lines.append("**Pipeline by Sector:**")
        lines.append("")
        lines.append("| Sector | Deals | Pipeline | Missing Value |")
        lines.append("|--------|------:|---------:|--------------:|")
        for sec, d in list(sector_bd.items())[:8]:
            mv = d.get("missing_value_count", 0)
            mv_str = f"{mv}" if mv > 0 else "—"
            lines.append(f"| {sec} | {d['count']} | {_fmt_inr(d['value'])} | {mv_str} |")
        lines.append("")

    # Stage breakdown (if grouped by stage)
    if q.groupby == "stage" and stage_bd:
        lines.append("**Pipeline by Stage:**")
        lines.append("")
        lines.append("| Stage | Deals | Value |")
        lines.append("|-------|------:|------:|")
        for stage, d in list(stage_bd.items())[:10]:
            lines.append(f"| {stage} | {d['count']} | {_fmt_inr(d['value'])} |")
        lines.append("")

    # Top sector insight
    if sector_bd and not q.sector:
        top_sector = next(iter(sector_bd))
        top_val = sector_bd[top_sector]["value"]
        top_pct = round(top_val / total * 100) if total > 0 else 0
        lines.append(f"**{top_sector}** leads with {_fmt_inr(top_val)}, representing ~{top_pct}% of total pipeline.")
        lines.append("")

    # At-risk
    if at_risk > 0:
        lines.append(f"⚠️ **{at_risk} deal{'s' if at_risk != 1 else ''}** have passed their tentative close date without being marked Won or Dead.")
        lines.append("")

    # Data quality caveat
    if missing > 0:
        lines.append(
            f"> ℹ️ **Data note:** {missing} of {count} deals have no recorded deal value and are excluded "
            f"from the total — the true pipeline may be higher."
        )

    _add_provenance(lines, "Deals board", ["Masked Deal Value", "Deal State", "Sector", "Tentative Close Date"],
                    q.deal_status, q.period, "SUM(Masked Deal Value)")

    return "\n".join(lines)


def _format_at_risk(q: ParsedQuery, data: dict) -> str:
    result = data.get("result", {})
    at_risk_list = result.get("at_risk_deals", [])
    at_risk_count = result.get("at_risk_deals_count", 0)
    count = result.get("deal_count", 0)

    if at_risk_count == 0:
        return f"No open deals have passed their tentative close date — all {count} active deals are within their expected timeline."

    lines = [f"**{at_risk_count} open deal{'s' if at_risk_count != 1 else ''} have passed their expected close date** (out of {count} total open deals)."]
    lines.append("")
    if at_risk_list:
        lines.append("| Deal | Expected Close | Sector | Value |")
        lines.append("|------|---------------|--------|------:|")
        for d in at_risk_list[:10]:
            lines.append(f"| {d['deal_name']} | {d['tentative_close'] or 'N/A'} | {d['sector'] or 'N/A'} | {_fmt_inr(d['value'])} |")
    lines.append("")
    lines.append("These deals should be reviewed — either the close date needs updating, or they may be at risk of going Dead.")
    return "\n".join(lines)


def _format_count(q: ParsedQuery, data: dict) -> str:
    lines = []

    if q.dataset == "both":
        d_result = data.get("deals", {})
        w_result = data.get("work_orders", {})
        d_count = d_result.get("data_quality", {}).get("records_retrieved_from_monday", 0)
        w_count = w_result.get("data_quality", {}).get("records_retrieved_from_monday", 0)
        d_recs = d_result.get("records", [])
        w_recs = w_result.get("records", [])

        from collections import Counter
        d_status = Counter(r.get("deal_status") or "Unknown" for r in d_recs)
        w_status = Counter(r.get("execution_status") or "Unknown" for r in w_recs)

        lines.append(f"**Total: {d_count} deals and {w_count} work orders** are on the boards.")
        lines.append("")
        lines.append(f"**Deals breakdown:** Open: {d_status.get('Open',0)}, Won: {d_status.get('Won',0)}, Dead: {d_status.get('Dead',0)}, On Hold: {d_status.get('On Hold',0)}")
        lines.append("")
        lines.append(f"**Work Orders breakdown:** Completed: {w_status.get('Completed',0)}, Ongoing: {w_status.get('Ongoing',0)}, Not Started: {w_status.get('Not Started',0)}")

    elif q.dataset == "deals":
        d_result = data.get("deals", {})
        count = d_result.get("data_quality", {}).get("records_after_filters", 0)
        sector_clause = f" in **{q.sector}**" if q.sector else ""
        status_clause = f" with status {q.deal_status}" if q.deal_status else ""
        lines.append(f"There are **{count} deals{sector_clause}{status_clause}** on the Deals board.")

    else:
        w_result = data.get("work_orders", {})
        count = w_result.get("data_quality", {}).get("records_after_filters", 0)
        sector_clause = f" in **{q.sector}**" if q.sector else ""
        status_clause = f" with status {q.wo_status!r}" if q.wo_status else ""
        lines.append(f"There are **{count} work orders{sector_clause}{status_clause}** on the Work Orders board.")

    return "\n".join(lines)


def _format_revenue(q: ParsedQuery, data: dict) -> str:
    result = data.get("result", {})
    dq = data.get("data_quality", {})

    if "error" in data:
        return f"Could not retrieve revenue data: {data['error']}"

    total = result.get("total", 0)
    basis = result.get("basis", "billed")
    period = result.get("period", "All time")
    count = result.get("record_count", 0)
    sector_bd = result.get("sector_breakdown", {})
    explanation = result.get("basis_explanation", "")

    basis_label = {
        "billed": "Billed value (incl. GST)",
        "collected": "Collected amount (incl. GST)",
        "deal_value": "Won deal value",
    }.get(basis, basis)

    sector_clause = f" in **{q.sector}**" if q.sector else ""
    period_clause = f" ({period})" if period != "All time" else ""

    lines = [f"**{basis_label}{sector_clause}{period_clause}: {_fmt_inr(total)}** across {_fmt_count(count, 'record')}."]
    lines.append("")
    lines.append(f"*Basis: {explanation}*")
    lines.append("")

    if sector_bd and not q.sector:
        lines.append("**By Sector:**")
        lines.append("")
        lines.append("| Sector | Records | Amount |")
        lines.append("|--------|--------:|-------:|")
        for sec, d in list(sector_bd.items())[:8]:
            lines.append(f"| {sec} | {d['count']} | {_fmt_inr(d['value'])} |")
        lines.append("")
        if sector_bd:
            top = next(iter(sector_bd))
            top_val = sector_bd[top]["value"]
            pct = round(top_val / total * 100) if total > 0 else 0
            lines.append(f"**{top}** is the top contributor at {_fmt_inr(top_val)} (~{pct}% of total).")

    # For collections specifically, add trend limitation note
    if basis == "collected" and q.intent == "collections":
        lines.append("")
        lines.append(
            "> ℹ️ **Trend note:** The data shows a single cumulative total — "
            "no monthly time-series is available in the current board schema, "
            "so a trend over time cannot be calculated. This is the all-time collected figure."
        )

    missing = dq.get("records_with_missing_value", dq.get("records_with_missing_deal_value", 0))
    if missing > 0:
        lines.append(f"\n> ℹ️ **Data note:** {missing} records have no value recorded and are excluded.")

    return "\n".join(lines)


def _format_receivables_by_customer(q: ParsedQuery, data: dict) -> str:
    """Per-customer receivables breakdown from raw WO records."""
    records = data.get("records", [])
    if not records:
        return "No work order records found to calculate customer receivables."

    from collections import defaultdict
    customer_totals: dict[str, dict] = defaultdict(
        lambda: {"receivable": 0.0, "billed": 0.0, "collected": 0.0, "wo_count": 0}
    )
    missing_receivable = 0
    missing_customer = 0

    for r in records:
        customer = r.get("customer_code") or r.get("deal_name") or "Unknown"
        if not r.get("customer_code"):
            missing_customer += 1

        rec_val = r.get("receivable")
        bil_val = r.get("billed_incl_gst")
        col_val = r.get("collected")

        if rec_val is None:
            missing_receivable += 1
        else:
            customer_totals[customer]["receivable"] += rec_val

        if bil_val is not None:
            customer_totals[customer]["billed"] += bil_val
        if col_val is not None:
            customer_totals[customer]["collected"] += col_val
        customer_totals[customer]["wo_count"] += 1

    # Sort by receivable descending
    ranked = sorted(customer_totals.items(), key=lambda x: -x[1]["receivable"])
    total_receivable = sum(v["receivable"] for _, v in ranked)

    lines = [f"**Customers by Outstanding Receivables** (top {min(len(ranked), 15)} of {len(ranked)})"]
    lines.append("")
    lines.append("| Customer | Work Orders | Billed | Collected | Receivable |")
    lines.append("|----------|------------|-------:|----------:|-----------:|")
    for customer, d in ranked[:15]:
        lines.append(
            f"| {customer} | {d['wo_count']} | "
            f"{_fmt_inr(d['billed'])} | {_fmt_inr(d['collected'])} | "
            f"**{_fmt_inr(d['receivable'])}** |"
        )
    lines.append("")

    if ranked:
        top_customer = ranked[0][0]
        top_val = ranked[0][1]["receivable"]
        pct = round(top_val / total_receivable * 100) if total_receivable > 0 else 0
        lines.append(
            f"**{top_customer}** has the highest outstanding receivables at "
            f"{_fmt_inr(top_val)} ({pct}% of total)."
        )
        lines.append(f"Total outstanding across all customers: **{_fmt_inr(total_receivable)}**")

    lines.append("")
    if missing_receivable > 0:
        lines.append(
            f"> ℹ️ **Data note:** {missing_receivable} of {len(records)} work orders have no "
            f"'Amount Receivable' recorded and are excluded from the totals."
        )
    if missing_customer > 0:
        lines.append(
            f"> ℹ️ **Customer note:** {missing_customer} work orders have no customer code — "
            f"grouped by deal name instead. Customer identifiers are masked in source data."
        )

    return "\n".join(lines)


def _format_receivables(q: ParsedQuery, data: dict) -> str:
    result = data.get("result", {})
    if "error" in data:
        return f"Could not retrieve receivables data: {data['error']}"

    fin = result.get("financials", {})
    receivable = fin.get("total_receivable", 0)
    billed = fin.get("total_billed_incl_gst", 0)
    collected = fin.get("total_collected", 0)
    to_bill = fin.get("total_still_to_bill", 0)

    sector_clause = f" in **{q.sector}**" if q.sector else ""

    lines = [f"**Total outstanding receivables{sector_clause}: {_fmt_inr(receivable)}**"]
    lines.append("")
    lines.append(f"- Total billed (incl. GST): **{_fmt_inr(billed)}**")
    lines.append(f"- Collected so far: **{_fmt_inr(collected)}**")
    lines.append(f"- Still to be billed: **{_fmt_inr(to_bill)}**")
    lines.append(f"- Outstanding (receivable): **{_fmt_inr(receivable)}**")
    lines.append("")

    collection_rate = round(collected / billed * 100) if billed > 0 else 0
    lines.append(f"Collection rate: **{collection_rate}%** of billed value has been collected.")
    lines.append("")
    lines.append("Review AR priority accounts for overdue follow-up.")

    dq = data.get("data_quality", {})
    _add_provenance(lines, "Work Orders board",
                    ["Amount Receivable", "Billed Value Incl GST", "Collected Amount Incl GST"],
                    None, None, "SUM")
    return "\n".join(lines)


def _format_ops(q: ParsedQuery, data: dict) -> str:
    result = data.get("result", {})
    if "error" in data:
        return f"Could not retrieve operational data: {data['error']}"

    total = result.get("total_work_orders", 0)
    active = result.get("active_work_orders", 0)
    completed = result.get("completed_work_orders", 0)
    backlog = result.get("backlog_count", 0)
    status_bd = result.get("status_breakdown", {})
    fin = result.get("financials", {})

    sector_clause = f" in **{q.sector}**" if q.sector else ""

    lines = [f"**{total} work orders{sector_clause} total: {active} active, {completed} completed.**"]
    lines.append("")

    if status_bd:
        lines.append("**Execution Status Breakdown:**")
        lines.append("")
        lines.append("| Status | Count | Billed Value |")
        lines.append("|--------|------:|-------------:|")
        for status, d in status_bd.items():
            lines.append(f"| {status} | {d['count']} | {_fmt_inr(d.get('billed_value', 0))} |")
        lines.append("")

    lines.append(f"- **Active backlog** (not yet completed): {backlog} work orders")
    lines.append(f"- Total billed: **{_fmt_inr(fin.get('total_billed_incl_gst', 0))}**")
    lines.append(f"- Collected: **{_fmt_inr(fin.get('total_collected', 0))}**")
    lines.append(f"- Outstanding: **{_fmt_inr(fin.get('total_receivable', 0))}**")
    lines.append("")
    lines.append("> ℹ️ 'Executed until current month' (recurring contracts) are counted as **active**, not completed.")

    return "\n".join(lines)


def _format_cross_board(q: ParsedQuery, data: dict) -> str:
    if "limitation" in data:
        return data["limitation"]

    result = data.get("result", {})
    if "error" in data:
        return f"Could not run cross-board analysis: {data['error']}"

    # Customer level
    if q.metric == "customer_level":
        return (
            "I can't reliably match individual customers across the two boards — "
            "they use different coding systems. I can answer this at the **sector level** instead.\n\n"
            "Try: *'Compare pipeline and execution by sector.'*"
        )

    # Owner conversion
    if q.metric == "owner_conversion":
        oc = result.get("owner_conversion", {})
        if not oc:
            return "No owner/BD conversion data available."
        lines = ["**Pipeline-to-Execution Conversion by BD Owner:**", ""]
        lines.append("| Owner | Open Deals | Won | Win Rate | Open Pipeline | WOs | Billed |")
        lines.append("|-------|----------:|----:|---------:|--------------:|----:|-------:|")
        for owner, d in list(oc.items())[:10]:
            wr = f"{d['deals']['win_rate_pct']}%" if d['deals']['win_rate_pct'] is not None else "N/A"
            lines.append(
                f"| {owner} | {d['deals']['open']} | {d['deals']['won']} | {wr} | "
                f"{_fmt_inr(d['open_pipeline_value'])} | {d['work_orders']['total']} | {_fmt_inr(d['billed_value'])} |"
            )
        lines.append("")
        lines.append("> Join is at owner/BD level (reliable — same masking scheme on both boards).")
        return "\n".join(lines)

    # Sector comparison
    sector_comparison = result.get("sector_comparison", {})
    if not sector_comparison:
        # strong_sales_weak_ops
        weak = result.get("sectors_with_strong_pipeline_but_weak_execution", {})
        full = result.get("full_table", {})
        if not weak or weak == "None identified":
            return "No sectors with strong pipeline but weak execution were identified. Overall balance looks healthy."
        lines = ["**Sectors with strong sales pipeline but limited execution:**", ""]
        for sec, d in weak.items():
            lines.append(f"- **{sec}**: {d['open_deals']} open deals ({_fmt_inr(d['open_pipeline_value'])} pipeline) but only {d['total_work_orders']} work orders")
        lines.append("")
        lines.append("These sectors represent opportunities where sales momentum has not yet translated to operational execution.")
        return "\n".join(lines)

    lines = ["**Pipeline vs Execution by Sector:**", ""]
    lines.append(
        "> **Column guide:** Pipeline = open deal value (Deals board) · "
        "Contract = PO/contract value excl. GST (Work Orders) · "
        "Billed = invoiced incl. GST (Work Orders)"
    )
    lines.append("")
    lines.append("| Sector | Open Deals | Pipeline | WOs | Active | Contract Value | Billed | Signal |")
    lines.append("|--------|----------:|---------:|----:|-------:|---------------:|-------:|--------|")
    for sec, d in sector_comparison.items():
        signal_emoji = {
            "strong_pipeline_weak_execution": "⚡ High pipeline",
            "strong_execution_low_new_pipeline": "🔧 Active ops",
            "healthy_both": "✅ Balanced",
        }.get(d["signal"], "—")
        contract = d.get("contract_value_excl_gst", d.get("billed_value", 0))
        billed = d.get("billed_value_incl_gst", d.get("billed_value", 0))
        lines.append(
            f"| {sec} | {d['open_deals']} | {_fmt_inr(d['open_pipeline_value'])} | "
            f"{d['total_work_orders']} | {d['active_work_orders']} | "
            f"{_fmt_inr(contract)} | {_fmt_inr(billed)} | {signal_emoji} |"
        )
    lines.append("")

    no_wo = result.get("sectors_with_pipeline_no_wo", [])
    if no_wo:
        lines.append(f"⚠️ **{', '.join(no_wo)}** have open pipeline but no corresponding work orders — potential conversion gap.")

    lines.append("")
    lines.append("> Join is at sector level only. Customer-level cross-board matching is not supported (different coding schemes).")
    return "\n".join(lines)


def _format_quality(q: ParsedQuery, data: dict) -> str:
    result = data.get("result", {})
    lines = ["**Data Quality Report**", ""]

    for board, bd_data in result.items():
        if "error" in bd_data:
            lines.append(f"**{board.title()}:** Error — {bd_data['error']}")
            continue
        total = bd_data.get("total_records", 0)
        nulls = bd_data.get("null_counts", {})
        notes = bd_data.get("notes", [])
        lines.append(f"### {board.replace('_', ' ').title()} ({total} records)")
        lines.append("")
        if nulls:
            lines.append("**Missing fields (top):**")
            for field, cnt in list(nulls.items())[:6]:
                pct = bd_data.get("null_pct", {}).get(field, 0)
                lines.append(f"- `{field}`: {cnt} missing ({pct}%)")
            lines.append("")
        if notes:
            lines.append("**Known issues:**")
            for note in notes:
                lines.append(f"- {note}")
            lines.append("")

    return "\n".join(lines)


def _format_leadership(data: dict) -> str:
    pipeline_data = data.get("pipeline", {})
    billed_data = data.get("revenue_billed", {})
    collected_data = data.get("revenue_collected", {})
    ops_data = data.get("operations", {})
    sector_data = data.get("sector_performance", {})

    p = pipeline_data.get("result", {})
    b = billed_data.get("result", {})
    c = collected_data.get("result", {})
    o = ops_data.get("result", {})

    pipeline_total = p.get("total_pipeline_value", 0)
    pipeline_count = p.get("deal_count", 0)
    missing_val = pipeline_data.get("data_quality", {}).get("records_with_missing_deal_value", 0)

    billed_total = b.get("total", 0)
    collected_total = c.get("total", 0)

    total_wo = o.get("total_work_orders", 0)
    active_wo = o.get("active_work_orders", 0)
    completed_wo = o.get("completed_work_orders", 0)
    fin = o.get("financials", {})
    receivable = fin.get("total_receivable", 0)
    to_bill = fin.get("total_still_to_bill", 0)
    at_risk = p.get("at_risk_deals_count", 0)

    # Top sector for pipeline
    sector_bd = p.get("sector_breakdown", {})
    top_sector = next(iter(sector_bd), "N/A") if sector_bd else "N/A"
    top_sector_val = sector_bd.get(top_sector, {}).get("value", 0) if sector_bd else 0

    collection_rate = round(collected_total / billed_total * 100) if billed_total > 0 else 0

    lines = [
        "# Leadership Business Update",
        f"*As of {datetime.now().strftime('%d %b %Y')} — Live data from Monday.com*",
        "",
        "---",
        "",
        "## Pipeline",
        f"- **Open pipeline: {_fmt_inr(pipeline_total)}** across {_fmt_count(pipeline_count, 'deal')}",
        f"- Largest sector: **{top_sector}** at {_fmt_inr(top_sector_val)}",
    ]
    if at_risk > 0:
        lines.append(f"- ⚠️ {at_risk} deals have passed expected close date — review required")
    if missing_val > 0:
        lines.append(f"- ℹ️ {missing_val} deals have no recorded value (pipeline may be understated)")
    lines.append("")
    lines.append("## Billing & Collections")
    lines.append(f"- Total billed (incl. GST): **{_fmt_inr(billed_total)}**")
    lines.append(f"- Collected: **{_fmt_inr(collected_total)}** ({collection_rate}% collection rate)")
    lines.append(f"- Outstanding receivables: **{_fmt_inr(receivable)}**")
    lines.append(f"- Still to be billed: **{_fmt_inr(to_bill)}**")
    lines.append("")
    lines.append("## Operations")
    lines.append(f"- **{total_wo} total work orders**: {active_wo} active, {completed_wo} completed")
    lines.append("")
    lines.append("## Key Takeaways")
    lines.append(f"- Pipeline is concentrated in **{top_sector}** — monitor for sector risk.")
    if collection_rate < 70:
        lines.append(f"- Collection rate is {collection_rate}% — consider escalating AR follow-up.")
    if at_risk > 0:
        lines.append(f"- {at_risk} overdue deals need immediate review or status update.")
    lines.append("")
    lines.append(
        "*This update is generated deterministically from live Monday.com data. "
        "All figures are as recorded — no estimates or projections.*"
    )
    return "\n".join(lines)


def _format_summary(q: ParsedQuery, data: dict) -> str:
    lines = []
    pipeline = data.get("pipeline", {})
    ops = data.get("operations", {})
    p = pipeline.get("result", {})
    o = ops.get("result", {})

    if p:
        lines.append(f"**Pipeline:** {_fmt_inr(p.get('total_pipeline_value', 0))} across {_fmt_count(p.get('deal_count', 0), 'open deal')}")
    if o:
        lines.append(f"**Operations:** {o.get('total_work_orders', 0)} work orders ({o.get('active_work_orders', 0)} active, {o.get('completed_work_orders', 0)} completed)")
        fin = o.get("financials", {})
        lines.append(f"**Financials:** Billed {_fmt_inr(fin.get('total_billed_incl_gst', 0))}, Collected {_fmt_inr(fin.get('total_collected', 0))}, Outstanding {_fmt_inr(fin.get('total_receivable', 0))}")

    lines.append("")
    lines.append("For more detail, try asking about specific areas: pipeline by sector, billing performance, collections, or work order status.")
    return "\n".join(lines)


def _format_generic(q: ParsedQuery, data: dict) -> str:
    """Fallback formatter for unrecognised intents."""
    if "error" in data:
        return f"Sorry, I couldn't answer that: {data['error']}"
    # Show raw result in a readable way
    import json
    result = data.get("result", data)
    return f"Here's what I found:\n\n```\n{json.dumps(result, default=str, indent=2)[:1500]}\n```"


def _add_provenance(lines: list, source: str, fields: list, filters: Any, period: Any, calc: str):
    """Append a collapsible source block."""
    lines.append("")
    lines.append("<details><summary>📊 Source</summary>")
    lines.append("")
    lines.append(f"**Board:** {source}")
    lines.append(f"**Fields:** {', '.join(fields)}")
    if filters:
        lines.append(f"**Filter:** {filters}")
    if period:
        lines.append(f"**Period:** {period}")
    lines.append(f"**Calculation:** {calc}")
    lines.append("")
    lines.append("</details>")
