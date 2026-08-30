# Skylark Drones — Monday.com BI Agent

A conversational, founder-level business intelligence agent that connects to Monday.com and answers natural-language questions about the company's sales pipeline and work order execution — with no external LLM API required.

---

## 1. Project Overview

Skylark Drones manages two Monday.com boards — a **Deals** board tracking the sales pipeline and a **Work Orders** board tracking operational execution and billing. Answering cross-functional BI questions (pipeline health, billing vs collections, sector performance, outstanding receivables) previously required manual data pulls and ad-hoc analysis.

This agent lets a founder type a question in plain English and get back a structured, insight-driven answer drawn directly from live Monday.com data.

---

## 2. Key Features

- **Conversational interface** — chat-style questions, not fixed dashboard buttons
- **No external LLM API** — fully deterministic query understanding and response generation
- **Live Monday.com data** — every answer queries the API at the moment the question is asked; no cached or hardcoded data
- **Read-only** — the agent never creates, modifies, or deletes Monday.com records
- **Clarifying questions** — genuinely ambiguous queries trigger a clarification rather than a guess
- **Cross-board analysis** — questions spanning both Deals and Work Orders are handled at the sector and owner level
- **Data-quality caveats** — missing or incomplete values are surfaced in every affected answer
- **Auditable calculations** — all arithmetic is deterministic Python; results are fully traceable

---

## 3. Architecture

```
User question
      │
      ▼
Streamlit Chat UI  (app.py)
      │
      ▼
┌─────────────────────────────────────────────────────┐
│                  Deterministic Agent                │
│                                                     │
│  1. Parser        agent/parser.py                   │
│     regex + synonym dictionaries                    │
│     → intent, dataset, sector, period, groupby      │
│     → ambiguity detection + clarification trigger   │
│                                                     │
│  2. Planner       agent/planner.py                  │
│     ParsedQuery → tool execution plan               │
│     → selects correct BI tool(s) + parameters       │
│                                                     │
│  3. BI Tools      tools/                            │
│     deterministic Python calculations               │
│     retrieval · calculations · cross_board          │
│     data_quality                                    │
│                                                     │
│  4. Responder     agent/responder.py                │
│     structured data → conversational markdown       │
│     headline metric + breakdown + insight + caveat  │
└─────────────────────────────────────────────────────┘
      │
      ▼
Monday.com GraphQL Client  (monday/client.py)
  Read-only · cursor pagination · retry + error handling
      │
      ├── Deals board        ID: 5030966266  (344 records)
      └── Work Orders board  ID: 5030966343  (176 records)
```

**No external LLM is used.** The architecture is deliberately LLM-pluggable — the parser and responder layers could be replaced with an LLM backend without changing any BI tools or Monday.com integration.

---

## 4. Technology Stack

| Component | Technology | Why |
|---|---|---|
| UI | Streamlit | Fastest path to a hosted chat interface; one deployment surface |
| Query understanding | Deterministic NLP (regex + synonym dicts) | No API cost, auditable, predictable results |
| Monday.com | GraphQL API v2 | Directly callable from Python; full cursor pagination |
| HTTP client | httpx | Async-capable, clean timeout/retry handling |
| Data normalization | Pure Python | Transparent, testable, no runtime dependencies |
| Deployment | Streamlit Community Cloud | Free, zero-config public URL |

**Why no LLM API?** The domain is bounded — two boards, ~15 question types, finite sector/status values. A deterministic parser handles this reliably, costs nothing to run, and produces fully auditable results. The limitation is reduced linguistic flexibility for unusual phrasing, which is documented.

---

## 5. Project Structure

