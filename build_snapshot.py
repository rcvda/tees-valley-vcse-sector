#!/usr/bin/env python3
"""Weekly Tees Valley VCSE sector snapshot (based-in measure).

For each Tees Valley local authority this fetches the Find That Charity
candidate universe, enriches each organisation, keeps those BASED IN the
borough (registered-office / HQ geo-code == the LA) that carry a registered
VCSE organisation type (statutory bodies excluded), and records the active and
total counts by segment.

Outputs each run:
  data/snapshots/<YYYY-MM-DD>/<Borough>.csv  one row per based-in VCSE org
  data/tees-valley-vcse-timeseries.csv       the living spine, appended

The generic resolver lives in charity-data-tools; the editorial method
(based-in rule, VCSE include/exclude, segment mapping) lives here.
Run:  python build_snapshot.py   (set SNAPSHOT_DATE=YYYY-MM-DD to override)
"""
from __future__ import annotations
import csv, os, datetime
from collections import Counter
from pathlib import Path

import requests
from charity_data_tools.ftc.client import FTCClient
from charity_data_tools.ftc import geo

BOROUGHS = [
    ("E06000001", "Hartlepool"),
    ("E06000002", "Middlesbrough"),
    ("E06000003", "Redcar-and-Cleveland"),
    ("E06000004", "Stockton-on-Tees"),
    ("E06000005", "Darlington"),
]
HEADLINE_SEGMENTS = ["Charities", "CICs", "Societies", "CASCs"]

CORE_VCSE = {
    "Registered Charity", "Charitable Incorporated Organisation",
    "Community Interest Company", "Registered Society", "Community Benefit Society",
    "Co-operative Society", "Community Amateur Sports Club", "Credit Union",
    "Working Men's Club", "Friendly Society", "Parochial Church Council",
}
EXCLUDE_PRIMARY = {
    "Local authority maintained school", "Academy", "Academy converter",
    "Academy sponsor led", "Special school", "Independent school", "Community school",
    "Foundation school", "Voluntary aided school", "Voluntary controlled school",
    "Community special school", "College", "Pupil referral unit",
    "Other education provider", "Other independent school",
    "Other independent special school", "Health organisation", "NHS organisation",
    "GP practice", "NHS Trust", "Local Authority", "Government Organisation",
}

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE / "data" / "snapshots"
TIMESERIES = HERE / "data" / "tees-valley-vcse-timeseries.csv"
TS_HEADER = ["segment", "borough", "snapshot_date", "definition", "active", "total", "n_sources"]
SNAP_HEADER = ["id", "name", "charityNumber", "companyNumber", "postalCode",
               "segment", "active", "dateRegistered", "dateRemoved", "latestIncome"]
SNAPSHOT_DATE = os.environ.get("SNAPSHOT_DATE") or datetime.date.today().isoformat()


def is_vcse(data):
    types = set(data.get("organisationType") or [])
    primary = data.get("organisationTypePrimary") or ""
    return bool(types & CORE_VCSE) and primary not in EXCLUDE_PRIMARY


def segment_of(types):
    if types & {"Registered Charity", "Charitable Incorporated Organisation"}:
        return "Charities"
    if "Community Interest Company" in types:
        return "CICs"
    if "Community Amateur Sports Club" in types:
        return "CASCs"
    if types & {"Registered Society", "Community Benefit Society", "Co-operative Society",
                "Credit Union", "Working Men's Club", "Friendly Society"}:
        return "Societies"
    return "Other VCSE"


def build_borough(geocode, session):
    cands = geo.fetch_location_candidates(geocode, orgtype=None, session=session)
    client = FTCClient(session)
    rows = []
    for c in cands:
        data, err = client.fetch_org(c["id"])
        if err or data is None:
            continue
        if not geo.is_based_in(data, geocode):
            continue
        if not is_vcse(data):
            continue
        types = set(data.get("organisationType") or [])
        inc = data.get("latestIncome")
        rows.append({
            "id": c["id"],
            "name": data.get("name") or c.get("name") or "",
            "charityNumber": data.get("charityNumber") or "",
            "companyNumber": data.get("companyNumber") or "",
            "postalCode": geo.extract_hq(data).get("id") or "",
            "segment": segment_of(types),
            "active": 1 if data.get("active", True) else 0,
            "dateRegistered": data.get("dateRegistered") or "",
            "dateRemoved": data.get("dateRemoved") or "",
            "latestIncome": inc if isinstance(inc, (int, float)) else "",
        })
    return rows


def write_snapshot(name, rows):
    outdir = SNAP_DIR / SNAPSHOT_DATE
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / (name + ".csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(SNAP_HEADER)
        for r in rows:
            w.writerow([r[k] for k in SNAP_HEADER])


def summarise(name, rows):
    total = Counter(r["segment"] for r in rows)
    active = Counter(r["segment"] for r in rows if r["active"])
    return [(seg, name, SNAPSHOT_DATE, "based-in", active[seg], total[seg], 1)
            for seg in HEADLINE_SEGMENTS]


def append_timeseries(summary_rows):
    existing = []
    if TIMESERIES.exists():
        with open(TIMESERIES, encoding="utf-8") as fh:
            rd = list(csv.reader(fh))
            existing = rd[1:] if rd else []
    seen = {(r[0], r[1], r[2]) for r in existing if len(r) >= 3}
    new = [r for r in summary_rows if (r[0], r[1], r[2]) not in seen]
    with open(TIMESERIES, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(TS_HEADER)
        for r in existing:
            w.writerow(r)
        for r in new:
            w.writerow(r)
    return len(new)


def main():
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    with requests.Session() as s:
        for geocode, name in BOROUGHS:
            rows = build_borough(geocode, s)
            write_snapshot(name, rows)
            summary.extend(summarise(name, rows))
            print(name + ": " + str(len(rows)) + " based-in VCSE (active "
                  + str(sum(1 for r in rows if r["active"])) + ")")
    added = append_timeseries(summary)
    print("snapshot " + SNAPSHOT_DATE + ": appended " + str(added) + " new time-series rows")


if __name__ == "__main__":
    main()
