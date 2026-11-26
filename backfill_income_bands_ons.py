#!/usr/bin/env python3
"""Add `income_bands_ons` (counts of reported incomes in the ten ONS UK Business
Counts turnover bands, lowest first) to every scope of a snapshot's aggregates.

  python backfill_income_bands_ons.py 2026-11-25 [2026-11-24 ...]

Recomputed from the snapshot's own per-borough CSVs (latestIncome of active
organisations), using the same rule as build_snapshot.py from v2026-11-26 on.
Check: the band counts must sum to the snapshot's existing income_bands total.
"""
import csv, json, sys
import build_snapshot as B

def main():
    agg = json.loads(B.AGGREGATES.read_text())
    for date in sys.argv[1:]:
        rows = []
        for name in B.BOROUGH_NAMES:
            for r in csv.DictReader(open(B.SNAP_DIR/date/(name+".csv"), encoding="utf-8")):
                r["_la"] = name; rows.append(r)
        blk = agg["snapshots"][date]
        scopes = {"Tees Valley": rows, **{n: [r for r in rows if r["_la"] == n] for n in B.BOROUGH_NAMES}}
        for scope, rs in scopes.items():
            have = [v for v in (B.income_of(r) for r in rs if str(r["active"]) in ("1","True")) if v is not None]
            c = B.ons_band_counts(have)
            assert sum(c) == sum(blk[scope]["income_bands"].values()), (date, scope, "income count mismatch")
            blk[scope]["income_bands_ons"] = c
        print(date, "Tees Valley:", blk["Tees Valley"]["income_bands_ons"])
    B.AGGREGATES.write_text(json.dumps(agg, separators=(',',':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
