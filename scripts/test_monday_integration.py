"""
Monday.com Integration Test
Verifies the full data pipeline: auth → pagination → normalization → structured records.
Run with: python scripts/test_monday_integration.py
"""
import sys
import os
import time
from collections import Counter
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

PASS = "PASS"
FAIL = "FAIL"


def section(title):
    print()
    print(f"[{title}]")


def check(label, condition, extra=""):
    status = PASS if condition else FAIL
    print(f"  {status}  {label}" + (f" — {extra}" if extra else ""))
    return condition


def main():
    print("=" * 64)
    print("SKYLARK BI AGENT — MONDAY.COM INTEGRATION TEST")
    print("=" * 64)

    all_passed = True

    # ── 1. Environment config ──────────────────────────────────────
    section("1  Environment / Config")
    from monday.schema import DEALS_BOARD_ID, WORK_ORDERS_BOARD_ID
    all_passed &= check("MONDAY_API_TOKEN set", bool(os.environ.get("MONDAY_API_TOKEN")))
    all_passed &= check("DEALS_BOARD_ID set", bool(DEALS_BOARD_ID), DEALS_BOARD_ID)
    all_passed &= check("WORK_ORDERS_BOARD_ID set", bool(WORK_ORDERS_BOARD_ID), WORK_ORDERS_BOARD_ID)
    all_passed &= check("No token in DEALS_BOARD_ID value",
                        os.environ.get("MONDAY_API_TOKEN", "")[:10] not in DEALS_BOARD_ID)

    # ── 2. Auth + board item counts ───────────────────────────────
    section("2  Auth + Board Item Counts")
    from monday.client import get_board_items_count, MondayError
    try:
        d_count = get_board_items_count(DEALS_BOARD_ID)
        w_count = get_board_items_count(WORK_ORDERS_BOARD_ID)
        all_passed &= check("Deals board reachable", d_count > 0, f"{d_count} items")
        all_passed &= check("Work Orders board reachable", w_count > 0, f"{w_count} items")
        all_passed &= check("Deals count matches expected 344", d_count == 344, f"got {d_count}")
        all_passed &= check("Work Orders count matches expected 176", w_count == 176, f"got {w_count}")
    except MondayError as e:
        print(f"  FAIL  Monday.com error: {e}")
        all_passed = False
        sys.exit(1)

    # ── 3. Column schema discovery ────────────────────────────────
    section("3  Column Schema Discovery")
    from tools.retrieval import get_board_column_schema
    d_schema = get_board_column_schema(DEALS_BOARD_ID)
    w_schema = get_board_column_schema(WORK_ORDERS_BOARD_ID)

    expected_deal_cols = [
        "Owner Code", "Client Code", "Deal State", "Close Date",
        "Closure Probability", "Masked Deal Value", "Tentative Close Date",
        "Deal Stage", "Product Deal", "Sector", "Created Date",
    ]
    expected_wo_cols = [
        "Execution Status", "Sector Name", "BD/KAM Personnel Code",
        "Billed Value Incl GST",
        "Collected Amount Incl GST",
        "Amount Receivable", "Invoice Status", "Billing Status",
    ]

    print(f"  Deals columns detected    : {len(d_schema)}")
    print(f"  Work Orders columns det.  : {len(w_schema)}")
    for col in expected_deal_cols:
        all_passed &= check(f"Deals has column: {col}", col in d_schema)
    for col in expected_wo_cols:
        all_passed &= check(f"Work Orders has column: {col}", col in w_schema)

    # ── 4. Full pagination — Deals ────────────────────────────────
    section("4  Full Pagination — Deals Board")
    from monday.client import get_all_board_items
    t0 = time.time()
    deals_raw = get_all_board_items(DEALS_BOARD_ID)
    elapsed = time.time() - t0
    print(f"  Fetched {len(deals_raw)} items in {elapsed:.1f}s")
    all_passed &= check("Retrieved all Deals items", len(deals_raw) == d_count,
                        f"got {len(deals_raw)}, expected {d_count}")
    if deals_raw:
        sample = deals_raw[0]
        all_passed &= check("Item has 'id'", "id" in sample)
        all_passed &= check("Item has 'name'", "name" in sample and bool(sample["name"]))
        all_passed &= check("Item has column_values", len(sample.get("column_values", [])) > 0,
                            f"{len(sample.get('column_values', []))} columns")

    # ── 5. Full pagination — Work Orders ──────────────────────────
    section("5  Full Pagination — Work Orders Board")
    t0 = time.time()
    wo_raw = get_all_board_items(WORK_ORDERS_BOARD_ID)
    elapsed = time.time() - t0
    print(f"  Fetched {len(wo_raw)} items in {elapsed:.1f}s")
    all_passed &= check("Retrieved all Work Orders items", len(wo_raw) == w_count,
                        f"got {len(wo_raw)}, expected {w_count}")

    # ── 6. get_deals() — normalization ────────────────────────────
    section("6  get_deals() — Normalization + Structured Records")
    from tools.retrieval import get_deals
    result = get_deals()
    if "error" in result:
        print(f"  FAIL  get_deals() error: {result['error']}")
        all_passed = False
    else:
        records = result["records"]
        dq = result["data_quality"]
        print(f"  Records returned          : {len(records)}")
        print(f"  Missing deal value        : {dq['records_with_missing_deal_value']}")
        print(f"  Live query timestamp      : {result['_meta']['timestamp']}")

        all_passed &= check("get_deals() returns records", len(records) > 0)
        all_passed &= check("Record count matches board count", len(records) == d_count,
                            f"got {len(records)}, expected {d_count}")
        all_passed &= check("data_quality block present", "records_retrieved_from_monday" in dq)
        all_passed &= check("_meta has timestamp", "timestamp" in result.get("_meta", {}))

        # Field checks on first record
        if records:
            r = records[0]
            all_passed &= check("Record has deal_name", "deal_name" in r)
            all_passed &= check("Record has deal_status", "deal_status" in r)
            all_passed &= check("Record has sector field", "sector" in r)
            all_passed &= check("Record has deal_value field", "deal_value" in r)
            all_passed &= check("Record has deal_value_missing flag", "deal_value_missing" in r)
            all_passed &= check("Record has tentative_close_date", "tentative_close_date" in r)
            print(f"  Sample deal_name          : {r['deal_name']}")
            print(f"  Sample deal_status        : {r['deal_status']}")
            print(f"  Sample sector             : {r['sector']}")
            print(f"  Sample deal_value         : {r['deal_value']}")

        # Null handling: deal_value can be None (not 0)
        null_vals = [r for r in records if r["deal_value"] is None]
        nonzero_vals = [r for r in records if r["deal_value"] is not None and r["deal_value"] > 0]
        all_passed &= check("None deal_value is None (not 0)",
                            all(r["deal_value"] is None for r in null_vals))
        all_passed &= check("Non-null deal_value is a float",
                            all(isinstance(r["deal_value"], float) for r in nonzero_vals[:5]))

        # Status distribution
        status_dist = Counter(r["deal_status"] for r in records)
        print(f"  Deal status distribution  : {dict(status_dist)}")
        all_passed &= check("Won deals present", status_dist.get("Won", 0) > 0,
                            f"{status_dist.get('Won', 0)} Won")
        all_passed &= check("Open deals present", status_dist.get("Open", 0) > 0,
                            f"{status_dist.get('Open', 0)} Open")

        # Sector distribution
        sector_dist = Counter(r["sector"] or "null" for r in records)
        print(f"  Top 4 sectors             : {dict(sector_dist.most_common(4))}")
        all_passed &= check("Renewables sector present", "Renewables" in sector_dist)
        all_passed &= check("Mining sector present", "Mining" in sector_dist)

    # ── 7. get_work_orders() — normalization ──────────────────────
    section("7  get_work_orders() — Normalization + Structured Records")
    from tools.retrieval import get_work_orders
    result_wo = get_work_orders()
    if "error" in result_wo:
        print(f"  FAIL  get_work_orders() error: {result_wo['error']}")
        all_passed = False
    else:
        records_wo = result_wo["records"]
        dq_wo = result_wo["data_quality"]
        print(f"  Records returned          : {len(records_wo)}")
        print(f"  Live query timestamp      : {result_wo['_meta']['timestamp']}")

        all_passed &= check("get_work_orders() returns records", len(records_wo) > 0)
        all_passed &= check("Record count matches board count", len(records_wo) == w_count,
                            f"got {len(records_wo)}, expected {w_count}")

        if records_wo:
            w = records_wo[0]
            all_passed &= check("WO record has execution_status", "execution_status" in w)
            all_passed &= check("WO record has sector", "sector" in w)
            all_passed &= check("WO record has billed_incl_gst", "billed_incl_gst" in w)
            all_passed &= check("WO record has bd_personnel_code", "bd_personnel_code" in w)
            all_passed &= check("WO record has billing_status", "billing_status" in w)
            print(f"  Sample deal_name          : {w['deal_name']}")
            print(f"  Sample exec_status        : {w['execution_status']}")
            print(f"  Sample sector             : {w['sector']}")
            print(f"  Sample billed_incl_gst    : {w['billed_incl_gst']}")

        exec_dist = Counter(r["execution_status"] or "null" for r in records_wo)
        print(f"  Execution status dist     : {dict(exec_dist)}")
        all_passed &= check("Completed WOs present", exec_dist.get("Completed", 0) > 0)
        all_passed &= check("Ongoing WOs present", exec_dist.get("Ongoing", 0) > 0)

        # Billing status typo fix verified
        billing_dist = Counter(r["billing_status"] or "null" for r in records_wo)
        all_passed &= check("No 'BIlled' typo in billing_status", "BIlled" not in billing_dist,
                            f"dist: {dict(billing_dist)}")

        # Invoice status normalization verified
        invoice_dist = Counter(r["invoice_status"] or "null" for r in records_wo)
        billed_visit = sum(1 for k in invoice_dist if k and "Visit" in k and "per-visit" not in k)
        all_passed &= check("No raw 'Billed- Visit N' in invoice_status", billed_visit == 0,
                            f"dist: {dict(invoice_dist)}")

    # ── 8. Sector filter test ─────────────────────────────────────
    section("8  Filter Test — Sector + Status Filters")
    mining_deals = get_deals(sector_filter="Mining", status_filter=["Open"])
    if "error" not in mining_deals:
        all_passed &= check("Sector filter works (Mining Open deals)",
                            len(mining_deals["records"]) > 0,
                            f"{len(mining_deals['records'])} records")
        all_passed &= check("All filtered records are Open Mining",
                            all(r["sector"] == "Mining" and r["deal_status"] == "Open"
                                for r in mining_deals["records"]))

    # ── 9. Security — token not in output ─────────────────────────
    section("9  Security — API Token Not Exposed in Outputs")
    token = os.environ.get("MONDAY_API_TOKEN", "")
    sample_output = str(records[:3] if "records" in dir() else "") + \
                    str(records_wo[:3] if "records_wo" in dir() else "")
    token_prefix = token[:15] if len(token) >= 15 else token
    all_passed &= check("API token not in record output", token_prefix not in sample_output)

    # ── Summary ────────────────────────────────────────────────────
    print()
    print("=" * 64)
    if all_passed:
        print("ALL TESTS PASSED — Monday.com data pipeline is working correctly")
    else:
        print("SOME TESTS FAILED — see FAIL lines above")
    print("=" * 64)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
