# Skylark Drones – Monday.com BI Agent

A conversational, founder-level business intelligence agent that queries two live Monday.com boards (Deals & Work Orders) in real time and answers natural-language questions without any external LLM API.

---

## Overview

Skylark Drones needed a way to get quick, accurate answers to business questions across Monday.com boards — without manually exporting data, running ad-hoc queries, or waiting for a data analyst.

This agent:
- Connects directly to Monday.com via GraphQL API (read-only)
- Parses natural-language founder questions deterministically
- Queries the correct board(s) dynamically at query time
- Returns contextual insights with data-quality caveats
- Asks clarifying questions when a query is genuinely ambiguous
- Runs with **no external LLM API** — no Gemini, no OpenAI, no Anthropic

---

## Architecture

```
User question (browser)
        │
        ▼
Streamlit Chat UI  (app.py)
        │
        ▼
┌─────────────────────────────────────────────┐
│            Deterministic Agent Loop         │
│                 (agent/loop.py)             │
│                                             │
│  1. Parser      (agent/parser.py)           │
│     regex + synonym dicts → ParsedQuery     │
│                                             │
│  2. Planner     (agent/planner.py)          │
│     ParsedQuery → tool execution plan       │
│                                             │
│  3. BI Tools    (tools/)                    │
│     deterministic Python calculations       │
│                                             │
│  4. Responder   (agent/responder.py)        │
│     structured data → markdown answer       │
└─────────────────────────────────────────────┘
        │
        ▼
Monday.com GraphQL Client  (monday/client.py)
  Read-only · cursor pagination · retry logic
        │
        ├── Deals board  (ID: 5030966266)
        └── Work Orders board  (ID: 5030966343)
```

**No external LLM is used.** The parser, planner, and responder are all deterministic Python. The architecture is explicitly designed so an LLM could be plugged in at the parser/responder level later — the BI tools and Monday.com integration would remain unchanged.

---

## Technology Stack

| Component | Choice | Why |
|---|---|---|
| Frontend/Backend | Streamlit (single app) | Fastest path to a hosted chat UI; one deployment surface |
| Query understanding | Deterministic NLP (regex + synonym dicts) | No API cost, auditable, predictable — LLM pluggable later |
| Monday.com access | GraphQL API v2 | Directly callable from Python, full pagination support |
| Deployment | Streamlit Community Cloud | Free, zero-config public URL |

### No external LLM API

The current implementation does not use Gemini, OpenAI, Claude, or any other external AI inference service. This means:
- No API cost or billing required
- No dependency on third-party AI availability
- Every answer is fully traceable and auditable
- Results are deterministic and reproducible

**Documented limitation:** A deterministic parser has less linguistic flexibility than a general-purpose LLM. It handles well-structured founder questions well, but may not parse highly idiomatic phrasing. The architecture supports adding an LLM backend in future without changing the BI tools or Monday.com integration.

---

## Project Structure

```
skylark-monday-bi-agent/
├── app.py                      # Streamlit chat UI entry point
├── agent/
│   ├── loop.py                 # Main agent orchestration
│   ├── parser.py               # Deterministic NLP query parser
│   ├── planner.py              # Query plan execution
│   ├── responder.py            # Structured data → conversational text
│   ├── tool_dispatcher.py      # Routes tool names to Python functions
│   └── _legacy/                # Prior Gemini-era files (archived, not used)
├── tools/
│   ├── retrieval.py            # get_deals(), get_work_orders() — live Monday calls
│   ├── calculations.py         # calculate_pipeline(), calculate_revenue(), etc.
│   ├── cross_board.py          # cross_board_metric() — sector + owner level
│   └── data_quality.py         # check_data_quality()
├── monday/
│   ├── client.py               # GraphQL client, pagination, error handling
│   └── schema.py               # Board ID constants, config
├── normalize.py                # Date/text/numeric normalization
├── tests/
│   ├── test_calculations.py    # Normalization + calculation unit tests (19 tests)
│   └── test_parser.py          # NLP parser unit tests (36 tests)
├── scripts/
│   ├── test_monday_integration.py  # Live Monday.com integration tests (39 tests)
│   ├── validate_scenarios.py       # Assignment scenario validation (77 checks)
│   └── one_time_ingest.py          # One-time: Excel → CSV for board setup
├── .env.example
├── requirements.txt
├── DECISION_LOG.md
└── README.md
```

---

## Prerequisites

- Python 3.11+
- A Monday.com account with two boards (Deals and Work Orders — already set up)
- No LLM API key required

---

## Monday.com Setup

The boards have already been created and populated:
- **Deals board** ID: `5030966266` (344 records)
- **Work Orders board** ID: `5030966343` (176 records)

To set up from scratch on a new account:
1. Run `python scripts/one_time_ingest.py` to generate `deals_clean.csv` and `work_orders_clean.csv`
2. In Monday.com: Add board → Import from Excel/CSV for each file
3. Verify item counts: Deals = 344, Work Orders = 176
4. Get your board IDs from the board URL: `monday.com/boards/<ID>`
5. Generate an API token: Avatar → Administration → API

---

## Environment Variables

Copy `.env.example` to `.env`:

```
MONDAY_API_TOKEN=your_monday_api_token_here
DEALS_BOARD_ID=5030966266
WORK_ORDERS_BOARD_ID=5030966343
```

No LLM API key is needed.

---

## Local Setup & Running

