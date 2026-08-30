"""
Deterministic natural-language query parser.
No external LLM. No API calls. Pure Python pattern matching.

Extracts from free-text questions:
  - intent        : what the user wants
  - dataset       : deals | work_orders | both
  - metric        : pipeline | revenue | billed | collected | receivable | count | ops | quality
  - sector        : Mining | Renewables | Railways | ...
  - owner         : OWNER_001 ... OWNER_007
  - period        : this_quarter | last_quarter | this_month | last_month | this_year
  - groupby       : sector | stage | owner | status | customer
  - status_filter : Open | Won | Dead | On Hold | Completed | Ongoing | ...
  - ambiguous     : True if clarification is needed
  - clarify_on    : which dimension is ambiguous
"""
from __future__ import annotations
import re
from datetime import date, datetime
from typing import Optional


# ── Synonym dictionaries ───────────────────────────────────────────────────────

PIPELINE_WORDS = {
    "pipeline", "sales pipeline", "opportunity", "opportunities",
    "deal value", "deal values", "funnel", "prospect", "prospects",
}

REVENUE_WORDS = {
    "revenue", "sales", "income", "earnings",
}

BILLED_WORDS = {
    "billed", "billing", "invoiced", "invoice", "invoice value",
    "billed value", "billing performance",
}

COLLECTED_WORDS = {
    "collected", "collections", "collection", "cash collected",
    "payments received", "cash received", "collections improving",
    "improving collections", "are collections",
}

RECEIVABLE_WORDS = {
    "receivable", "receivables", "outstanding amount",
    "accounts receivable", "unpaid", "dues", "pending payment",
    "money owed", "how much is outstanding", "ar priority",
    "show me ar", "show ar", "our ar",
}

# NOTE: "outstanding" alone is kept separate — it's checked after more specific
# intents so it doesn't hijack pipeline/quality/collections queries.
OUTSTANDING_STANDALONE = {"outstanding"}

WORK_ORDER_WORDS = {
    "work order", "work orders", "wo", "wos", "execution", "operations",
    "operational", "project", "projects", "on-site", "field work",
}

DEAL_WORDS = {
    "deal", "deals", "opportunity", "opportunities", "lead", "leads",
    "prospect", "prospects", "sales deal",
}

SECTOR_WORDS = {
    "sector", "sectors", "industry", "industries", "segment", "segments",
    "vertical", "verticals",
}

CUSTOMER_WORDS = {
    "customer", "customers", "client", "clients", "account", "accounts",
}

OWNER_WORDS = {
    "owner", "owners", "sales rep", "sales person", "bd", "kam",
    "account manager", "sales owner",
}

STAGE_WORDS = {
    "stage", "stages", "funnel stage", "deal stage",
}

QUALITY_WORDS = {
    "data quality", "data health", "how clean", "missing data",
    "missing values", "missing value", "null values", "null value",
    "incomplete data", "data issues", "data problems", "data gaps",
    "how complete", "data completeness",
}

LEADERSHIP_WORDS = {
    "leadership update", "board update", "executive summary",
    "management report", "prepare update", "summary report",
    "leadership report", "weekly update", "monthly update",
}

# Known sector values (from actual board data)
KNOWN_SECTORS = {
    "renewables": "Renewables",
    "renewable": "Renewables",
    "renewable energy": "Renewables",
    "mining": "Mining",
    "railways": "Railways",
    "railway": "Railways",
    "rail": "Railways",
    "powerline": "Powerline",
    "power line": "Powerline",
    "power": "Powerline",
    "construction": "Construction",
    "others": "Others",
    "dsp": "DSP",
    "tender": "Tender",
    "manufacturing": "Manufacturing",
    "security": "Security and Surveillance",
    "surveillance": "Security and Surveillance",
    "aviation": "Aviation",
    # Aliases the user might type
    "energy": "Renewables",
    "solar": "Renewables",
    "wind": "Renewables",
    "infra": "Construction",
    "infrastructure": "Construction",
}

# Time period patterns
PERIOD_PATTERNS = [
    (r"\bthis\s+quarter\b", "this_quarter"),
    (r"\bcurrent\s+quarter\b", "this_quarter"),
    (r"\bq\d\b", "this_quarter"),
    (r"\blast\s+quarter\b", "last_quarter"),
    (r"\bprevious\s+quarter\b", "last_quarter"),
    (r"\bthis\s+month\b", "this_month"),
    (r"\bcurrent\s+month\b", "this_month"),
    (r"\blast\s+month\b", "last_month"),
    (r"\bthis\s+year\b", "this_year"),
    (r"\bcurrent\s+year\b", "this_year"),
    (r"\blast\s+year\b", "last_year"),
    (r"\brecently\b", "this_quarter"),
    (r"\brecent\b", "this_quarter"),
    (r"\bsoon\b", "this_quarter"),
    (r"\bupcoming\b", "this_quarter"),
]

