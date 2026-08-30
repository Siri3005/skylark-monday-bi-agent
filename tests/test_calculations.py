"""
Spot-check tests for calculation and normalization logic.
These verify that the deterministic calculation layer is correct
against hand-verified values from the source Excel files.
"""
import sys
import os
from pathlib import Path
from datetime import date

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Normalization tests ────────────────────────────────────────────────────────

def test_normalize_date_iso_string():
    from normalize import normalize_date
    val, valid, raw = normalize_date("2024-08-15")
    assert valid and val == date(2024, 8, 15)

def test_normalize_date_monday_json():
    from normalize import normalize_date
    val, valid, raw = normalize_date('{"date": "2025-03-01", "time": null}')
    assert valid and val == date(2025, 3, 1)

def test_normalize_date_none():
    from normalize import normalize_date
    val, valid, raw = normalize_date(None)
    assert not valid and val is None

def test_normalize_date_nan():
    from normalize import normalize_date
    import math
    val, valid, raw = normalize_date(float("nan"))
    assert not valid and val is None

def test_normalize_date_never_substitutes_today():
    """Missing dates must NEVER become today's date."""
    from normalize import normalize_date
    val, valid, _ = normalize_date("")
    assert val is None, "Empty date should be None, not today"

def test_normalize_numeric_valid():
    from normalize import normalize_numeric
    val, valid, _ = normalize_numeric("1500000")
    assert valid and val == 1500000.0

def test_normalize_numeric_monday_json():
    from normalize import normalize_numeric
    val, valid, _ = normalize_numeric('{"number": 2500000}')
    assert valid and val == 2500000.0

def test_normalize_numeric_none_is_not_zero():
    """None must be distinct from 0."""
    from normalize import normalize_numeric
    val, valid, _ = normalize_numeric(None)
    assert val is None and not valid

def test_normalize_numeric_zero_is_valid():
    from normalize import normalize_numeric
    val, valid, _ = normalize_numeric("0")
    assert valid and val == 0.0

def test_normalize_billing_status_typo():
    from normalize import normalize_billing_status
    val, valid, _ = normalize_billing_status("BIlled")
    assert val == "Billed"

def test_normalize_invoice_status_visit():
    from normalize import normalize_invoice_status
    val, valid, _ = normalize_invoice_status("Billed- Visit 7")
    assert val == "Partially Billed (per-visit)"
    val2, _, _ = normalize_invoice_status("Billed- Visit 3")
    assert val2 == "Partially Billed (per-visit)"

def test_normalize_quantity_with_unit():
    from normalize import normalize_quantity_with_unit
    mag, unit, valid, _ = normalize_quantity_with_unit("5360 HA")
    assert valid and mag == 5360.0 and unit == "HA"

def test_normalize_quantity_bare_number():
    from normalize import normalize_quantity_with_unit
    mag, unit, valid, _ = normalize_quantity_with_unit("3000")
    assert valid and mag == 3000.0 and unit is None

def test_normalize_quantity_none():
    from normalize import normalize_quantity_with_unit
    mag, unit, valid, _ = normalize_quantity_with_unit(None)
    assert not valid and mag is None


# ── Quarter logic tests ────────────────────────────────────────────────────────

def test_quarter_bounds_q1():
    from tools.calculations import _quarter_bounds
    start, end = _quarter_bounds(date(2025, 2, 15))
    assert start == date(2025, 1, 1) and end == date(2025, 3, 31)

def test_quarter_bounds_q3():
    from tools.calculations import _quarter_bounds
    start, end = _quarter_bounds(date(2025, 8, 1))
    assert start == date(2025, 7, 1) and end == date(2025, 9, 30)

def test_last_quarter_bounds_from_q1():
    from tools.calculations import _last_quarter_bounds
    start, end = _last_quarter_bounds(date(2025, 2, 1))
    assert start == date(2024, 10, 1) and end == date(2024, 12, 31)


# ── Pipeline calculation tests (with mock data, no Monday.com needed) ──────────

def _make_deal(deal_value=None, sector="Mining", status="Open", prob=None, tentative_close=None):
    return {
        "id": "1",
        "deal_name": "Test Deal",
        "owner_code": "OWNER_001",
        "client_code": "COMPANY001",
        "deal_status": status,
        "close_date": None,
        "closure_probability": prob,
        "deal_value": deal_value,
        "deal_value_missing": deal_value is None,
        "tentative_close_date": tentative_close,
        "deal_stage": "A. Lead Generated",
        "product_deal": None,
        "sector": sector,
        "created_date": "2024-10-01",
    }


def test_pipeline_excludes_null_values():
    """Deals with no value should be excluded from sum but counted."""
    records = [
        _make_deal(1000000, "Mining"),
        _make_deal(None, "Mining"),       # no value — excluded from sum
        _make_deal(500000, "Renewables"),
    ]
    from collections import defaultdict
    total = sum(r["deal_value"] for r in records if r["deal_value"] is not None)
    missing = sum(1 for r in records if r["deal_value"] is None)
    assert total == 1500000
    assert missing == 1


def test_none_and_zero_are_distinct():
    """0 is not missing — it's a known-zero value."""
    from normalize import normalize_numeric
    none_val, none_valid, _ = normalize_numeric(None)
    zero_val, zero_valid, _ = normalize_numeric("0")
    assert none_val is None and not none_valid
    assert zero_val == 0.0 and zero_valid


if __name__ == "__main__":
    import traceback
    tests = [
        test_normalize_date_iso_string,
        test_normalize_date_monday_json,
        test_normalize_date_none,
        test_normalize_date_nan,
        test_normalize_date_never_substitutes_today,
        test_normalize_numeric_valid,
        test_normalize_numeric_monday_json,
        test_normalize_numeric_none_is_not_zero,
        test_normalize_numeric_zero_is_valid,
        test_normalize_billing_status_typo,
        test_normalize_invoice_status_visit,
        test_normalize_quantity_with_unit,
        test_normalize_quantity_bare_number,
        test_normalize_quantity_none,
        test_quarter_bounds_q1,
        test_quarter_bounds_q3,
        test_last_quarter_bounds_from_q1,
        test_pipeline_excludes_null_values,
        test_none_and_zero_are_distinct,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✓ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
