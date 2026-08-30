"""
Tests for the deterministic NLP parser and query planner.
No Monday.com API calls — pure unit tests.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.parser import parse_query


# ── Pipeline ───────────────────────────────────────────────────────────────────

def test_pipeline_basic():
    q = parse_query("What's our pipeline?")
    assert q.intent == "pipeline"
    assert q.dataset == "deals"

def test_pipeline_sector():
    q = parse_query("How's our pipeline looking for mining this quarter?")
    assert q.intent == "pipeline"
    assert q.sector == "Mining"
    assert q.period == "this_quarter"

def test_pipeline_by_sector():
    q = parse_query("Break the pipeline down by sector")
    assert q.intent == "pipeline"
    assert q.groupby == "sector"

def test_pipeline_by_stage():
    q = parse_query("Show pipeline by stage")
    assert q.intent == "pipeline"
    assert q.groupby == "stage"

def test_pipeline_energy_alias():
    q = parse_query("Pipeline for energy sector this quarter")
    assert q.sector == "Renewables"   # "energy" maps to Renewables
    assert q.period == "this_quarter"

def test_upcoming_closures():
    q = parse_query("Which deals are likely to close soon?")
    assert q.intent == "upcoming_closures"
    assert q.dataset == "deals"

def test_at_risk():
    q = parse_query("Show me at-risk deals")
    assert q.intent == "at_risk"
    assert q.dataset == "deals"


# ── Revenue / Billing / Collections ───────────────────────────────────────────

def test_revenue_ambiguous():
    q = parse_query("What's our revenue?")
    assert q.ambiguous is True
    assert q.clarify_on == "revenue_basis"

def test_revenue_billed():
    q = parse_query("Show me billing performance")
    assert q.intent == "billing"
    assert q.dataset == "work_orders"

def test_revenue_collected():
    q = parse_query("How much have we collected?")
    assert q.intent == "collections"
    assert q.dataset == "work_orders"

def test_revenue_collected2():
    q = parse_query("Are collections improving?")
    assert q.intent == "collections"

def test_receivables():
    q = parse_query("How much is outstanding?")
    assert q.intent == "receivables"
    assert q.dataset == "work_orders"

def test_receivables2():
    q = parse_query("Which customers have the highest receivables?")
    assert q.intent == "receivables"

def test_ar():
    q = parse_query("Show me AR")
    assert q.intent == "receivables"


# ── Work Orders / Operations ───────────────────────────────────────────────────

def test_work_orders():
    q = parse_query("How many work orders are currently active?")
    assert q.intent == "count" or q.intent == "ops"
    assert q.dataset == "work_orders"

def test_work_orders_status():
    q = parse_query("Show work orders by execution status")
    assert q.dataset == "work_orders"

def test_work_order_operational():
    q = parse_query("Show me billing and collections performance")
    assert q.dataset == "work_orders"


# ── Count ─────────────────────────────────────────────────────────────────────

def test_count_both():
    q = parse_query("How many deals and work orders do we have?")
    assert q.intent == "count"
    assert q.dataset == "both"

def test_count_deals():
    q = parse_query("How many deals are there?")
    assert q.intent == "count"
    assert q.dataset == "deals"

def test_count_wo():
    q = parse_query("How many work orders are there?")
    assert q.intent == "count"
    assert q.dataset == "work_orders"


# ── Cross-board ───────────────────────────────────────────────────────────────

def test_cross_board_compare():
    q = parse_query("Compare pipeline with executed work")
    assert q.intent == "cross_board"
    assert q.dataset == "both"

def test_cross_board_sector_perf():
    q = parse_query("Which sector is performing best?")
    assert q.intent == "cross_board" or q.intent == "pipeline"

def test_cross_board_strong_weak():
    q = parse_query("Which sectors have strong pipeline but weak execution?")
    assert q.intent == "cross_board"
    assert q.metric == "strong_sales_weak_ops"

def test_cross_board_owner():
    q = parse_query("Which BD owner has the most billed work orders?")
    assert q.intent == "cross_board"
    assert q.metric == "owner_conversion"


# ── Time periods ──────────────────────────────────────────────────────────────

def test_period_this_quarter():
    q = parse_query("What's our pipeline this quarter?")
    assert q.period == "this_quarter"

def test_period_last_quarter():
    q = parse_query("Show me last quarter's performance")
    assert q.period == "last_quarter"

def test_period_this_month():
    q = parse_query("Billing this month")
    assert q.period == "this_month"

def test_period_recent():
    q = parse_query("Recent deals")
    assert q.period == "this_quarter"


# ── Sectors ───────────────────────────────────────────────────────────────────

def test_sector_mining():
    q = parse_query("Mining sector pipeline")
    assert q.sector == "Mining"

def test_sector_railways():
    q = parse_query("railways performance")
    assert q.sector == "Railways"

def test_sector_renewables():
    q = parse_query("renewables work orders")
    assert q.sector == "Renewables"


# ── Data quality ──────────────────────────────────────────────────────────────

def test_data_quality():
    q = parse_query("How clean is our data?")
    assert q.intent == "quality"

def test_data_quality2():
    q = parse_query("Are there missing values?")
    assert q.intent == "quality"


# ── Leadership ────────────────────────────────────────────────────────────────

def test_leadership():
    q = parse_query("Prepare a leadership update")
    assert q.intent == "leadership"

def test_leadership2():
    q = parse_query("Give me an executive summary")
    assert q.intent == "leadership"


# ── Clarification ─────────────────────────────────────────────────────────────

def test_ambiguous_revenue():
    q = parse_query("What's our revenue?")
    assert q.ambiguous is True
    assert q.clarify_message is not None
    assert len(q.clarify_message) > 20


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