# Status synonyms
DEAL_STATUS_SYNONYMS = {
    "open": "Open",
    "active deal": "Open",
    "active deals": "Open",
    "live deal": "Open",
    "live deals": "Open",
    "in progress": "Open",
    "won": "Won",
    "closed won": "Won",
    "closed": "Won",
    "dead": "Dead",
    "lost": "Dead",
    "closed lost": "Dead",
    "on hold": "On Hold",
    "paused": "On Hold",
}

WO_STATUS_SYNONYMS = {
    "completed": "Completed",
    "done": "Completed",
    "finished": "Completed",
    "ongoing": "Ongoing",
    "in progress": "Ongoing",
    "not started": "Not Started",
    "pending": "Not Started",
    "stuck": "Pause / struck",
    "recurring": "Executed until current month",
}

# ── Clarification triggers ────────────────────────────────────────────────────
# These exact patterns trigger a clarifying question.
# They are checked FIRST, before any other intent mapping.
ALWAYS_CLARIFY_PATTERNS = [
    # "how are we doing" — intentionally vague overview
    (r"^how\s+are\s+we\s+doing[\?]?$",
     "metric",
     "Would you like me to focus on **sales pipeline**, **billing and collections**, or **work-order execution**?"),

    # bare "how are we doing" with no qualifier
    (r"^how\s+(are|is)\s+(we|the\s+business|things?)\s+doing[\?]?$",
     "metric",
     "Would you like me to focus on **sales pipeline**, **billing and collections**, or **work-order execution**?"),

    # "show performance" with no qualifier
    (r"^(show|display|give me|what('s| is))\s+(our\s+)?(performance|results|metrics|numbers|stats)[\?]?$",
     "metric",
     "Would you like **pipeline performance**, **billing performance**, or **operational performance**?"),
]


# ── Main parser ────────────────────────────────────────────────────────────────

class ParsedQuery:
    """Result of parsing a user query."""
    def __init__(self):
        self.raw: str = ""
        self.intent: str = "unknown"
        self.dataset: str = "both"
        self.metric: str = ""
        self.sector: Optional[str] = None
        self.owner: Optional[str] = None
        self.period: Optional[str] = None
        self.groupby: Optional[str] = None
        self.deal_status: Optional[list] = None
        self.wo_status: Optional[str] = None
        self.ambiguous: bool = False
        self.clarify_on: Optional[str] = None
        self.clarify_message: Optional[str] = None
        self.limit: Optional[int] = None
        self.sort: str = "desc"

    def __repr__(self):
        return (f"ParsedQuery(intent={self.intent!r}, dataset={self.dataset!r}, "
                f"metric={self.metric!r}, sector={self.sector!r}, period={self.period!r}, "
                f"groupby={self.groupby!r}, ambiguous={self.ambiguous})")


