"""
Live trace of the three specific queries.
Shows: parsed intent, query plan, boards accessed, tools called, actual result.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from agent.parser import parse_query
from agent.planner import execute_plan
from agent.responder import generate_response
from agent.loop import run_agent

QUERIES = [
    "Which customers have the highest receivables?",
    "Which sectors have both high pipeline and high work order value?",
    "Are there any missing or incomplete values in the data?",
]

def trace(query):
    print(f"\n{'='*70}")
    print(f"QUERY: {query}")
    print('='*70)

    # Step 1: Parse
    parsed = parse_query(query)
    print(f"\n1. PARSED INTENT")
    print(f"   intent   : {parsed.intent}")
    print(f"   dataset  : {parsed.dataset}")
    print(f"   metric   : {parsed.metric!r}")
    print(f"   sector   : {parsed.sector}")
    print(f"   groupby  : {parsed.groupby}")
    print(f"   ambiguous: {parsed.ambiguous}")
    if parsed.ambiguous:
        print(f"   clarify  : {parsed.clarify_message}")

    if parsed.ambiguous:
        print("\n2. QUERY PLAN: N/A (returning clarification)")
        print(f"\n5. ACTUAL RESULT:\n{parsed.clarify_message}")
        return

    # Step 2: Plan
    from agent.planner import _make_plan
    plan = _make_plan(parsed)
    print(f"\n2. QUERY PLAN")
    for k, v in plan.items():
        if v is not None and v != "" and v != []:
            print(f"   {k}: {v}")

    # Step 3: Execute with tool tracing
    print(f"\n3. BOARDS ACCESSED + TOOLS CALLED")
    import agent.tool_dispatcher as td
    original_dispatch = td.dispatch_tool
    calls_log = []

    def tracing_dispatch(tool_name, args):
        result = original_dispatch(tool_name, args)
        board = "?"
        if "deals" in tool_name.lower() or tool_name in ("calculate_pipeline", "calculate_revenue"):
            if args.get("basis") in ("billed", "collected"):
                board = "Work Orders"
            elif args.get("basis") == "deal_value":
                board = "Deals"
            elif "deal" in tool_name:
                board = "Deals"
            else:
                board = "Deals or Work Orders"
        elif "work" in tool_name.lower() or "operational" in tool_name.lower():
            board = "Work Orders"
        elif "cross" in tool_name.lower() or "sector_performance" in tool_name.lower():
            board = "Both (Deals + Work Orders)"
        elif "quality" in tool_name.lower():
            board = "Both (Deals + Work Orders)"
        else:
            board = "see tool"

        # Get record count from result
        count_info = ""
        if isinstance(result, dict):
            dq = result.get("data_quality", {})
            rc = dq.get("records_retrieved_from_monday") or dq.get("records_after_filters")
            if rc:
                count_info = f" → {rc} records"
            if "error" in result:
                count_info = f" → ERROR: {result['error']}"

        calls_log.append((tool_name, args, board, count_info))
        print(f"   tool: {tool_name}({json.dumps({k:v for k,v in args.items() if v}, default=str)[:80]})")
        print(f"         board: {board}{count_info}")
        return result

    td.dispatch_tool = tracing_dispatch

    try:
        plan_result = execute_plan(parsed)
        data = plan_result.get("data", {})
        exec_error = plan_result.get("error")

        if exec_error:
            print(f"\n4. EXECUTION ERROR: {exec_error}")
            return

        # Step 4: Generate response
        answer = generate_response(parsed, plan, data)

        print(f"\n4. ACTUAL RESULT (full answer):")
        print("-" * 60)
        print(answer)
        print("-" * 60)

    finally:
        td.dispatch_tool = original_dispatch

for q in QUERIES:
    trace(q)

print(f"\n{'='*70}")
print("TRACE COMPLETE")
print('='*70)