```bash
cd skylark-monday-bi-agent
pip install -r requirements.txt
cp .env.example .env
# Fill in MONDAY_API_TOKEN

python -m streamlit run app.py
```

Open http://localhost:8501

### Run all tests

```bash
# Unit tests
python tests/test_calculations.py
python tests/test_parser.py

# Live integration tests (requires .env)
python scripts/test_monday_integration.py

# Full assignment scenario validation (requires .env)
python scripts/validate_scenarios.py
```

---

## Deployment (Streamlit Community Cloud)

1. Push repo to GitHub
2. Go to https://share.streamlit.io → New app
3. Set repository, branch `main`, main file `app.py`
4. Under Advanced → Secrets, add:
   ```toml
   MONDAY_API_TOKEN = "your_token_here"
   DEALS_BOARD_ID = "5030966266"
   WORK_ORDERS_BOARD_ID = "5030966343"
   ```
5. Deploy — public URL ready in ~2 minutes

**Note:** Free-tier apps may have a 20–30 second cold-start delay on first load.

---

## Example Queries

| Question | What it does |
|---|---|
| "How many deals and work orders do we have?" | Counts both boards |
| "What's our open pipeline value?" | Pipeline total with sector breakdown |
| "Break the pipeline down by sector." | Sector-by-sector pipeline table |
| "How's our pipeline for the energy sector this quarter?" | Filtered pipeline with period |
| "Which sector has the highest pipeline?" | Ranked sector breakdown |
| "How much is outstanding?" | Receivables summary from Work Orders |
| "How are collections improving?" | Collections total + trend limitation note |
| "How many work orders are active vs completed?" | Operational status breakdown |
| "Compare pipeline and execution by sector." | Cross-board sector analysis |
| "What's our revenue?" | Triggers clarification question |
| "How are we doing?" | Triggers clarification question |
| "Prepare a leadership update." | Multi-tool executive summary |
| "Are there missing values?" | Data quality report with null counts |

---

## Query Understanding

The parser extracts these dimensions from free-text questions:

| Dimension | Examples |
|---|---|
| Intent | pipeline, billing, collections, receivables, ops, cross-board, quality, leadership |
| Dataset | deals, work_orders, both |
| Sector | Mining, Renewables, Railways (+ aliases: "energy" → Renewables) |
| Period | this quarter, last quarter, this month, last month |
| Groupby | by sector, by stage, by owner, by status |
| Deal status | open, won, dead, on hold |
| WO status | completed, ongoing, not started |

**Clarification triggers:**
- "What's our revenue?" → asks: billed, collected, or won deal value?
- "How are we doing?" → asks: pipeline, billing/collections, or operations?
- "Which BD owner has the most?" → asks: pipeline value, billed value, or win rate?

---

## Data Normalization

| Issue | How handled |
|---|---|
| Missing dates | `None` — never substituted with today |
| Missing numbers | `None` — never converted to 0 |
| `BIlled` typo | → `Billed` (3 occurrences) |
| `Billed- Visit N` invoice status | → `Partially Billed (per-visit)` |
| Quantities with embedded units (e.g. `5360 HA`) | Split into magnitude + unit — never summed across units |
| `Executed until current month` | Treated as ACTIVE (recurring contract) |
| 4 fully-empty Work Order columns | Not imported — documented |

---

## Cross-Board Analysis

**Reliable joins (used):**
- **Sector level** — same taxonomy on both boards
- **Owner/BD level** — same `OWNER_00x` masking scheme

**Not supported:**
- Customer-level join — `COMPANY0xx` (Deals) vs `WOCOMPANY_0xx` (Work Orders) are different namespaces. A join would be fabricated. The agent states this limitation explicitly.

---

## Error Handling

| Scenario | Response |
|---|---|
| Monday.com unreachable | Clear error message, no fallback to stale data |
| Auth failure | "Authentication failed — check MONDAY_API_TOKEN" |
| Board not found | "Board ID not found — check board ID configuration" |
| Empty result (valid query, no data) | Explains why (e.g., no deals in this period), not an error |
| Malformed data | Excluded from calculation, counted in data-quality report |
| Unsupported question | States what can and cannot be answered |

---

## Security

- `MONDAY_API_TOKEN` stored only in `.env` (local) or Streamlit Cloud secrets — never in source code
- Monday.com client is **read-only** — no mutation operations exist anywhere in the codebase
- `.gitignore` includes `.env`, all CSV/Excel files, `__pycache__`
- Logs record query parameters and counts — never full record data

---

## Known Limitations

1. **No trend analysis** — the boards contain cumulative totals, not time-series. "Are collections improving?" returns the total with a caveat that trends cannot be calculated.
2. **Customer-level cross-board join not supported** — different coding schemes on each board.
3. **Pipeline totals understated** — 52% of deals have no recorded value. Every pipeline answer surfaces this caveat.
4. **Deterministic parser** — less flexible than an LLM for unusual phrasing. Architecture supports LLM integration later.
5. **Close Date rarely known** — 92% of deals have no actual close date; only tentative dates are available.
6. **4 empty Work Order columns** — `Expected Billing Month`, `Actual Collection Month`, `Collection status`, `Collection Date` were 100% null and not imported.

---

## AI Tools Used

- **Coding assistant**: Kiro AI (used to scaffold and implement this project)
- **No LLM API is used at runtime** — the agent is fully deterministic
