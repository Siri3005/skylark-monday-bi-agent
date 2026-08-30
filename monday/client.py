"""
Monday.com GraphQL client — read-only.
No mutation operations (create_item, change_column_value, etc.) are implemented.
Every public function in this module either reads data or raises an error.
"""
import os
import time
import logging
from typing import Any, Optional
import httpx
from dotenv import load_dotenv
from monday.schema import (
    MONDAY_API_URL,
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF,
)

load_dotenv()
logger = logging.getLogger(__name__)


def _get_token() -> str:
    token = os.environ.get("MONDAY_API_TOKEN", "")
    if not token:
        raise ValueError(
            "MONDAY_API_TOKEN is not set. Check your .env file or hosting platform secrets."
        )
    return token


def _gql_request(query: str, variables: Optional[dict] = None) -> dict:
    """
    Execute one GraphQL request against Monday.com API v2.
    Raises MondayAuthError, MondayBoardNotFoundError, MondayRateLimitError,
    MondayTimeoutError, or MondayAPIError on failure.
    """
    token = _get_token()
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                MONDAY_API_URL,
                json=payload,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
        except httpx.TimeoutException:
            raise MondayTimeoutError(
                f"Request to Monday.com timed out after {REQUEST_TIMEOUT}s. "
                "The service may be temporarily slow — please try again."
            )

        if resp.status_code == 401:
            raise MondayAuthError(
                "Monday.com authentication failed — check MONDAY_API_TOKEN configuration."
            )

        if resp.status_code == 429:
            if attempt < MAX_RETRIES:
                logger.warning("Monday.com rate-limited, backing off...")
                time.sleep(RETRY_BACKOFF * (attempt + 1))
                continue
            raise MondayRateLimitError(
                "Monday.com rate limit exceeded. Results may be incomplete — please try again shortly."
            )

        if resp.status_code >= 500:
            if attempt < MAX_RETRIES:
                logger.warning(f"Monday.com server error {resp.status_code}, retrying...")
                time.sleep(RETRY_BACKOFF * (attempt + 1))
                continue
            raise MondayAPIError(
                f"Monday.com returned a server error ({resp.status_code}). Please try again."
            )

        try:
            data = resp.json()
        except Exception:
            raise MondayAPIError("Monday.com returned an unparseable response.")

        # GraphQL-level errors
        if "errors" in data and data["errors"]:
            err = data["errors"][0]
            msg = err.get("message", str(err))
            if "not found" in msg.lower() or "doesn't exist" in msg.lower():
                raise MondayBoardNotFoundError(
                    f"Board not found or not accessible — check board ID configuration. "
                    f"API message: {msg}"
                )
            if "complexity" in msg.lower() or "rate" in msg.lower():
                if attempt < MAX_RETRIES:
                    logger.warning("Complexity/rate limit from GraphQL, backing off...")
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
                    continue
                raise MondayRateLimitError(
                    f"Monday.com complexity budget exceeded: {msg}. Results may be incomplete."
                )
            raise MondayAPIError(f"Monday.com GraphQL error: {msg}")

        return data.get("data", {})

    raise MondayAPIError("Monday.com request failed after all retries.")


def get_board_items_count(board_id: str) -> int:
    """Return the total item count for a board (lightweight check)."""
    query = """
    query ($boardId: [ID!]!) {
      boards(ids: $boardId) {
        items_count
      }
    }
    """
    data = _gql_request(query, {"boardId": [board_id]})
    boards = data.get("boards", [])
    if not boards:
        raise MondayBoardNotFoundError(
            f"Board ID {board_id} not found — check DEALS_BOARD_ID / WORK_ORDERS_BOARD_ID."
        )
    return boards[0].get("items_count", 0)


def get_all_board_items(board_id: str) -> list[dict]:
    """
    Fetch ALL items from a board using cursor-based pagination.
    Logs request timestamp and item count on every page.
    Verifies final count against board's items_count.
    Returns a list of raw item dicts with 'id', 'name', 'column_values'.
    """
    board_id_str = str(board_id)

    # Verify board exists and get expected count
    expected_count = get_board_items_count(board_id_str)
    logger.info(
        f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] "
        f"Fetching board {board_id_str} — expected {expected_count} items"
    )

    query = """
    query ($boardId: [ID!]!, $limit: Int!, $cursor: String) {
      boards(ids: $boardId) {
        items_page(limit: $limit, cursor: $cursor) {
          cursor
          items {
            id
            name
            column_values {
              id
              text
              value
            }
          }
        }
      }
    }
    """

    all_items: list[dict] = []
    seen_ids: set[str] = set()
    cursor: Optional[str] = None
    page = 0

    while True:
        variables: dict[str, Any] = {
            "boardId": [board_id_str],
            "limit": PAGE_SIZE,
        }
        if cursor:
            variables["cursor"] = cursor

        data = _gql_request(query, variables)
        boards = data.get("boards", [])
        if not boards:
            raise MondayBoardNotFoundError(
                f"Board ID {board_id_str} not found during pagination."
            )

        page_data = boards[0].get("items_page", {})
        items = page_data.get("items", [])
        next_cursor = page_data.get("cursor")

        # Deduplicate by item id
        new_items = [i for i in items if i["id"] not in seen_ids]
        for item in new_items:
            seen_ids.add(item["id"])
        all_items.extend(new_items)
        page += 1

        logger.info(
            f"  Page {page}: got {len(items)} items (cumulative: {len(all_items)})"
        )

        if not next_cursor:
            break
        cursor = next_cursor

    # Verify count
    if len(all_items) != expected_count:
        logger.warning(
            f"Board {board_id_str}: retrieved {len(all_items)} items but "
            f"board reports {expected_count}. Results may be partial."
        )

    logger.info(
        f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] "
        f"Board {board_id_str}: retrieved {len(all_items)} / {expected_count} items"
    )
    return all_items


# ── Custom Exceptions ──────────────────────────────────────────────────────────

class MondayError(Exception):
    """Base class for all Monday.com client errors."""
    pass

class MondayAuthError(MondayError):
    pass

class MondayBoardNotFoundError(MondayError):
    pass

class MondayRateLimitError(MondayError):
    pass

class MondayTimeoutError(MondayError):
    pass

class MondayAPIError(MondayError):
    pass
