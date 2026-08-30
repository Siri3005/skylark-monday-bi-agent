# Decision Log — Skylark Drones BI Agent

## 1. Why No External LLM API

**Decision:** The agent uses deterministic Python for query understanding and response generation — no Gemini, OpenAI, or Anthropic API.

**Reasoning:** The assignment data is structured and finite (344 deals, 176 work orders, ~15 distinct question types). A regex + synonym-dictionary parser is sufficient, auditable, and costs nothing to run. All calculations are deterministic Python regardless of whether an LLM is used, so the LLM would only handle language in and language out — a layer that can be added later without changing anything else.

**Trade-off:** A deterministic parser has less linguistic flexibility than a general-purpose LLM. It handles well-structured founder questions reliably but may not parse highly idiomatic or ambiguous phrasing. This is documented as a known limitation.

**LLM-pluggable architecture:** The `agent/parser.py` → `agent/planner.py` → `agent/responder.py` pipeline is explicitly designed so an LLM can replace the parser and/or responder steps without touching the BI tools or Monday.com integration.

---

## 2. Technology Decisions

**Single Streamlit app (no separate FastAPI):** The assignment requires "a working agent accessible via link." A single Streamlit app satisfies this without an extra deployment surface. The trade-off is a less "production" UI — the brief explicitly de-prioritises visual polish.

**GraphQL API over MCP:** Directly callable from Python with no additional infrastructure. MCP would satisfy the brief equally — GraphQL was chosen because it is the lower-risk option for most setups and requires no local server.

**No persistent caching:** Every answer re-queries Monday.com live. Latency cost (~3–5s) is acceptable; the benefit is guaranteed dynamic retrieval, which is the core evaluation criterion.

---

## 3. Key Assumptions

- **Calendar quarters** (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec) for "this/last quarter." No fiscal year specified — documented default.
- **"Revenue" is genuinely ambiguous** — three distinct numbers exist: billed value (Work Orders), collected amount (Work Orders), and won deal value (Deals). The agent asks for clarification rather than guessing.
- **Weighted pipeline mapping:** High=75%, Med=50%, Low=25%. `Closure Probability` is categorical in the source data, not numeric. Stated assumption in every weighted answer.
- **12 duplicate deal rows kept** — not silently deleted. Removing real business records without confirmation is riskier than retaining documented duplicates.
- **`Executed until current month` = ACTIVE** — recurring contracts counted as active, not completed.
- **4 fully-empty Work Order columns not imported:** `Expected Billing Month`, `Actual Collection Month`, `Collection status`, `Collection Date` — 100% null, no information content.

---

## 4. Cross-Board Analysis Approach

**Reliable joins (implemented):** Sector level (same taxonomy on both boards) and owner/BD level (same `OWNER_00x` masking scheme).

**Customer-level join not implemented:** `Client Code` (Deals) uses `COMPANY0xx` masking; `Customer Name Code` (Work Orders) uses `WOCOMPANY_0xx`. These are different namespaces with no verified mapping. A join would be fabricated. The agent states this limitation explicitly rather than producing misleading results.

---

## 5. "Leadership Updates" Interpretation

Implemented as a single-turn executive summary calling `calculate_pipeline()`, `calculate_revenue(billed)`, `calculate_revenue(collected)`, `calculate_operational_metrics()`, and `calculate_sector_performance()` — then formatting the combined results into a structured markdown report. Not a scheduled report, not an email feature. This scoping is documented because the brief leaves it open-ended.

---

## 6. Data Quality Decisions

- **Junk rows (2):** Rows where every cell equals its column header — spreadsheet artifacts. Removed before import.
- **`BIlled` typo (3 occurrences):** Corrected to `Billed` at import time and defensively in the normalization layer.
- **`Billed- Visit N` invoice status:** Mapped to `Partially Billed (per-visit)` with original value preserved.
- **Pipeline totals:** 52% of deals have no deal value. Every pipeline answer surfaces this caveat — the figure is materially understated.
- **No trend data:** The boards store cumulative totals, not time-series. Questions like "are collections improving?" return the total with an explicit limitation note.

---

## 7. What Would Change with More Time

- Resolve the `Client Code` / `Customer Name Code` mapping to enable customer-level cross-board analysis
- Add time-series tracking (monthly snapshots) to support genuine trend queries
- Improve the NLP parser for more idiomatic phrasing, or add an optional LLM backend
- Add automated tests for the retrieval layer using a mock Monday.com server
