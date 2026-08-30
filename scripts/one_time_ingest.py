"""
ONE-TIME data ingestion script.
Reads the raw Excel files, applies pre-import cleaning, and exports clean CSVs
for manual import into Monday.com.

THIS SCRIPT IS NOT PART OF THE DEPLOYED APP.
The deployed app never reads Excel files or calls this script.
This is only run once during board setup.

Usage:
    python scripts/one_time_ingest.py

Outputs:
    deals_clean.csv         — 344 rows (junk rows removed, duplicates documented)
    work_orders_clean.csv   — 176 rows (typo fixed, normalized status values)
"""
import sys
import os
import re
from pathlib import Path

# Add parent to path so imports work from the scripts/ dir
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas not installed. Run: pip install pandas openpyxl")
    sys.exit(1)


def load_deals(xlsx_path: str) -> pd.DataFrame:
    """
    Load Deals Excel file.
    Header is row 0 (normal). Drop junk rows, document duplicates.
    """
    print(f"Loading deals from: {xlsx_path}")
    df = pd.read_excel(xlsx_path, sheet_name=0)
    print(f"  Raw shape: {df.shape}")

    # Detect and drop junk rows (rows where Deal Status == 'Deal Status')
    junk_mask = df["Deal Status"] == "Deal Status"
    junk_count = junk_mask.sum()
    print(f"  Junk rows detected: {junk_count} (rows where every cell = column header)")
    df = df[~junk_mask].copy()

    # Count and report duplicates (keep them — don't silently delete business records)
    dup_mask = df.duplicated()
    dup_count = dup_mask.sum()
    print(f"  Exact duplicate rows: {dup_count} (kept — see Decision Log)")

    print(f"  Clean shape: {df.shape}")
    print(f"  Deal Status distribution:\n{df['Deal Status'].value_counts(dropna=False)}")
    print(f"  Sector distribution:\n{df['Sector/service'].value_counts(dropna=False)}")

    # Normalize date columns for CSV export
    for col in ["Close Date (A)", "Tentative Close Date", "Created Date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
        df[col] = df[col].dt.strftime("%Y-%m-%d")

    return df


def load_work_orders(xlsx_path: str) -> pd.DataFrame:
    """
    Load Work Orders Excel file.
    IMPORTANT: The real header is row 2 (index 1) — row 1 is blank.
    Detect programmatically rather than hardcoding the skip.
    """
    print(f"\nLoading work orders from: {xlsx_path}")

    # Detect header row: find first fully non-null row
    raw = pd.read_excel(xlsx_path, sheet_name=0, header=None)
    header_row = None
    for i, row in raw.iterrows():
        if row.notna().sum() > raw.shape[1] * 0.5:
            header_row = i
            break

    print(f"  Detected header row: {header_row} (expected 1)")
    df = pd.read_excel(xlsx_path, sheet_name=0, header=header_row)
    print(f"  Raw shape after header correction: {df.shape}")

    # Verify column count
    expected_cols = 38
    if df.shape[1] != expected_cols:
        print(f"  WARNING: Expected {expected_cols} columns, got {df.shape[1]}")

    # Fix BIlled typo in Billing Status
    if "Billing Status" in df.columns:
        before = (df["Billing Status"] == "BIlled").sum()
        df["Billing Status"] = df["Billing Status"].str.replace("BIlled", "Billed", regex=False)
        print(f"  Fixed 'BIlled' typo: {before} occurrences corrected to 'Billed'")

    # Normalize Invoice Status: 'Billed- Visit N' → 'Partially Billed (per-visit)'
    if "Invoice Status" in df.columns:
        pattern = re.compile(r"Billed- Visit \d+")
        before = df["Invoice Status"].str.match(r"Billed- Visit \d+", na=False).sum()
        df["Invoice Status"] = df["Invoice Status"].apply(
            lambda v: "Partially Billed (per-visit)" if isinstance(v, str) and pattern.match(v) else v
        )
        print(f"  Normalized 'Billed- Visit N' → 'Partially Billed (per-visit)': {before} rows")

    # Report 100% null columns
    null_cols = [c for c in df.columns if df[c].isna().all()]
    print(f"  100% null columns ({len(null_cols)}): {null_cols}")
    print("  These will NOT be imported into Monday.com (zero information content)")

    # Normalize date columns
    date_cols = ["Data Delivery Date", "Date of PO/LOI", "Probable Start Date",
                 "Probable End Date", "Last invoice date"]
    for col in date_cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
            df[col] = df[col].dt.strftime("%Y-%m-%d")

    print(f"  Final shape: {df.shape}")
    print(f"  Execution Status distribution:\n{df['Execution Status'].value_counts(dropna=False)}")
    print(f"  Sector distribution:\n{df['Sector'].value_counts(dropna=False)}")

    return df


def main():
    # Expected paths — adjust if running from different directory
    base = Path(__file__).parent.parent.parent
    deals_path = base / "Deal funnel Data.xlsx"
    wo_path = base / "Work_Order_Tracker Data.xlsx"

    if not deals_path.exists():
        print(f"ERROR: Deals file not found at {deals_path}")
        sys.exit(1)
    if not wo_path.exists():
        print(f"ERROR: Work Orders file not found at {wo_path}")
        sys.exit(1)

    output_dir = Path(__file__).parent.parent
    deals_out = output_dir / "deals_clean.csv"
    wo_out = output_dir / "work_orders_clean.csv"

    # Process deals
    df_deals = load_deals(str(deals_path))
    df_deals.to_csv(deals_out, index=False)
    print(f"\n✓ Deals CSV saved: {deals_out} ({len(df_deals)} rows)")

    # Process work orders
    df_wo = load_work_orders(str(wo_path))
    df_wo.to_csv(wo_out, index=False)
    print(f"✓ Work Orders CSV saved: {wo_out} ({len(df_wo)} rows)")

    print("\n" + "="*60)
    print("NEXT STEPS:")
    print("1. Import deals_clean.csv into Monday.com as 'Deals' board")
    print(f"   Expected import count: 344 items")
    print("2. Import work_orders_clean.csv into Monday.com as 'Work Orders' board")
    print(f"   Expected import count: 176 items")
    print("3. After import, verify item counts via Monday.com API:")
    print("   boards(ids: [BOARD_ID]) { items_count }")
    print("4. Copy board IDs into your .env file:")
    print("   DEALS_BOARD_ID=<id>")
    print("   WORK_ORDERS_BOARD_ID=<id>")
    print("="*60)


if __name__ == "__main__":
    main()
