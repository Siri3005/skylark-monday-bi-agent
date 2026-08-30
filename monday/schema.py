"""
Board and column ID constants for Monday.com boards.
Board IDs are loaded from environment variables — never hardcoded here.
Column IDs are the internal Monday.com column identifiers fetched dynamically
or mapped from the board schema on first load.
"""
import os
from dotenv import load_dotenv

load_dotenv()

MONDAY_API_URL = "https://api.monday.com/v2"

# Board IDs — loaded from env
DEALS_BOARD_ID: str = os.environ.get("DEALS_BOARD_ID", "")
WORK_ORDERS_BOARD_ID: str = os.environ.get("WORK_ORDERS_BOARD_ID", "")

# Human-readable board names (for error messages)
BOARD_NAMES = {
    "deals": "Deals",
    "work_orders": "Work Orders",
}

# Pagination page size — Monday.com recommends ≤500; 200 is safe for complex boards
PAGE_SIZE = 200

# Request timeout in seconds
REQUEST_TIMEOUT = 15

# Max retries for transient errors
MAX_RETRIES = 2
RETRY_BACKOFF = 1.5  # seconds

# Weighted pipeline probability mapping (documented assumption)
CLOSURE_PROBABILITY_WEIGHTS = {
    "high": 0.75,
    "medium": 0.50,
    "low": 0.25,
}

# Sectors that appear only in Deals (not in Work Orders)
DEALS_ONLY_SECTORS = {"DSP", "Tender", "Manufacturing", "Security and Surveillance", "Aviation"}

# Active execution statuses for Work Orders (NOT just "Completed")
ACTIVE_EXECUTION_STATUSES = {
    "Ongoing",
    "Not Started",
    "Executed until current month",  # recurring contracts — functionally active
    "Partial Completed",
    "Details pending from Client",
}

COMPLETED_EXECUTION_STATUSES = {"Completed"}
