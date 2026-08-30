"""
Retrieval tools: get_deals() and get_work_orders().
These are the ONLY functions that call Monday.com.
Every call hits the live GraphQL endpoint — no caching across turns.
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

# ── Column ID mappings ─────────────────────────────────────────────────────────
# These are the Monday.com column IDs that correspond to our source columns.
# They are detected dynamically from the first item fetched, not hardcoded,
# using the column names we set during CSV import.
# However, we define the canonical column *name* → internal ID mapping here
# so the code stays readable. The actual IDs are board-specific and must be
# discovered at runtime via _discover_column_ids().

# Deals column names (as imported from CSV)
DEALS_COLUMN_NAMES = [
    "Owner code", "Client Code", "Deal Status", "Close Date (A)",
    "Closure Probability", "Masked Deal value", "Tentative Close Date",
    "Deal Stage", "Product deal", "Sector/service", "Created Date",
]

# Work Orders column names (as imported from CSV)
WO_COLUMN_NAMES = [
    "Customer Name Code", "Serial #", "Nature of Work",
    "Last executed month of recurring project", "Execution Status",
    "Data Delivery Date", "Date of PO/LOI", "Document Type",
    "Probable Start Date", "Probable End Date", "BD/KAM Personnel code",
    "Sector", "Type of Work",
    "Is any Skylark software platform part of the client deliverables in this deal?",
    "Last invoice date", "latest invoice no.",
    "Amount in Rupees (Excl of GST) (Masked)",
    "Amount in Rupees (Incl of GST) (Masked)",
    "Billed Value in Rupees (Excl of GST.) (Masked)",
    "Billed Value in Rupees (Incl of GST.) (Masked)",
    "Collected Amount in Rupees (Incl of GST.) (Masked)",
    "Amount to be billed in Rs. (Exl. of GST) (Masked)",
    "Amount to be billed in Rs. (Incl. of GST) (Masked)",
    "Amount Receivable (Masked)",
    "AR Priority account", "Quantity by Ops", "Quantities as per PO",
    "Quantity billed (till date)", "Balance in quantity",
    "Invoice Status", "Actual Billing Month",
    "WO Status (billed)", "Billing Status",
    # Note: Expected Billing Month, Actual Collection Month,
    # Collection status, Collection Date are 100% null — omitted.
]


def _discover_column_ids(items: list[dict], expected_names: list[str]) -> dict[str, str]:
    """
    Build a name→id map by scanning column_values of the first item.
    Monday.com stores column IDs as short slugs (e.g. 'text', 'status0').
    The item 'name' field is the board's built-in name column (no column_value entry).
    Falls back to matching on column id directly if text matching fails.
    """
    if not items:
        return {}
    col_map = {}
    # Monday.com doesn't expose column *names* in column_values — only ids.
    # We need to use the boards.columns query to get the name→id mapping.
    # Since we don't do that here (keeps retrieval simple), we rely on the
    # column IDs being consistent once a board is created. The mapping is
    # built via get_board_column_schema() which is called lazily.
    return col_map


# Cache for column schemas (per session, not persisted)
_column_schema_cache: dict[str, dict[str, str]] = {}  # board_id -> {name: col_id}


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
    logger.info(f"Board {board_id} column schema: {list(schema.keys())}")
    return schema


def _get_val(col_map: dict, col_id: str, key: str = "text") -> Any:
    """Safely get text or value from a column map."""
    entry = col_map.get(col_id)
    if entry is None:
        return None
    return entry.get(key)


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

    Parameters:
        status_filter: e.g. ["Open", "Won"] — filters Deal Status
        sector_filter: e.g. "Mining" — case-insensitive match on Sector/service
        date_from / date_to: filter on date_field
        date_field: one of 'tentative_close_date', 'close_date', 'created_date'

    IMPORTANT: No Excel files are loaded here. This is a live Monday.com call.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logger.info(f"[{ts}] get_deals() called — live Monday.com query")

    if not DEALS_BOARD_ID:
        return _error_result("DEALS_BOARD_ID is not configured. Check .env file.")

    try:
        raw_items = get_all_board_items(DEALS_BOARD_ID)
    except MondayError as e:
        return _error_result(str(e))

    schema = get_board_column_schema(DEALS_BOARD_ID)

    records = []
    excluded = {"missing_deal_value": 0, "invalid_date": 0, "junk_row": 0}
    total = len(raw_items)

    for item in raw_items:
        col_map = extract_column_map(item)

        # Item name is the deal name
        deal_name = item.get("name", "")

        # Helper to get column value by title
        def col(title: str, field: str = "text") -> Any:
            cid = schema.get(title)
            if cid is None:
                return None
            return _get_val(col_map, cid, field)

        # Parse fields
        owner_code, _, _ = normalize_text(col("Owner code"))
        client_code, _, _ = normalize_text(col("Client Code"))
        deal_status, _, _ = normalize_text(col("Deal Status"))
        closure_prob, _, _ = normalize_text(col("Closure Probability"))
        deal_value, value_valid, _ = normalize_numeric(col("Masked Deal value", "value"))
        deal_stage, _, _ = normalize_text(col("Deal Stage"))
        product_deal, _, _ = normalize_text(col("Product deal"))
        sector, _, _ = normalize_sector(col("Sector/service"))
        close_date, cd_valid, _ = normalize_date(col("Close Date (A)", "value"))
        tentative_close, tc_valid, _ = normalize_date(col("Tentative Close Date", "value"))
        created_date, cr_valid, _ = normalize_date(col("Created Date", "value"))

        # Apply filters
        if status_filter:
            normalized_status = deal_status.lower() if deal_status else ""
            if not any(f.lower() == normalized_status for f in status_filter):
                continue

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

        if date_from and filter_date:
            if filter_date < date_from:
                continue
        if date_to and filter_date:
            if filter_date > date_to:
                continue

        record = {
            "id": item.get("id"),
            "deal_name": deal_name,
            "owner_code": owner_code,
            "client_code": client_code,
            "deal_status": deal_status,
            "close_date": close_date.isoformat() if close_date else None,
            "closure_probability": closure_prob,
            "deal_value": deal_value,
            "deal_value_missing": not value_valid,
            "tentative_close_date": tentative_close.isoformat() if tentative_close else None,
            "deal_stage": deal_stage,
            "product_deal": product_deal,
            "sector": sector,
            "created_date": created_date.isoformat() if created_date else None,
        }
        records.append(record)

    missing_value_count = sum(1 for r in records if r["deal_value_missing"])

    return {
        "records": records,
        "data_quality": {
            "records_retrieved_from_monday": total,
            "records_after_filters": len(records),
            "records_with_missing_deal_value": missing_value_count,
            "note": (
                f"{missing_value_count} of {len(records)} deals in this result "
                "have no recorded deal value and are excluded from value totals — "
                "the true pipeline value may be higher."
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
    Returns structured WO records + data_quality block.
    IMPORTANT: No Excel files loaded. Live Monday.com call only.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    logger.info(f"[{ts}] get_work_orders() called — live Monday.com query")

    if not WORK_ORDERS_BOARD_ID:
        return _error_result("WORK_ORDERS_BOARD_ID is not configured. Check .env file.")

    try:
        raw_items = get_all_board_items(WORK_ORDERS_BOARD_ID)
    except MondayError as e:
        return _error_result(str(e))

    schema = get_board_column_schema(WORK_ORDERS_BOARD_ID)

    records = []
    total = len(raw_items)
    missing_monetary = 0

    for item in raw_items:
        col_map = extract_column_map(item)
        deal_name = item.get("name", "")

        def col(title: str, field: str = "text") -> Any:
            cid = schema.get(title)
            if cid is None:
                return None
            return _get_val(col_map, cid, field)

        customer_code, _, _ = normalize_text(col("Customer Name Code"))
        serial_num, _, _ = normalize_text(col("Serial #"))
        nature_of_work, _, _ = normalize_text(col("Nature of Work"))
        exec_status, _, _ = normalize_text(col("Execution Status"))
        delivery_date, _, _ = normalize_date(col("Data Delivery Date", "value"))
        po_date, _, _ = normalize_date(col("Date of PO/LOI", "value"))
        doc_type, _, _ = normalize_text(col("Document Type"))
        start_date, _, _ = normalize_date(col("Probable Start Date", "value"))
        end_date, _, _ = normalize_date(col("Probable End Date", "value"))
        bd_code, _, _ = normalize_text(col("BD/KAM Personnel code"))
        sector, _, _ = normalize_sector(col("Sector"))
        type_of_work, _, _ = normalize_text(col("Type of Work"))
        has_software, _, _ = normalize_text(
            col("Is any Skylark software platform part of the client deliverables in this deal?")
        )
        last_invoice_date, _, _ = normalize_date(col("Last invoice date", "value"))
        invoice_num, _, _ = normalize_text(col("latest invoice no."))

        # Monetary fields
        amount_excl_gst, _, _ = normalize_numeric(col("Amount in Rupees (Excl of GST) (Masked)", "value"))
        amount_incl_gst, _, _ = normalize_numeric(col("Amount in Rupees (Incl of GST) (Masked)", "value"))
        billed_excl_gst, _, _ = normalize_numeric(col("Billed Value in Rupees (Excl of GST.) (Masked)", "value"))
        billed_incl_gst, _, _ = normalize_numeric(col("Billed Value in Rupees (Incl of GST.) (Masked)", "value"))
        collected, _, _ = normalize_numeric(col("Collected Amount in Rupees (Incl of GST.) (Masked)", "value"))
        to_bill_excl, _, _ = normalize_numeric(col("Amount to be billed in Rs. (Exl. of GST) (Masked)", "value"))
        to_bill_incl, _, _ = normalize_numeric(col("Amount to be billed in Rs. (Incl. of GST) (Masked)", "value"))
        receivable, _, _ = normalize_numeric(col("Amount Receivable (Masked)", "value"))

        # Quantity fields
        qty_ops, _, _ = normalize_numeric(col("Quantity by Ops", "value"))
        qty_po_mag, qty_po_unit, qty_po_valid, _ = normalize_quantity_with_unit(col("Quantities as per PO"))
        qty_billed, _, _ = normalize_numeric(col("Quantity billed (till date)", "value"))
        qty_balance, _, _ = normalize_numeric(col("Balance in quantity", "value"))

        # Status fields
        invoice_status_raw = col("Invoice Status")
        invoice_status, _, _ = normalize_invoice_status(invoice_status_raw)
        billing_month, _, _ = normalize_text(col("Actual Billing Month"))
        wo_status, _, _ = normalize_text(col("WO Status (billed)"))
        billing_status_raw = col("Billing Status")
        billing_status, _, _ = normalize_billing_status(billing_status_raw)
        ar_priority, _, _ = normalize_text(col("AR Priority account"))

        # Apply filters
        if status_filter:
            normalized_status = exec_status.lower() if exec_status else ""
            if not any(f.lower() == normalized_status for f in status_filter):
                continue
        if sector_filter:
            if not sector or sector.lower() != sector_filter.lower():
                continue

        # Date filter on probable start date
        if date_from and start_date and start_date < date_from:
            continue
        if date_to and start_date and start_date > date_to:
            continue

        if amount_excl_gst is None and billed_excl_gst is None:
            missing_monetary += 1

        record = {
            "id": item.get("id"),
            "deal_name": deal_name,
            "customer_code": customer_code,
            "serial_num": serial_num,
            "nature_of_work": nature_of_work,
            "execution_status": exec_status,
            "data_delivery_date": delivery_date.isoformat() if delivery_date else None,
            "po_date": po_date.isoformat() if po_date else None,
            "document_type": doc_type,
            "probable_start_date": start_date.isoformat() if start_date else None,
            "probable_end_date": end_date.isoformat() if end_date else None,
            "bd_personnel_code": bd_code,
            "sector": sector,
            "type_of_work": type_of_work,
            "has_skylark_software": has_software,
            "last_invoice_date": last_invoice_date.isoformat() if last_invoice_date else None,
            "invoice_num": invoice_num,
            "amount_excl_gst": amount_excl_gst,
            "amount_incl_gst": amount_incl_gst,
            "billed_excl_gst": billed_excl_gst,
            "billed_incl_gst": billed_incl_gst,
            "collected": collected,
            "to_bill_excl": to_bill_excl,
            "to_bill_incl": to_bill_incl,
            "receivable": receivable,
            "qty_ops": qty_ops,
            "qty_po_magnitude": qty_po_mag,
            "qty_po_unit": qty_po_unit,
            "qty_billed": qty_billed,
            "qty_balance": qty_balance,
            "invoice_status": invoice_status,
            "invoice_status_raw": invoice_status_raw,
            "billing_month": billing_month,
            "wo_status": wo_status,
            "billing_status": billing_status,
            "billing_status_raw": billing_status_raw,
            "ar_priority": ar_priority,
        }
        records.append(record)

    return {
        "records": records,
        "data_quality": {
            "records_retrieved_from_monday": total,
            "records_after_filters": len(records),
            "note": (
                f"Note: 'Expected Billing Month', 'Actual Collection Month', "
                "'Collection status', 'Collection Date' are 100% empty in source data and were not imported."
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