```
skylark-monday-bi-agent/
├── app.py                        # Streamlit entry point
├── normalize.py                  # Date / text / numeric normalization
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── DECISION_LOG.md
│
├── agent/
│   ├── loop.py                   # Main agent orchestration
│   ├── parser.py                 # Natural-language query parser
│   ├── planner.py                # Query plan execution
│   ├── responder.py              # Structured data → conversational text
│   ├── tool_dispatcher.py        # Routes tool names to Python functions
│   └── _legacy/                  # Prior Gemini-era files (archived)
│
├── monday/
│   ├── client.py                 # GraphQL client, pagination, error handling
│   └── schema.py                 # Board IDs, config constants
│
├── tools/
│   ├── retrieval.py              # get_deals(), get_work_orders()
│   ├── calculations.py           # pipeline, revenue, operational metrics
│   ├── cross_board.py            # sector + owner cross-board analysis
│   └── data_quality.py           # null counts, known issues report
│
├── tests/
│   ├── test_calculations.py      # Normalization + calculation unit tests
│   └── test_parser.py            # NLP parser unit tests
│
└── scripts/
    ├── one_time_ingest.py        # One-time: Excel → CSV for board setup
    ├── test_monday_integration.py # Live Monday.com integration tests
    └── validate_scenarios.py     # Assignment scenario validation
```

**Runtime data source:** Monday.com exclusively. The `scripts/one_time_ingest.py` script was used once to prepare the CSV files for board import. No CSV or Excel file is read at runtime.

---

## 6. Monday.com Setup

The boards are already created and populated. No action needed to run the application.

**Board details:**

| Board | ID | Records |
|---|---|---|
| Deals | `5030966266` | 344 |
| Work Orders | `5030966343` | 176 |

**To recreate boards from scratch** (e.g., on a new account):
1. Run `python scripts/one_time_ingest.py` from the parent directory to generate cleaned CSVs
2. In Monday.com: Add board → Import from Excel/CSV for each file
3. Verify item counts match (344 Deals, 176 Work Orders)
4. Get board IDs from the board URL: `monday.com/boards/<ID>`

**API token:**
Monday.com → avatar (bottom left) → Administration → API → copy your personal token

---

## 7. Environment Variables

Copy `.env.example` to `.env` and fill in your token:

```
MONDAY_API_TOKEN=your_token_here
DEALS_BOARD_ID=5030966266
WORK_ORDERS_BOARD_ID=5030966343
```

No LLM API key is required.

---

## 8. Running Locally

```bash
cd skylark-monday-bi-agent
pip install -r requirements.txt
cp .env.example .env
# Add your MONDAY_API_TOKEN to .env

python -m streamlit run app.py
```

Open http://localhost:8501

---

## 9. Example Queries

| Question | What it does |
|---|---|
| `How many deals and work orders do we have?` | Counts both boards with status breakdown |
| `What's our open pipeline value?` | Pipeline total with sector breakdown and data-quality note |
| `Break the pipeline down by sector` | Ranked sector table with missing-value counts |
| `How's our pipeline for energy this quarter?` | Filtered pipeline (Renewables sector, current quarter) |
| `Which sector has the highest pipeline?` | Ranked sectors, top contributor identified |
| `How much is outstanding?` | Total receivables with billed/collected breakdown |
| `Which customers have the highest receivables?` | Per-customer ranked table (51 customers) |
| `How are collections improving?` | Collections total + limitation note (no time-series) |
| `How many work orders are active vs completed?` | Execution status breakdown with financials |
| `Which sectors have both high pipeline and high work order value?` | Cross-board sector table: pipeline + contract + billed |
| `Compare pipeline and execution by sector` | Cross-board sector comparison table |
| `What's our revenue?` | Asks: billed, collected, or won deal value? |
| `How are we doing?` | Asks: pipeline, billing/collections, or operations? |
| `Prepare a leadership update` | Multi-section executive summary |
| `Are there any missing or incomplete values in the data?` | Data quality report for both boards |

---

## 10. Data Resilience

The normalization layer (`normalize.py`) handles all data issues before any calculation:

