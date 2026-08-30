# Decision Log — Skylark Drones BI Agent

## Key Assumptions

- **Calendar quarters** (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec) are used for "this/last quarter" queries. No fiscal year is specified in the data.
- **"Revenue" is genuinely ambiguous** — three distinct real numbers exist: billed value (Work Orders), collected amount (Work Orders), and won deal value (Deals). The agent asks for clarification rather than guessing.
- **Weighted pipeline probabilities:** High = 75%, Medium = 50%, Low = 25%. The source field is categorical, not numeric. Any weighted calculation states this assumption.
- **12 duplicate deal rows were retained.** Silently removing real business records without confirmation is riskier than importing documented duplicates.
- **`Executed until current month` = ACTIVE** — recurring contracts, not completed work.
- **`Amount Incl GST` (Work Orders) is 100% empty** on this board. Contract value is `Amount Excl GST`; invoiced value is `Billed Value Incl GST` (fully populated). Both are shown in cross-board comparisons.
- **4 Work Order columns were not imported:** `Expected Billing Month`, `Actual Collection Month`, `Collection Status`, `Collection Date` — all 100% null in source.

---

## Technology Decisions

**No external LLM API.** The domain is bounded — two boards, ~15 question types, finite sector and status values. A deterministic parser handles this reliably at zero runtime cost, with fully auditable results. The architecture supports adding an LLM backend later at the parser/responder layer without changing any BI tools or Monday.com integration.

**Trade-off:** A deterministic parser has less linguistic flexibility than a general-purpose LLM. It handles well-structured founder questions reliably but may fail on highly idiomatic phrasing. This is a documented limitation.

**Single Streamlit app, no separate backend.** The assignment requires "a working agent accessible via link." A single Streamlit app satisfies this without an extra deployment surface. The trade-off is a less "production" UI — the brief explicitly de-prioritises visual polish.

**GraphQL API over MCP.** Directly callable from Python with no additional infrastructure. MCP would satisfy the brief equally; GraphQL was chosen as the lower-risk option.

**No persistent caching.** Every answer re-queries Monday.com live. Latency cost (~4–6 s) is acceptable; the benefit is guaranteed dynamic retrieval, which is the core evaluation criterion.

---

## Cross-Board Analysis Approach

Sector and owner/BD level joins are reliable (same taxonomy and same masking scheme on both boards). Customer-level join is not implemented: `Client Code` (Deals) uses `COMPANY0xx` masking; `Customer Name Code` (Work Orders) uses `WOCOMPANY_0xx`. These are different namespaces with no verified mapping. Fabricating a join would produce misleading results. The agent states this limitation explicitly.

---

## Data Quality Decisions

- **Junk rows (2 in Deals):** Rows where every cell equals its column header — spreadsheet artefacts. Removed before import.
- **`BIlled` typo (3 occurrences):** Corrected to `Billed` at import time and in the normalisation layer.
- **`Billed- Visit N` invoice status:** Mapped to `Partially Billed (per-visit)` with original value preserved.
- **Pipeline totals:** 52% of deals have no deal value. Every pipeline answer surfaces this caveat — the figure is materially understated.
- **No trend data:** The boards store cumulative totals. "Are collections improving?" returns the current total with an explicit note that a trend cannot be calculated from the available data.

---

## "Leadership Updates" Interpretation

Implemented as a single-turn executive summary calling `calculate_pipeline()`, `calculate_revenue(billed)`, `calculate_revenue(collected)`, `calculate_operational_metrics()`, and `calculate_sector_performance()`, then formatting the combined results into a structured markdown report. Not a scheduled report or email feature.

---

## What Would Change with More Time

- Monthly data snapshots to support genuine trend queries
- Resolution of the customer ID mismatch to enable customer-level cross-board analysis
- Automated retrieval-layer tests using a Monday.com mock server
- Optional LLM backend at the parser/responder layer for improved linguistic flexibility
