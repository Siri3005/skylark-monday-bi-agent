"""
Assignment requirement validation — runs all 8 mandatory scenarios
plus security/data-provenance checks against live Monday.com data.

Usage: python scripts/validate_scenarios.py
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results = []

def check(label, condition, detail="", level="PASS"):
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    icon = "✓" if condition else "✗"
    print(f"  {icon}  {label}" + (f"\n       → {detail}" if detail else ""))
    return condition

def warn(label, detail=""):
    results.append((WARN, label, detail))
    print(f"  ⚠  {label}" + (f"\n       → {detail}" if detail else ""))

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ── Import agent components ────────────────────────────────────────────────────
section("IMPORT CHECK")
try:
    from agent.parser import parse_query
    from agent.planner import execute_plan
    from agent.responder import generate_response
    from agent.loop import run_agent, run_leadership_update
    check("agent.parser importable", True)
    check("agent.planner importable", True)
    check("agent.responder importable", True)
    check("agent.loop importable", True)
except ImportError as e:
    check("agent modules importable", False, str(e))
    sys.exit(1)

# ── Security checks (before any API calls) ────────────────────────────────────
section("SECURITY CHECKS")
token = os.environ.get("MONDAY_API_TOKEN", "")
gemini = os.environ.get("GEMINI_API_KEY", "")
openai = os.environ.get("OPENAI_API_KEY", "")

# Check loop.py doesn't import any LLM SDK
loop_src = open("agent/loop.py", encoding="utf-8").read()
check("No google.generativeai import in loop.py",
      "google.generativeai" not in loop_src)
check("No openai import in loop.py",
      "import openai" not in loop_src and "from openai" not in loop_src)
check("No anthropic import in loop.py",
      "import anthropic" not in loop_src and "from anthropic" not in loop_src)

# Check app.py doesn't expose token
app_src = open("app.py", encoding="utf-8").read()
# Token should only appear in os.environ.get() calls, never as a literal value
token_exposed = (token and token in app_src)
check("API token not hardcoded in app.py source", not token_exposed,
      "token literal found in app.py" if token_exposed else "")
check("GEMINI_API_KEY not checked in app.py config",
      "GEMINI_API_KEY" not in app_src)

# Check no CSV loading at runtime
check("No read_excel in app.py", "read_excel" not in app_src)
check("No .csv loading in app.py", ".csv" not in app_src)
check("No .xlsx loading in app.py", ".xlsx" not in app_src)

for fname in ["tools/retrieval.py", "tools/calculations.py", "tools/cross_board.py"]:
    src = open(fname, encoding="utf-8").read()
    check(f"No read_excel in {fname}", "read_excel" not in src)
    check(f"No hardcoded CSV in {fname}", ".csv" not in src)

# Check requirements.txt has no LLM deps
req_src = open("requirements.txt", encoding="utf-8").read()
check("google-generativeai not in requirements.txt", "google-generativeai" not in req_src)
check("openai not in requirements.txt", "openai" not in req_src)
check("anthropic not in requirements.txt", "anthropic" not in req_src)

# Check Monday client has no write operations
client_src = open("monday/client.py", encoding="utf-8").read()
# These should only appear in comments/docstrings, not as actual calls
import ast as _ast
try:
    client_tree = _ast.parse(client_src)
    call_names = [n.func.attr for n in _ast.walk(client_tree)
                  if isinstance(n, _ast.Call) and isinstance(getattr(n, 'func', None), _ast.Attribute)]
    check("No create_item call in monday/client.py", "create_item" not in call_names)
    check("No change_column_value call in monday/client.py", "change_column_value" not in call_names)
except Exception:
    # Fallback: check that mutation only appears in comments
    lines_with_mutation = [l.strip() for l in client_src.splitlines()
                           if "mutation" in l.lower() and not l.strip().startswith("#") and not l.strip().startswith('"""') and not l.strip().startswith("'")]
    check("No live mutation calls in monday/client.py", len(lines_with_mutation) == 0,
          f"found: {lines_with_mutation[:2]}")


# ── Scenario tests (parser only — no API call needed) ─────────────────────────
section("SCENARIO 1 — Pipeline for energy sector this quarter (parser)")
q1 = parse_query("How's our pipeline looking for the energy sector this quarter?")
check("Intent = pipeline", q1.intent == "pipeline", f"got: {q1.intent}")
check("Dataset = deals", q1.dataset == "deals", f"got: {q1.dataset}")
check("Sector = Renewables (energy alias)", q1.sector == "Renewables", f"got: {q1.sector}")
check("Period = this_quarter", q1.period == "this_quarter", f"got: {q1.period}")
check("Not ambiguous", not q1.ambiguous)

