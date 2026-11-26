#!/usr/bin/env python3
"""Add the CIC legal structure (limited by shares vs by guarantee) to the
aggregates' `social_enterprise` block for a snapshot.

  python backfill_cic_structure.py 2026-11-25 [2026-11-24 ...]

Source: data/cache/cic_company_types.json — each CIC's "Company type" as shown on
its public Companies House page (find-and-update.company-information.service.gov.uk),
looked up by company number. Neither Find That Charity nor the Companies House
bulk product carries the distinction (bulk files show every CIC as just
"Community Interest Company").

Classification of the Companies House "Company type" text:
  "Private limited Company ..." / "Public limited Company ..."      -> shares
  "Private company limited by guarantee without share capital ..."  -> guarantee
  (incl. the "use of 'Limited' exemption" variant)
  "Converted/closed company ..."                                      -> converted
  anything else / not looked up                                        -> unknown

A CIC's legal form almost never changes, so one lookup serves every snapshot that
contains the company; the block records the lookup date.
"""
import csv, json, sys
import build_snapshot as B

CACHE = B.HERE/"data"/"cache"/"cic_company_types.json"

def classify(t):
    t = (t or "").lower()
    if t.startswith("private limited company") or t.startswith("public limited company"): return "shares"
    if "limited by guarantee" in t: return "guarantee"
    if t.startswith("converted/closed"): return "converted"
    return "unknown"

def main():
    types = json.loads(CACHE.read_text())
    agg = json.loads(B.AGGREGATES.read_text())
    for date in sys.argv[1:]:
        rows = []
        for name in B.BOROUGH_NAMES:
            for r in csv.DictReader(open(B.SNAP_DIR/date/(name+".csv"), encoding="utf-8")):
                r["_la"] = name; rows.append(r)
        blk = agg["snapshots"][date]
        scopes = {"Tees Valley": rows, **{n: [r for r in rows if r["_la"] == n] for n in B.BOROUGH_NAMES}}
        for scope, rs in scopes.items():
            act = [r for r in rs if str(r["active"]) == "1" and r["segment"] == "CICs"]
            c = {"shares": 0, "guarantee": 0, "converted": 0, "unknown": 0}
            for r in act:
                rec = types.get((r["companyNumber"] or "").strip().zfill(8))
                c[classify(rec and rec.get("type"))] += 1
            assert sum(c.values()) == blk[scope]["by_segment"]["CICs"], (date, scope, "CIC count mismatch")
            se = blk[scope].setdefault("social_enterprise", {})
            se["cic_structure"] = c
            se["cic_structure_source"] = "Companies House public company pages, looked up " + types.get("_meta", {}).get("checked", "?")
        print(date, "Tees Valley active CICs:", blk["Tees Valley"]["social_enterprise"]["cic_structure"])
    B.AGGREGATES.write_text(json.dumps(agg, separators=(',',':'), ensure_ascii=False))

if __name__ == "__main__":
    main()
