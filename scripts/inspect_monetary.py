"""
Inspect all monetary columns in the Work Orders board.
Shows: non-null counts, totals, min/max, and sample values.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from tools.retrieval import get_work_orders

r = get_work_orders()
records = r["records"]
print(f"Total Work Order records: {len(records)}")
print()

# All monetary fields with their Monday.com column names
monetary_fields = {
    "amount_excl_gst":  "Amount Excl GST          (contract value, excl. GST)",
    "amount_incl_gst":  "Amount Incl GST          (contract value, incl. GST)",
    "billed_excl_gst":  "Billed Value Excl GST    (invoiced so far, excl. GST)",
    "billed_incl_gst":  "Billed Value Incl GST    (invoiced so far, incl. GST)",
    "collected":        "Collected Amount Incl GST (cash received)",
    "to_bill_excl":     "Amount to be Billed Excl GST (remaining to invoice)",
    "to_bill_incl":     "Amount to be Billed Incl GST (remaining to invoice)",
    "receivable":       "Amount Receivable        (billed but not yet collected)",
}

print(f"{'Field':<20}  {'Non-null':>9}  {'Null':>6}  {'Total (INR)':>18}  {'Max (INR)':>15}  Description")
print("-" * 130)

for field, desc in monetary_fields.items():
    vals = [rec[field] for rec in records if rec.get(field) is not None]
    nulls = len(records) - len(vals)
    total = sum(vals)
    mx = max(vals) if vals else 0
    print(f"{field:<20}  {len(vals):>9}  {nulls:>6}  {total:>18,.0f}  {mx:>15,.0f}  {desc}")

print()
print("=" * 80)
print("SAMPLE: First 8 records — all monetary fields")
print("=" * 80)
for i, rec in enumerate(records[:8]):
    print(f"\n[{i}] Deal: {rec['deal_name']}  |  Sector: {rec['sector']}  |  Status: {rec['execution_status']}")
    for field in monetary_fields:
        v = rec.get(field)
        print(f"     {field:<20}: {v}")

print()
print("=" * 80)
print("RELATIONSHIP CHECK: amount_incl_gst vs (billed_incl_gst + to_bill_incl)")
print("=" * 80)
matches = 0
mismatches = 0
both_present = 0
for rec in records:
    a = rec.get("amount_incl_gst")
    b = rec.get("billed_incl_gst")
    tb = rec.get("to_bill_incl")
    if a is not None and b is not None and tb is not None:
        both_present += 1
        diff = abs(a - (b + tb))
        if diff < 1:   # within ₹1 rounding
            matches += 1
        else:
            mismatches += 1
            if mismatches <= 3:
                print(f"  Mismatch: amount={a:,.0f}  billed={b:,.0f}  to_bill={tb:,.0f}  sum={b+tb:,.0f}  diff={diff:,.0f}")

print(f"Records with all three present: {both_present}")
print(f"  amount_incl_gst == billed + to_bill: {matches} matches, {mismatches} mismatches")

print()
print("=" * 80)
print("RELATIONSHIP CHECK: billed_incl_gst vs (collected + receivable)")
print("=" * 80)
matches2 = 0
mismatches2 = 0
both_present2 = 0
for rec in records:
    b = rec.get("billed_incl_gst")
    c = rec.get("collected")
    rv = rec.get("receivable")
    if b is not None and c is not None and rv is not None:
        both_present2 += 1
        diff = abs(b - (c + rv))
        if diff < 1:
            matches2 += 1
        else:
            mismatches2 += 1
            if mismatches2 <= 3:
                print(f"  Mismatch: billed={b:,.0f}  collected={c:,.0f}  receivable={rv:,.0f}  sum={c+rv:,.0f}  diff={diff:,.0f}")

print(f"Records with all three present: {both_present2}")
print(f"  billed_incl_gst == collected + receivable: {matches2} matches, {mismatches2} mismatches")

print()
print("=" * 80)
print("WHICH COLUMN IS 'WORK ORDER VALUE'?")
print("=" * 80)
total_contract = sum(r["amount_incl_gst"] for r in records if r.get("amount_incl_gst") is not None)
total_billed   = sum(r["billed_incl_gst"] for r in records if r.get("billed_incl_gst") is not None)
total_collected = sum(r["collected"] for r in records if r.get("collected") is not None)
total_receivable = sum(r["receivable"] for r in records if r.get("receivable") is not None)
total_to_bill  = sum(r["to_bill_incl"] for r in records if r.get("to_bill_incl") is not None)
print(f"  Contract value  (Amount Incl GST):          INR {total_contract:>18,.0f}")
print(f"  Billed so far   (Billed Value Incl GST):    INR {total_billed:>18,.0f}")
print(f"  Collected       (Collected Amount Incl GST):INR {total_collected:>18,.0f}")
print(f"  Still to bill   (Amount to be Billed Incl): INR {total_to_bill:>18,.0f}")
print(f"  Receivable      (Amount Receivable):         INR {total_receivable:>18,.0f}")
print()
print(f"  billed + to_bill  = INR {total_billed + total_to_bill:>18,.0f}  (should equal contract value)")
print(f"  collected + recv  = INR {total_collected + total_receivable:>18,.0f}  (should equal billed)")