def parse_query(text: str) -> ParsedQuery:
    """
    Parse a natural-language BI question into a structured ParsedQuery.
    Deterministic — no external API calls.

    Priority order (highest → lowest):
      1. Explicit clarification triggers (vague questions that must not be guessed)
      2. Leadership update
      3. Data quality
      4. Entity extraction (sector, period, groupby, status)
      5. Specific intents: at-risk, upcoming, count, cross-board
      6. Financial intents: receivables > collections > billing > revenue > pipeline
      7. Operational: work orders, deals
      8. Sector-only catch-all → cross-board
      9. Generic summary
      10. Mark ambiguous
    """
    q = ParsedQuery()
    q.raw = text
    low = text.lower().strip()

    # ── Step 1: Always-clarify patterns (must come FIRST) ─────────────────────
    for pattern, dim, message in ALWAYS_CLARIFY_PATTERNS:
        if re.search(pattern, low):
            q.intent = "clarify"
            q.ambiguous = True
            q.clarify_on = dim
            q.clarify_message = message
            return q

    # ── Step 2: Leadership update ─────────────────────────────────────────────
    if any(w in low for w in LEADERSHIP_WORDS):
        q.intent = "leadership"
        q.dataset = "both"
        return q

    # ── Step 3: Data quality ──────────────────────────────────────────────────
    # Check this early — "missing values" etc. must not be mistaken for receivables
    if any(w in low for w in QUALITY_WORDS):
        q.intent = "quality"
        q.dataset = "both"
        if "deal" in low:
            q.dataset = "deals"
        elif "work order" in low or re.search(r'\bwo\b', low):
            q.dataset = "work_orders"
        return q

    # ── Step 4: Extract sector ────────────────────────────────────────────────
    # Use longest-match first (sort by length descending) to avoid partial matches
    for key in sorted(KNOWN_SECTORS.keys(), key=len, reverse=True):
        if re.search(r'\b' + re.escape(key) + r'\b', low):
            q.sector = KNOWN_SECTORS[key]
            break

    # ── Step 5: Extract time period ───────────────────────────────────────────
    for pattern, period in PERIOD_PATTERNS:
        if re.search(pattern, low):
            q.period = period
            break

    # ── Step 6: Extract groupby ───────────────────────────────────────────────
    if re.search(r'\bby\s+sector\b', low) or re.search(r'\bper\s+sector\b', low):
        q.groupby = "sector"
    elif re.search(r'\bby\s+stage\b', low) or re.search(r'\bfunnel\b', low):
        q.groupby = "stage"
    elif re.search(r'\bby\s+owner\b', low) or re.search(r'\bper\s+owner\b', low) or re.search(r'\bby\s+(bd|kam)\b', low):
        q.groupby = "owner"
    elif re.search(r'\bby\s+status\b', low):
        q.groupby = "status"
    elif re.search(r'\bby\s+customer\b', low) or re.search(r'\bper\s+customer\b', low) or re.search(r'\bby\s+client\b', low):
        q.groupby = "customer"

    # ── Step 7: Extract deal status filters ──────────────────────────────────
    for phrase, status in DEAL_STATUS_SYNONYMS.items():
        if phrase in low:
            q.deal_status = [status]
            break

    # ── Step 8: Extract WO status ─────────────────────────────────────────────
    for phrase, status in WO_STATUS_SYNONYMS.items():
        if re.search(r'\b' + re.escape(phrase) + r'\b', low):
            q.wo_status = status
            break

    # ── Step 9: Detect "at risk" / "upcoming closures" ───────────────────────
    if re.search(r'\bat.?risk\b', low) or re.search(r'\boverdue\b', low):
        q.intent = "at_risk"
        q.dataset = "deals"
        return q

    if (re.search(r'\bupcoming\s+(clos|deal)\b', low) or
            re.search(r'\blikely\s+to\s+close\b', low) or
            re.search(r'\bclose\s+soon\b', low)):
        q.intent = "upcoming_closures"
        q.dataset = "deals"
        q.period = q.period or "this_quarter"
        return q

    # ── Step 10: Count questions ──────────────────────────────────────────────
    if re.search(r'\b(how many|count|total number|number of)\b', low):
        q.intent = "count"
        has_wo = any(w in low for w in WORK_ORDER_WORDS)
        has_deal = any(w in low for w in DEAL_WORDS)
        if has_wo and has_deal:
            q.dataset = "both"
        elif has_wo:
            q.dataset = "work_orders"
        elif has_deal:
            q.dataset = "deals"
        else:
            q.dataset = "both"
        return q

    # ── Step 11: Cross-board questions ────────────────────────────────────────
    cross_signals = [
        r'\bcompare\b', r'\bvs\b', r'\bversus\b', r'\bcross.board\b',
        r'\bpipeline.*execution\b', r'\bexecution.*pipeline\b',
        r'\bdeals.*work order\b', r'\bwork order.*deal\b',
        r'\bsales.*ops\b', r'\bops.*sales\b',
        r'\bwhich\s+sector.*performing\b', r'\bsector\s+performance\b',
    ]
    if any(re.search(p, low) for p in cross_signals):
        q.intent = "cross_board"
        q.dataset = "both"
        # Owner/BD conversion
        if re.search(r'\b(bd|kam)\s+(owner|person|rep)\b', low) or re.search(r'\bowner.*most\b', low) or re.search(r'\bbd.*most\b', low):
            q.metric = "owner_conversion"
        elif re.search(r'\bstrong.*pipeline.*weak\b|\bpipeline.*not.*execut\b', low):
            q.metric = "strong_sales_weak_ops"
        else:
            q.metric = "pipeline_vs_execution"
        return q

    # ── Step 12: "Which BD/owner ... most/highest" — cross-board owner ────────
    if (re.search(r'\bwhich\s+(bd|kam|owner|sales)\b', low) and
            re.search(r'\b(most|highest|best|top)\b', low)):
        q.intent = "cross_board"
        q.dataset = "both"
        q.metric = "owner_conversion"
        # If metric is ambiguous (just "most" with no qualifier), ask
        if not any(w in low for w in ["billed", "pipeline", "deal", "revenue", "work order", "wo"]):
            q.ambiguous = True
            q.clarify_on = "owner_metric"
            q.clarify_message = (
                "Would you like to know which BD owner has the most:\n"
                "- **Open pipeline value** (deals)\n"
                "- **Billed work order value**\n"
                "- **Win rate** (deals won vs total)?"
            )
        return q

    # ── Step 13: Primary intent — financial metrics ───────────────────────────
    # Order matters: most specific → least specific
    # Collections (before receivables — "are collections improving" has both)
    if any(w in low for w in COLLECTED_WORDS):
        q.intent = "collections"
        q.dataset = "work_orders"
        q.metric = "collected"
        return q

    # Receivables (explicit receivable words, not just "outstanding")
    if any(w in low for w in RECEIVABLE_WORDS) or re.search(r'\bar\b', low):
        q.intent = "receivables"
        q.dataset = "work_orders"
        q.metric = "receivable"
        return q

    # Billing
    if any(w in low for w in BILLED_WORDS):
        q.intent = "billing"
        q.dataset = "work_orders"
        q.metric = "billed"
        return q

    # Revenue (genuinely ambiguous without qualifier)
    if any(w in low for w in REVENUE_WORDS):
        q.intent = "revenue"
        q.dataset = "both"
        q.metric = "revenue"
        if "billed" in low or "invoice" in low:
            q.metric = "billed"
            q.dataset = "work_orders"
        elif "collected" in low or "cash" in low:
            q.metric = "collected"
            q.dataset = "work_orders"
        elif "deal" in low or "won" in low or "closed" in low:
            q.metric = "deal_value"
            q.dataset = "deals"
        else:
            q.ambiguous = True
            q.clarify_on = "revenue_basis"
            q.clarify_message = (
                "Do you mean **billed value** (invoiced), **collected** (cash received), "
                "or the value of **won/closed deals**? These are three different numbers in our data."
            )
        return q

    # Pipeline (check after revenue to avoid conflict)
    if any(w in low for w in PIPELINE_WORDS):
        q.intent = "pipeline"
        q.dataset = "deals"
        q.metric = "pipeline"
        if not q.deal_status:
            q.deal_status = ["Open", "On Hold"]
        return q

    # ── Step 14: "outstanding" as standalone word (receivables) ──────────────
    # Only reached if no more specific intent matched above
    if re.search(r'\boutstanding\b', low):
        q.intent = "receivables"
        q.dataset = "work_orders"
        q.metric = "receivable"
        return q

    # ── Step 15: Work orders / Operations ────────────────────────────────────
    if any(w in low for w in WORK_ORDER_WORDS):
        q.intent = "ops"
        q.dataset = "work_orders"
        q.metric = "ops"
        return q

    # ── Step 16: Deals ────────────────────────────────────────────────────────
    if any(w in low for w in DEAL_WORDS):
        q.intent = "pipeline"
        q.dataset = "deals"
        q.metric = "pipeline"
        if not q.deal_status:
            q.deal_status = ["Open", "On Hold"]
        return q

    # ── Step 17: Sector-only catch-all → cross-board ─────────────────────────
    if q.sector and q.intent == "unknown":
        q.intent = "cross_board"
        q.dataset = "both"
        q.metric = "pipeline_vs_execution"
        return q

    # ── Step 18: Generic summary ──────────────────────────────────────────────
    if re.search(r'\b(overview|summary|dashboard|status|update|report)\b', low):
        q.intent = "summary"
        q.dataset = "both"
        return q

    # ── Step 19: Mark ambiguous ───────────────────────────────────────────────
    q.ambiguous = True
    q.clarify_on = "intent"
    q.clarify_message = (
        "I'm not sure what you'd like to know. Could you ask about:\n"
        "- **Pipeline** (deal values, stages, sectors)\n"
        "- **Billing** (invoiced amounts)\n"
        "- **Collections** (cash received)\n"
        "- **Receivables** (outstanding amounts)\n"
        "- **Work orders** (execution status, operations)\n"
        "- **Cross-board** (compare pipeline vs execution)"
    )

    return q


def _today() -> date:
    return datetime.now().date()