| Issue | How handled |
|---|---|
| Missing dates | `None` — never substituted with today's date |
| Missing numbers | `None` — never converted to 0 (`None ≠ 0` throughout) |
| `BIlled` typo in Billing Status | Corrected to `Billed` (3 occurrences) |
| `Billed- Visit N` invoice status | Mapped to `Partially Billed (per-visit)` |
| Quantities with embedded units (`5360 HA`) | Split into magnitude + unit; never summed across units |
| `Executed until current month` | Treated as ACTIVE (recurring contract), not Completed |
| 4 fully-empty Work Order columns | Not imported; documented in Decision Log |
| 2 junk rows in Deals (embedded headers) | Removed before import |

Every answer that is affected by missing data includes an explicit data-quality caveat.

---

## 11. Cross-Board Analysis

The two boards share a sector taxonomy, enabling reliable sector-level cross-board analysis.

**Reliable joins:**
- **Sector level** — same values on both boards (Mining, Renewables, Railways, etc.)
- **Owner/BD level** — same `OWNER_00x` masking scheme on both boards

**Not supported:**
- Customer-level join — `COMPANY0xx` (Deals) vs `WOCOMPANY_0xx` (Work Orders) are different masking schemes with no verified mapping. The agent states this clearly rather than fabricating a join.

---

## 12. Query Planning

The parser extracts these dimensions from any question:

| Dimension | Examples |
|---|---|
| **Intent** | pipeline, billing, collections, receivables, ops, cross-board, quality, leadership |
| **Dataset** | deals, work_orders, both |
| **Sector** | Mining, Renewables, Railways (plus aliases: "energy" → Renewables) |
| **Period** | this quarter, last quarter, this month, last month |
| **Groupby** | by sector, by stage, by owner, by customer |
| **Status** | open, won, dead, on hold / completed, ongoing, not started |

**Clarification is triggered when:**
- "What's our revenue?" → asks: billed value, collected amount, or won deal value?
- "How are we doing?" → asks: pipeline, billing/collections, or operations?
- "Which BD owner has the most?" → asks: pipeline value, billed value, or win rate?

---

## 13. Testing

```bash
# Unit tests (no Monday.com required)
python tests/test_calculations.py   # 19 normalization + calculation tests
python tests/test_parser.py         # 36 NLP parser tests

# Integration tests (requires .env with valid token)
python scripts/test_monday_integration.py   # 39 live Monday.com tests
python scripts/validate_scenarios.py       # 77 assignment scenario checks
```

All 181 tests/checks pass against the live boards.

---

## 14. Deployment

**Streamlit Community Cloud (recommended):**

1. Fork or push this repo to GitHub
2. Go to https://share.streamlit.io → New app
3. Set repository, branch `main`, main file `app.py`
4. Under Advanced → Secrets, add:
   ```toml
   MONDAY_API_TOKEN = "your_token_here"
   DEALS_BOARD_ID = "5030966266"
   WORK_ORDERS_BOARD_ID = "5030966343"
   ```
5. Deploy — public URL in ~2 minutes

Free-tier apps may have a 20–30 second cold-start delay on first load.

---

## 15. Limitations

| Limitation | Reason |
|---|---|
| No trend analysis | Boards store cumulative totals, not time-series snapshots |
| No customer cross-board join | Incompatible customer ID schemes on the two boards |
| Pipeline figures understated | 52% of deals have no recorded deal value; every answer says so |
| Less flexible than an LLM | Deterministic parser may not handle highly idiomatic phrasing |
| Receivables aging not available | No invoice-date field on the Work Orders board |

---

## 16. Future Improvements

- Monthly snapshots to enable genuine trend analysis
- Customer ID mapping to support customer-level cross-board queries
- Optional LLM backend at the parser/responder layer (architecture already supports this)
- Automated mock-server tests for the retrieval layer

---

## 17. AI Tools Used

- **Kiro AI** — coding assistant used to scaffold and build this project
- **No LLM API is called at runtime** — the agent is fully deterministic
