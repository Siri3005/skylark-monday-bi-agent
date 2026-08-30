# Decision Log — Skylark Drones BI Agent

## Key Assumptions

- **Calendar quarters** used for "this/last quarter" logic (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec). No fiscal year specified in the brief or data — stated assumption.
- **"Revenue" is ambiguous** → agent asks for basis (deal_value / billed / collected) rather than guessing. Three distinct real numbers exist in the data that could all qualify as "revenue."
- **Weighted pipeline probability mapping**: High=75%, Medium=50%, Low=25%. `Closure Probability` is categorical (High/Med/Low) in the source — not a numeric percentage. Any weighted total uses this documented mapping, stated in every weighted answer.
- **12 duplicate deal rows were kept**, not deleted, to avoid silently removing real business records without confirmation from the business owner. Their presence is documented here.
- **`Executed until current month` = ACTIVE**, not Completed. These are recurring contracts — collapsing them into "Completed" would undercount active work.
- **4 Work Order columns not imported** (`Expected Billing Month`, `Actual Collection Month`, `Collection status`, `Collection Date`): 100% null in source data. No information content — importing them would just add empty columns.
- **`Quantities as per PO` kept as Text** (not Numbers): contains embedded units like "5360 HA" that would be silently truncated if imported as Numbers. Unit-aware parsing happens agent-side.

## Trade-offs

- **Single Streamlit app instead of separate FastAPI + frontend**: Faster to build and deploy within the time constraint. The brief requires "a working agent accessible via link" — a single Streamlit app satisfies this without an extra deployment surface. The tradeoff is a less "production" UI, which the brief explicitly de-prioritizes.
- **GraphQL API instead of MCP**: Lower setup risk, directly callable from Python with no additional infrastructure. MCP would satisfy the brief equally — this choice was made because it's the more robust option for most setups.
- **Cross-board analysis scoped to sector and owner/BD level only**: `Client Code` (Deals) uses `COMPANY0xx` masking; `Customer Name Code` (Work Orders) uses `WOCOMPANY_0xx`. These are different namespaces — no verified mapping exists between them. A customer-level join would have been fabricated, not evidence-based. Documented limitation, not a shortcut.
- **No persistent caching**: Every answer re-queries Monday.com live. Latency cost is acceptable for a 6-hour prototype; the benefit is guaranteed dynamic retrieval (the core evaluation criterion).
- **Hand-rolled tool-calling loop** instead of LangGraph/LangChain: ~60 lines of transparent code that's easy to demo, debug, and understand. Heavy frameworks add setup risk with no material benefit at ≤10 tools.

## What I'd Do Differently with More Time

- Resolve the `Client Code` / `Customer Name Code` mapping with the business owner to enable customer-level cross-board analysis.
- Add a hard numeric-provenance check that blocks (not just logs) any LLM response containing a number not present in tool results.
- Build a board column schema cache with TTL so repeated queries don't re-fetch the column schema each time.
- Add automated tests for the retrieval layer with a mock Monday.com server to enable CI without live API access.
- Explore whether Monday.com Item IDs from the auto-import can be manually cross-referenced to the `Serial #` field to enable deal-level cross-board linking.

## "Leadership Updates" Interpretation

Implemented as a **single-turn executive summary** that calls `calculate_pipeline()`, `calculate_revenue(basis="billed")`, `calculate_revenue(basis="collected")`, `calculate_operational_metrics()`, and `calculate_sector_performance()` with no filters, then asks the LLM to synthesize their combined JSON output into a structured summary.

This is NOT a scheduled report, email-sending feature, or separate data model. The scoping decision was: the brief leaves "leadership update" open-ended; the most valuable and realistic interpretation within the time budget is a one-click executive snapshot from existing tools.

## Data Quality Decisions

- **Junk rows**: 2 rows in Deals where every cell equals its column header (e.g., `Deal Status = "Deal Status"`). These are re-pasted header artifacts. Removed before import — not real deals.
- **`BIlled` typo**: 3 occurrences of `BIlled` in Work Orders `Billing Status`. High-confidence correction (clear typo, not a semantic merge). Fixed both at import time and defensively in the normalization layer.
- **`Billed- Visit N` in Invoice Status**: Two irregular values (`Billed- Visit 7`, `Billed- Visit 3`). These appear to be per-visit billing status entries from a different taxonomy. Mapped to `Partially Billed (per-visit)` with original value preserved.
- **Deal Stage ordering**: 16 distinct labels, mostly letter-prefixed (A–O). Two labels break the convention (`Project Completed`, junk-row values). Stage order is not assumed to be strictly alphabetical — no funnel waterfall is built that depends on ordinal stage order.
