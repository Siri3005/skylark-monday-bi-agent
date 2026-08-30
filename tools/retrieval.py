"""
Retrieval tools: get_deals() and get_work_orders().
These are the ONLY functions that call Monday.com.
Every call hits the live GraphQL endpoint — no caching across turns.

Column names below match exactly what Monday.com shows after CSV import.
Discovered via: boards(ids).columns[id, title] query.
"""
from __future__ import annotations
import logging
import time
from datetime import date
from typing import Any, Optional

from monday.client import get_all_board_items, MondayError
from monday.schema import DEALS_BOARD_ID, WORK_ORDERS_BOARD_ID
from normalize import (
    normalize_date,
    normalize_numeric,
    normalize_text,
    normalize_billing_status,
    normalize_invoice_status,
    normalize_sector,
    normalize_quantity_with_unit,
    extract_column_map,
)

logger = logging.getLogger(__name__)

# ── Cache for column schemas (per session, not persisted) ──────────────────────
_column_schema_cache: dict[str, dict[str, str]] = {}


def get_board_column_schema(board_id: str) -> dict[str, str]:
    """Fetch column name→id mapping for a board. Cached per session."""
    if board_id in _column_schema_cache:
        return _column_schema_cache[board_id]

    from monday.client import _gql_request
    query = """
    query ($boardId: [ID!]!) {
      boards(ids: $boardId) {
        columns {
          id
          title
        }
      }
    }
    """
    data = _gql_request(query, {"boardId": [board_id]})
    boards = data.get("boards", [])
    if not boards:
        return {}
    schema = {col["title"]: col["id"] for col in boards[0].get("columns", [])}
    _column_schema_cache[board_id] = schema
    logger.info(f"Board {board_id} column schema ({len(schema)} cols): {list(schema.keys())}")
    return schema


def _get_val(col_map: dict, col_id: str, key: str = "text") -> Any:
    """Safely get text or value from a column map entry."""
    entry = col_map.get(col_id)
    if entry is None:
        return None
    return entry.get(key)


# ── Deals column name mapping (actual names on Monday.com board) ───────────────
# Source name (CSV) → Monday.com board column title
DEALS_COL = {
    "deal_name":          "Name",                    # built-in item name
    "owner_code":         "Owner Code",
    "client_code":        "Client Code",
    "deal_status":        "Deal State",              # Status column with Won/Dead/Open/On Hold
    "close_date":         "Close Date",
    "closure_prob":       "Closure Probability",
    "deal_value":         "Masked Deal Value",
    "tentative_close":    "Tentative Close Date",
    "deal_stage":         "Deal Stage",
    "product_deal":       "Product Deal",
    "sector":             "Sector",                  # Dropdown column
    "created_date":       "Created Date",
}

# ── Work Orders column name mapping ───────────────────────────────────────────
WO_COL = {
    "deal_name":          "Name",
    "customer_code":      "Customer Code",
    "serial_num":         "Work Order ID",
    "nature_of_work":     "Work Description",
    "exec_status":        "Execution Status",
    "delivery_date":      "Data Delivery Date",
    "po_date":            "PO/LOI Date",
    "doc_type":           "Document Type",
    "start_date":         "Start Date",
    "end_date":           "Probable End Date",
    "bd_code":            "BD/KAM Personnel Code",
    "sector":             "Sector Name",             # Text column
    "type_of_work":       "Type of Work",
    "has_software":       "Skylark Software Involvement",
    "last_invoice_date":  "Last Invoice Date",
    "invoice_num":        "Latest Invoice No.",
    "amount_excl_gst":    "Amount Excl GST",
    "amount_incl_gst":    "Amount Incl GST",
    "billed_excl_gst":    "Billed Value Excl GST",
    "billed_incl_gst":    "Billed Value Incl GST",
    "collected":          "Collected Amount Incl GST",
    "to_bill_excl":       "Amount to be Billed Excl GST",
    "to_bill_incl":       "Amount to be Billed Incl GST",
    "receivable":         "Amount Receivable",
    "ar_priority":        "AR Priority Account",
    "qty_ops":            "Quantity by Ops",
    "qty_po":             "Quantity as per PO",
    "qty_billed":         "Quantity Billed",
    "qty_balance":        "Balance Quantity",
    "invoice_status":     "Invoice Status",
    "billing_month":      "Actual Billing Month",
    "wo_status":          "WO Status",
    "billing_status":     "Billing Status",
}


