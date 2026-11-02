"""
Fill the PTF column for vendors that do not publish PTF numbers in a grid.

Reads data/ptf_sources.csv (vendor, product_contains, zos, ptf_text, source_url, verified_on) and writes
ptf_text into data/*_compat.csv, but ONLY into cells that are still a placeholder ("Verify", "Not stated ...").
Cells that already hold real data (Yes - ..., No, N/A, Check ..., Not found publicly ...) are never changed,
so the tool is safe to run again at any time.

    python tools/apply_ptf_sources.py --dry-run
    python tools/apply_ptf_sources.py

To add a vendor's FIXCAT or a PTF you found, add a line to data/ptf_sources.csv and run the tool.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from compatibility_db import VER, ptf_state  # noqa: E402


def load_sources(path: str) -> pd.DataFrame:
    s = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in ("vendor", "product_contains", "zos", "ptf_text", "source_url", "verified_on"):
        if c not in s.columns:
            raise SystemExit(f"{path} is missing the column '{c}'")
    return s


def pick(sources: pd.DataFrame, vendor: str, product: str, zos: str):
    """Most specific source line for this row: product match beats a vendor-wide line."""
    s = sources[(sources["vendor"].str.lower() == vendor.lower()) & (sources["zos"] == zos)]
    best, best_len = None, -1
    for _, r in s.iterrows():
        key = r["product_contains"].strip().lower()
        if key and key not in product.lower():
            continue
        if len(key) > best_len:
            best, best_len = r, len(key)
    return best


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    sources = load_sources(os.path.join(a.data_dir, "ptf_sources.csv"))
    files = sorted(glob.glob(os.path.join(a.data_dir, "*_compat.csv")))
    changed = 0
    for f in files:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        dirty = False
        for i, r in df.iterrows():
            for zos, (_, pcol, _, _) in VER.items():
                if ptf_state(r[pcol]) != "unknown":
                    continue                                   # real data: never overwrite
                src = pick(sources, r["vendor"], r["product"], zos)
                if src is None or src["ptf_text"] == r[pcol]:
                    continue
                df.at[i, pcol] = src["ptf_text"]
                note = f"PTF info z/OS {zos}: {src['source_url']} (checked {src['verified_on']})."
                if src["source_url"] not in df.at[i, "comments"]:
                    df.at[i, "comments"] = (df.at[i, "comments"] + " " + note).strip()
                changed += 1
                dirty = True
                print(f"{os.path.basename(f)}: {r['product']} {r['vrm']} [z/OS {zos}] -> {src['ptf_text'][:70]}")
        if dirty and not a.dry_run:
            df.to_csv(f, index=False, lineterminator="\r\n")
    print(f"\n{changed} cell(s) {'would be ' if a.dry_run else ''}filled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