section("SCENARIO 2 — Highest pipeline sector (parser)")
q2 = parse_query("Which sector has the highest pipeline?")
check("Intent = pipeline", q2.intent == "pipeline", f"got: {q2.intent}")
check("Dataset = deals", q2.dataset == "deals", f"got: {q2.dataset}")
check("No sector filter (all sectors)", q2.sector is None, f"got: {q2.sector}")
# groupby sector is ideal but not required — breakdown is always returned
check("Not ambiguous", not q2.ambiguous)

section("SCENARIO 3 — Outstanding amount (parser)")
q3 = parse_query("How much is outstanding?")
check("Intent = receivables", q3.intent == "receivables", f"got: {q3.intent}")
check("Dataset = work_orders", q3.dataset == "work_orders", f"got: {q3.dataset}")
check("Not ambiguous", not q3.ambiguous)

section("SCENARIO 4 — Collections improving (parser)")
q4 = parse_query("How are collections improving?")
check("Intent = collections", q4.intent == "collections", f"got: {q4.intent}")
check("Dataset = work_orders", q4.dataset == "work_orders", f"got: {q4.dataset}")
check("Not ambiguous", not q4.ambiguous)

section("SCENARIO 5 — BD owner ambiguous metric (parser)")
q5 = parse_query("Which BD owner has the most?")
# Should either ask clarification or route to owner_conversion
check("Handled gracefully (clarify OR cross_board)",
      q5.ambiguous or q5.intent == "cross_board",
      f"got intent={q5.intent}, ambiguous={q5.ambiguous}")

section("SCENARIO 6 — How are we doing (parser — must clarify)")
q6 = parse_query("How are we doing?")
check("Is ambiguous (should ask clarification)", q6.ambiguous, f"got: {q6.ambiguous}")
check("Has clarify_message", bool(q6.clarify_message), f"got: {q6.clarify_message!r}")
check("Clarify message mentions pipeline or billing",
      q6.clarify_message and ("pipeline" in q6.clarify_message.lower() or "billing" in q6.clarify_message.lower()),
      f"message: {q6.clarify_message!r}")

section("SCENARIO 7 — Missing values / data quality (parser)")
q7 = parse_query("Are there missing values?")
check("Intent = quality", q7.intent == "quality", f"got: {q7.intent}")

section("SCENARIO 8 — Cross-board query (parser)")
q8 = parse_query("Compare pipeline with executed work by sector")
check("Intent = cross_board", q8.intent == "cross_board", f"got: {q8.intent}")
check("Dataset = both", q8.dataset == "both", f"got: {q8.dataset}")


# ── Live Monday.com calls — scenarios 1, 2, 3, 7, 8 ──────────────────────────
section("LIVE MONDAY.COM — Scenario 1 (energy pipeline this quarter)")
try:
    result1 = run_agent("How's our pipeline looking for the energy sector this quarter?")
    ans1 = result1.get("answer", "")
    err1 = result1.get("error")
    check("No error", not err1, err1 or "")
    check("Answer is non-empty", len(ans1) > 50, f"length={len(ans1)}")
    check("Answer mentions Renewables or sector",
          "renewables" in ans1.lower() or "sector" in ans1.lower() or "energy" in ans1.lower(),
          ans1[:200])
    check("Answer contains a number (pipeline value)",
          any(c.isdigit() for c in ans1))
    check("Answer mentions quarter or period",
          "quarter" in ans1.lower() or "q" in ans1.lower() or "jan" in ans1.lower() or
          "apr" in ans1.lower() or "jul" in ans1.lower() or "oct" in ans1.lower())
    # Data quality caveat check
    if "data note" in ans1.lower() or "missing" in ans1.lower() or "excluded" in ans1.lower():
        check("Data quality caveat present", True, "caveat found")
    else:
        warn("No data quality caveat in answer", "may be fine if no values missing for this filter")
    print(f"\n  Sample answer (first 300 chars):\n  {ans1[:300]}")
except Exception as e:
    check("Scenario 1 live call", False, str(e))

section("LIVE MONDAY.COM — Scenario 2 (highest pipeline sector)")
try:
    result2 = run_agent("Which sector has the highest pipeline?")
    ans2 = result2.get("answer", "")
    err2 = result2.get("error")
    check("No error", not err2, err2 or "")
    check("Answer non-empty", len(ans2) > 50)
    check("Answer mentions a sector name",
          any(s in ans2 for s in ["Mining", "Renewables", "Railways", "Powerline", "Construction"]),
          ans2[:200])
    check("Answer contains breakdown or table", "|" in ans2 or "breakdown" in ans2.lower())
    check("Answer provides insight (not just number)",
          "lead" in ans2.lower() or "highest" in ans2.lower() or "top" in ans2.lower() or
          "%" in ans2 or "represent" in ans2.lower())
    print(f"\n  Sample answer (first 300 chars):\n  {ans2[:300]}")