def get_deals(
    status_filter: Optional[list[str]] = None,
    sector_filter: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    date_field: str = "tentative_close_date",
) -> dict:
    """
    Fetch and normalize all deals from Monday.com Deals board.
    Returns structured deal records + data_quality block.
    IMPORTANT: No Excel files loaded. This is a live Monday.com call.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logger.info(f"[{ts}] get_deals() — live Monday.com query")

    if not DEALS_BOARD_ID:
        return _error_result("DEALS_BOARD_ID is not configured. Check .env file.")

    try:
        raw_items = get_all_board_items(DEALS_BOARD_ID)
    except MondayError as e:
        return _error_result(str(e))

    schema = get_board_column_schema(DEALS_BOARD_ID)
    total = len(raw_items)
    records = []

    for item in raw_items:
        col_map = extract_column_map(item)

        def col(field_key: str, value_type: str = "text") -> Any:
            col_title = DEALS_COL.get(field_key, "")
            col_id = schema.get(col_title)
            if col_id is None:
                return None
            return _get_val(col_map, col_id, value_type)

        owner_code, _, _    = normalize_text(col("owner_code"))
        client_code, _, _   = normalize_text(col("client_code"))
        deal_status, _, _   = normalize_text(col("deal_status"))
        closure_prob, _, _  = normalize_text(col("closure_prob"))
        deal_value, val_ok, _ = normalize_numeric(col("deal_value", "value"))
        deal_stage, _, _    = normalize_text(col("deal_stage"))
        product_deal, _, _  = normalize_text(col("product_deal"))
        sector, _, _        = normalize_sector(col("sector"))
        close_date, _, _    = normalize_date(col("close_date", "value"))
        tentative_close, _, _ = normalize_date(col("tentative_close", "value"))
        created_date, _, _  = normalize_date(col("created_date", "value"))

        # Status filter
        if status_filter:
            ds = deal_status.lower() if deal_status else ""
            if not any(f.lower() == ds for f in status_filter):
                continue

        # Sector filter
        if sector_filter:
            if not sector or sector.lower() != sector_filter.lower():
                continue

        # Date filter
        filter_date = None
        if date_field == "tentative_close_date":
            filter_date = tentative_close
        elif date_field == "close_date":
            filter_date = close_date
        elif date_field == "created_date":
            filter_date = created_date

        if date_from and filter_date and filter_date < date_from:
            continue
        if date_to and filter_date and filter_date > date_to:
            continue

        records.append({
            "id":                   item.get("id"),
            "deal_name":            item.get("name", ""),
            "owner_code":           owner_code,
            "client_code":          client_code,
            "deal_status":          deal_status,
            "close_date":           close_date.isoformat() if close_date else None,
            "closure_probability":  closure_prob,
            "deal_value":           deal_value,
            "deal_value_missing":   not val_ok,
            "tentative_close_date": tentative_close.isoformat() if tentative_close else None,
            "deal_stage":           deal_stage,
            "product_deal":         product_deal,
            "sector":               sector,
            "created_date":         created_date.isoformat() if created_date else None,
        })

    missing_value_count = sum(1 for r in records if r["deal_value_missing"])

    return {
        "records": records,
        "data_quality": {
            "records_retrieved_from_monday": total,
            "records_after_filters": len(records),
            "records_with_missing_deal_value": missing_value_count,
            "note": (
                f"{missing_value_count} of {len(records)} deals have no recorded deal value "
                "— pipeline totals may be understated."
                if missing_value_count > 0 else ""
            ),
        },
        "_meta": {
            "source": "Monday.com Deals board (live)",
            "timestamp": ts,
            "board_id": DEALS_BOARD_ID,
        },
    }


def get_work_orders(
    status_filter: Optional[list[str]] = None,
    sector_filter: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> dict:
    """
    Fetch and normalize all work orders from Monday.com Work Orders board.
    IMPORTANT: No Excel files loaded. Live Monday.com call only.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logger.info(f"[{ts}] get_work_orders() — live Monday.com query")

    if not WORK_ORDERS_BOARD_ID:
        return _error_result("WORK_ORDERS_BOARD_ID is not configured. Check .env file.")

    try:
        raw_items = get_all_board_items(WORK_ORDERS_BOARD_ID)
    except MondayError as e:
        return _error_result(str(e))

    schema = get_board_column_schema(WORK_ORDERS_BOARD_ID)
    total = len(raw_items)
    records = []

    for item in raw_items:
        col_map = extract_column_map(item)

        def col(field_key: str, value_type: str = "text") -> Any:
            col_title = WO_COL.get(field_key, "")
            col_id = schema.get(col_title)
            if col_id is None:
                return None
            return _get_val(col_map, col_id, value_type)

        customer_code, _, _  = normalize_text(col("customer_code"))
        serial_num, _, _     = normalize_text(col("serial_num"))
        nature_of_work, _, _ = normalize_text(col("nature_of_work"))
        exec_status, _, _    = normalize_text(col("exec_status"))
        delivery_date, _, _  = normalize_date(col("delivery_date", "value"))
        po_date, _, _        = normalize_date(col("po_date", "value"))
        doc_type, _, _       = normalize_text(col("doc_type"))
        start_date, _, _     = normalize_date(col("start_date", "value"))
        end_date, _, _       = normalize_date(col("end_date", "value"))
        bd_code, _, _        = normalize_text(col("bd_code"))
        sector, _, _         = normalize_sector(col("sector"))
        type_of_work, _, _   = normalize_text(col("type_of_work"))
        has_software, _, _   = normalize_text(col("has_software"))
        last_inv_date, _, _  = normalize_date(col("last_invoice_date", "value"))
        invoice_num, _, _    = normalize_text(col("invoice_num"))

        amount_excl_gst, _, _ = normalize_numeric(col("amount_excl_gst", "value"))
        amount_incl_gst, _, _ = normalize_numeric(col("amount_incl_gst", "value"))
        billed_excl_gst, _, _ = normalize_numeric(col("billed_excl_gst", "value"))
        billed_incl_gst, _, _ = normalize_numeric(col("billed_incl_gst", "value"))
        collected, _, _        = normalize_numeric(col("collected", "value"))
        to_bill_excl, _, _     = normalize_numeric(col("to_bill_excl", "value"))
        to_bill_incl, _, _     = normalize_numeric(col("to_bill_incl", "value"))
        receivable, _, _       = normalize_numeric(col("receivable", "value"))

        qty_ops, _, _           = normalize_numeric(col("qty_ops", "value"))
        qty_po_mag, qty_po_unit, _, _ = normalize_quantity_with_unit(col("qty_po"))
        qty_billed, _, _        = normalize_numeric(col("qty_billed", "value"))
        qty_balance, _, _       = normalize_numeric(col("qty_balance", "value"))

        invoice_status_raw = col("invoice_status")
        invoice_status, _, _   = normalize_invoice_status(invoice_status_raw)
        billing_month, _, _    = normalize_text(col("billing_month"))
        wo_status, _, _        = normalize_text(col("wo_status"))
        billing_status_raw     = col("billing_status")
        billing_status, _, _   = normalize_billing_status(billing_status_raw)
        ar_priority, _, _      = normalize_text(col("ar_priority"))

        # Filters
        if status_filter:
            es = exec_status.lower() if exec_status else ""
            if not any(f.lower() == es for f in status_filter):
                continue
        if sector_filter:
            if not sector or sector.lower() != sector_filter.lower():
                continue
        if date_from and start_date and start_date < date_from:
            continue
        if date_to and start_date and start_date > date_to:
            continue

        records.append({
            "id":                   item.get("id"),
            "deal_name":            item.get("name", ""),
            "customer_code":        customer_code,
            "serial_num":           serial_num,
            "nature_of_work":       nature_of_work,
            "execution_status":     exec_status,
            "data_delivery_date":   delivery_date.isoformat() if delivery_date else None,
            "po_date":              po_date.isoformat() if po_date else None,
            "document_type":        doc_type,
            "probable_start_date":  start_date.isoformat() if start_date else None,
            "probable_end_date":    end_date.isoformat() if end_date else None,
            "bd_personnel_code":    bd_code,
            "sector":               sector,
            "type_of_work":         type_of_work,
            "has_skylark_software": has_software,
            "last_invoice_date":    last_inv_date.isoformat() if last_inv_date else None,
            "invoice_num":          invoice_num,
            "amount_excl_gst":      amount_excl_gst,
            "amount_incl_gst":      amount_incl_gst,
            "billed_excl_gst":      billed_excl_gst,
            "billed_incl_gst":      billed_incl_gst,
            "collected":            collected,
            "to_bill_excl":         to_bill_excl,
            "to_bill_incl":         to_bill_incl,
            "receivable":           receivable,
            "qty_ops":              qty_ops,
            "qty_po_magnitude":     qty_po_mag,
            "qty_po_unit":          qty_po_unit,
            "qty_billed":           qty_billed,
            "qty_balance":          qty_balance,
            "invoice_status":       invoice_status,
            "invoice_status_raw":   invoice_status_raw,
            "billing_month":        billing_month,
            "wo_status":            wo_status,
            "billing_status":       billing_status,
            "billing_status_raw":   billing_status_raw,
            "ar_priority":          ar_priority,
        })

    return {
        "records": records,
        "data_quality": {
            "records_retrieved_from_monday": total,
            "records_after_filters": len(records),
            "note": (
                "4 columns are 100% empty in source data and were not imported: "
                "Expected Billing Month, Actual Collection Month, Collection status, Collection Date."
            ),
        },
        "_meta": {
            "source": "Monday.com Work Orders board (live)",
            "timestamp": ts,
            "board_id": WORK_ORDERS_BOARD_ID,
        },
    }


def _error_result(message: str) -> dict:
    return {
        "records": [],
        "error": message,
        "data_quality": {"records_retrieved_from_monday": 0, "records_after_filters": 0},
    }
