#!/usr/bin/env python3
"""Backfill `social_enterprise` (CICs + registered-society sub-types) into the
aggregates for snapshots taken before the runner computed it (added 2026-11-25).

  python backfill_social_enterprise.py 2026-11-25                 # from its own CSVs
  python backfill_social_enterprise.py 2026-11-24 --types-from 2026-11-25

A snapshot whose CSVs carry `organisationType` is computed directly. Older
snapshots (2026-11-24 kept only 10 columns) can borrow organisation types from a
later snapshot ONLY if the two are identical on every shared column for every
organisation (same org set, same status, segment, dates, income...); otherwise
the script refuses. The aggregate records where its types came from.
Uses the runner's own classification (build_snapshot.slugs / SOC sub-type order).
"""
import csv, json, sys
from pathlib import Path
import build_snapshot as B

def load(date):
    rows = {}
    for name in B.BOROUGH_NAMES:
        f = B.SNAP_DIR/date/(name+".csv")
        for r in csv.DictReader(open(f, encoding="utf-8")):
            r["_la"] = name; rows[r["id"]] = r
    return rows

SOC_TYPES = [("community-benefit-society","community_benefit"),("co-operative-society","co_operative"),
             ("credit-union","credit_union"),("working-mens-club","working_mens_club"),
             ("friendly-society","friendly_society")]

def se_block(rows):
    act = [r for r in rows if str(r["active"]) == "1"]
    st = {k: 0 for _, k in SOC_TYPES}; st["other"] = 0
    for r in act:
        if r["segment"] != "Societies": continue
        t = B.slugs(r)
        for slug, k in SOC_TYPES:
            if slug in t: st[k] += 1; break
        else: st["other"] += 1
    return {"cic": sum(1 for r in act if r["segment"] == "CICs"), "society_types": st}

def main():
    date = sys.argv[1]
    src = sys.argv[sys.argv.index("--types-from")+1] if "--types-from" in sys.argv else None
    rows = load(date)
    note = "computed from this snapshot's organisationType"
    if not all("organisationType" in r for r in rows.values()):
        if not src: sys.exit(f"{date} has no organisationType column; pass --types-from <later snapshot>")
        other = load(src)
        if rows.keys() != other.keys():
            sys.exit(f"REFUSED: organisation sets differ ({len(rows)} vs {len(other)})")
        diffs = [(i, k) for i in rows for k in B.SNAP_HEADER
                 if (rows[i].get(k) or "") != (other[i].get(k) or "")]
        diffs += [(i, "_la") for i in rows if rows[i]["_la"] != other[i]["_la"]]
        if diffs:
            sys.exit(f"REFUSED: {len(diffs)} differing values between {date} and {src}, e.g. {diffs[:5]}")
        for i in rows: rows[i]["organisationType"] = other[i]["organisationType"]
        note = (f"organisation types taken from the {src} snapshot; {date} and {src} verified identical "
                f"on all {len(B.SNAP_HEADER)} shared columns for all {len(rows)} organisations")
    agg = json.loads(B.AGGREGATES.read_text())
    blk = agg["snapshots"][date]
    scopes = {"Tees Valley": list(rows.values())}
    for name in B.BOROUGH_NAMES: scopes[name] = [r for r in rows.values() if r["_la"] == name]
    for scope, rs in scopes.items():
        se = se_block(rs)
        assert se["cic"] == blk[scope]["by_segment"]["CICs"], (scope, "CIC count mismatch")
        assert sum(se["society_types"].values()) == blk[scope]["by_segment"]["Societies"], (scope, "society count mismatch")
        se["source"] = "backfill: " + note
        blk[scope]["social_enterprise"] = se
    B.AGGREGATES.write_text(json.dumps(agg, separators=(',',':'), ensure_ascii=False))
    print(f"{date}: social_enterprise written for {len(scopes)} scopes ({note})")
    print("  Tees Valley:", blk["Tees Valley"]["social_enterprise"])

if __name__ == "__main__":
    main()