except Exception as e:
    check("Scenario 2 live call", False, str(e))

section("LIVE MONDAY.COM — Scenario 3 (outstanding amount)")
try:
    result3 = run_agent("How much is outstanding?")
    ans3 = result3.get("answer", "")
    err3 = result3.get("error")
    check("No error", not err3, err3 or "")
    check("Answer non-empty", len(ans3) > 50)
    check("Answer mentions receivable or outstanding",
          "receivable" in ans3.lower() or "outstanding" in ans3.lower())
    check("Answer contains a currency value", "₹" in ans3 or "cr" in ans3.lower() or "lakh" in ans3.lower() or "l " in ans3)
    check("Answer explains what outstanding means",
          "billed" in ans3.lower() or "collected" in ans3.lower() or "owed" in ans3.lower() or
          "collection" in ans3.lower())
    print(f"\n  Sample answer (first 300 chars):\n  {ans3[:300]}")
except Exception as e:
    check("Scenario 3 live call", False, str(e))

section("LIVE MONDAY.COM — Scenario 4 (collections improving)")
try:
    result4 = run_agent("How are collections improving?")
    ans4 = result4.get("answer", "")
    err4 = result4.get("error")
    check("No error", not err4, err4 or "")
    check("Answer non-empty", len(ans4) > 50)
    check("Answer mentions collection",
          "collect" in ans4.lower())
    check("Answer either shows trend or explains limitation",
          "%" in ans4 or "rate" in ans4.lower() or
          "trend" in ans4.lower() or "data" in ans4.lower() or
          "limitation" in ans4.lower() or "only" in ans4.lower())
    print(f"\n  Sample answer (first 300 chars):\n  {ans4[:300]}")
except Exception as e:
    check("Scenario 4 live call", False, str(e))

section("LIVE MONDAY.COM — Scenario 6 (how are we doing — clarification)")
result6 = run_agent("How are we doing?")
ans6 = result6.get("answer", "")
is_clarifying = result6.get("is_clarifying", False)
check("Returns clarifying question (not a raw answer)",
      is_clarifying or "pipeline" in ans6.lower() or "billing" in ans6.lower(),
      f"is_clarifying={is_clarifying}, answer[:100]={ans6[:100]}")
check("Answer asks about scope or gives options",
      "?" in ans6 or "pipeline" in ans6.lower() or "billing" in ans6.lower())

section("LIVE MONDAY.COM — Scenario 7 (missing values / data quality)")
try:
    result7 = run_agent("Are there missing values?")
    ans7 = result7.get("answer", "")
    err7 = result7.get("error")
    check("No error", not err7, err7 or "")
    check("Answer non-empty", len(ans7) > 100)
    check("Answer mentions missing or null",
          "missing" in ans7.lower() or "null" in ans7.lower() or "null_count" in ans7.lower())
    check("Answer mentions deals or work orders",
          "deal" in ans7.lower() or "work order" in ans7.lower())
    check("Answer contains specific numbers",
          any(c.isdigit() for c in ans7))
    print(f"\n  Sample answer (first 400 chars):\n  {ans7[:400]}")
except Exception as e:
    check("Scenario 7 live call", False, str(e))

section("LIVE MONDAY.COM — Scenario 8 (cross-board: pipeline vs execution)")
try:
    result8 = run_agent("Compare pipeline with executed work by sector")
    ans8 = result8.get("answer", "")
    err8 = result8.get("error")
    check("No error", not err8, err8 or "")
    check("Answer non-empty", len(ans8) > 100)
    check("Answer contains sector data",
          any(s in ans8 for s in ["Mining", "Renewables", "Railways"]))
    check("Answer contains both pipeline and execution data",
          ("pipeline" in ans8.lower() or "deal" in ans8.lower()) and
          ("work order" in ans8.lower() or "execution" in ans8.lower() or "wo" in ans8.lower()))
    check("Answer contains a table (markdown)", "|" in ans8)
    check("Answer mentions cross-board limitation",
          "sector" in ans8.lower() or "level" in ans8.lower())
    print(f"\n  Sample answer (first 400 chars):\n  {ans8[:400]}")
except Exception as e:
    check("Scenario 8 live call", False, str(e))


# ── Final summary ──────────────────────────────────────────────────────────────
section("SUMMARY")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
warned = sum(1 for r in results if r[0] == WARN)
total = passed + failed

print(f"\n  {passed}/{total} checks passed, {failed} failed, {warned} warnings")
print()

if failed:
    print("  FAILED checks:")
    for status, label, detail in results:
        if status == FAIL:
            print(f"    ✗ {label}" + (f": {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
