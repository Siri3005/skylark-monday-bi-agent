"""
Data normalization module.
Every function returns (cleaned_value, was_valid, original_raw_value).
Raw values are ALWAYS preserved alongside cleaned ones — never discarded.

Rules enforced here:
- None/null and 0 are ALWAYS distinct — missing ≠ zero.
- Dates are parsed from ISO strings (Monday.com raw JSON value); never from
  locale-formatted text fields.
- Missing dates are NEVER substituted with today's date or any default.
- Numeric values that fail to parse are excluded and counted, never treated as 0.
- BIlled → Billed typo fix is applied here (also applied at CSV-import time,
  but defensive re-application is cheap).
"""
from __future__ import annotations
import re
import json
import logging
from datetime import date, datetime
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Type alias ─────────────────────────────────────────────────────────────────
NormalizeResult = Tuple[Any, bool, Any]   # (cleaned, was_valid, raw)


# ── Dates ──────────────────────────────────────────────────────────────────────

def normalize_date(raw_value: Any) -> NormalizeResult:
    """
    Parse a date from Monday.com column raw JSON value.
    Monday.com encodes dates as: {"date": "YYYY-MM-DD", "time": null} or
    plain ISO string "YYYY-MM-DD". Returns (date | None, bool, raw).
    Never substitutes a missing date with today's date.
    """
    if raw_value is None or raw_value == "" or (isinstance(raw_value, float)):
        return (None, False, raw_value)

    # Monday.com raw value JSON: {"date": "2024-08-15", "time": null}
    if isinstance(raw_value, str):
        raw_str = raw_value.strip()
        if raw_str == "" or raw_str == "null":
            return (None, False, raw_value)
        # Try parsing as JSON object first
        try:
            parsed = json.loads(raw_str)
            if isinstance(parsed, dict) and "date" in parsed and parsed["date"]:
                date_str = parsed["date"]
                return _parse_iso_date(date_str, raw_value)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try direct ISO parse
        return _parse_iso_date(raw_str, raw_value)

    if isinstance(raw_value, (date, datetime)):
        d = raw_value.date() if isinstance(raw_value, datetime) else raw_value
        return (d, True, raw_value)

    return (None, False, raw_value)


def _parse_iso_date(s: str, raw: Any) -> NormalizeResult:
    """Parse YYYY-MM-DD string to date. Returns (None, False, raw) on failure."""
    try:
        # Handle YYYY-MM-DDTHH:MM:SS too
        d = datetime.fromisoformat(s.split("T")[0]).date()
        return (d, True, raw)
    except (ValueError, AttributeError):
        logger.debug(f"Could not parse date: {repr(s)}")
        return (None, False, raw)


# ── Text / Category ────────────────────────────────────────────────────────────

# Billing Status typo fix
_BILLING_STATUS_FIXES = {
    "billed": "Billed",   # covers "BIlled" after lowercasing
}

# Invoice Status canonical mapping
_INVOICE_STATUS_MAP = {
    "billed- visit 3": "Partially Billed (per-visit)",
    "billed- visit 7": "Partially Billed (per-visit)",
}


def normalize_text(raw_value: Any) -> NormalizeResult:
    """
    Clean a text value: strip whitespace, return None for empty/null.
    Preserves original casing for display; canonical form is lowercase+strip
    and is stored internally for comparisons only.
    """
    if raw_value is None or (isinstance(raw_value, float)):
        return (None, False, raw_value)
    s = str(raw_value).strip()
    if s == "" or s.lower() == "null":
        return (None, False, raw_value)
    return (s, True, raw_value)


def normalize_billing_status(raw_value: Any) -> NormalizeResult:
    """Fix the BIlled typo in Billing Status."""
    cleaned, valid, raw = normalize_text(raw_value)
    if not valid or cleaned is None:
        return (None, False, raw_value)
    key = cleaned.lower()
    if key == "billed":
        return ("Billed", True, raw_value)
    return (cleaned, True, raw_value)


def normalize_invoice_status(raw_value: Any) -> NormalizeResult:
    """Map 'Billed- Visit N' patterns to canonical bucket."""
    cleaned, valid, raw = normalize_text(raw_value)
    if not valid or cleaned is None:
        return (None, False, raw_value)
    key = cleaned.lower()
    canonical = _INVOICE_STATUS_MAP.get(key)
    if canonical:
        return (canonical, True, raw_value)
    return (cleaned, True, raw_value)


def normalize_sector(raw_value: Any) -> NormalizeResult:
    """Return sector as-is (no case variants exist in the dataset per §3.1).
    Unrecognized values pass through with a flag."""
    return normalize_text(raw_value)


# ── Numeric ────────────────────────────────────────────────────────────────────

def normalize_numeric(raw_value: Any) -> NormalizeResult:
    """
    Parse a numeric value from Monday.com.
    Returns (float | None, bool, raw). Never converts None to 0.
    Monday.com stores numbers as JSON strings like '"1500000"' or '"1500000.0"'.
    """
    if raw_value is None or (isinstance(raw_value, float) and __import__('math').isnan(raw_value)):
        return (None, False, raw_value)
    if isinstance(raw_value, (int, float)):
        return (float(raw_value), True, raw_value)
    if isinstance(raw_value, str):
        s = raw_value.strip().strip('"')
        if s == "" or s.lower() == "null":
            return (None, False, raw_value)
        # Monday.com numeric raw value is often a JSON string: '{"number": 1500000}'
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict) and "number" in parsed:
                n = parsed["number"]
                return (float(n) if n is not None else None, n is not None, raw_value)
            if isinstance(parsed, (int, float)):
                return (float(parsed), True, raw_value)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try direct float conversion after removing commas
        try:
            return (float(s.replace(",", "")), True, raw_value)
        except ValueError:
            pass
    logger.debug(f"Could not parse numeric value: {repr(raw_value)}")
    return (None, False, raw_value)


def normalize_quantity_with_unit(raw_value: Any) -> Tuple[Optional[float], Optional[str], bool, Any]:
    """
    Parse 'Quantities as per PO' which may contain embedded units like '5360 HA'.
    Returns (numeric_magnitude, unit, was_valid, raw).
    NEVER sums across different units — caller is responsible.
    """
    if raw_value is None or (isinstance(raw_value, float) and __import__('math').isnan(raw_value)):
        return (None, None, False, raw_value)

    s = str(raw_value).strip()
    if s == "" or s.lower() == "null":
        return (None, None, False, raw_value)

    # Try to extract number + optional unit suffix
    pattern = re.compile(r"^([\d,]+(?:\.\d+)?)\s*([A-Za-z]*)$")
    match = pattern.match(s)
    if match:
        num_str, unit = match.group(1), match.group(2).strip().upper() or None
        try:
            magnitude = float(num_str.replace(",", ""))
            return (magnitude, unit, True, raw_value)
        except ValueError:
            pass

    logger.debug(f"Could not parse quantity: {repr(raw_value)}")
    return (None, None, False, raw_value)


# ── Monday.com column value extractor ─────────────────────────────────────────

def extract_column_map(item: dict) -> dict:
    """
    Convert a Monday.com item's column_values list into a flat dict:
      { column_id: {"text": ..., "value": ...} }
    """
    result = {}
    for cv in item.get("column_values", []):
        result[cv["id"]] = {
            "text": cv.get("text"),
            "value": cv.get("value"),
        }
    return result
