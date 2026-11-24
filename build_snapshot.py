#!/usr/bin/env python3
"""Weekly Tees Valley VCSE sector snapshot (based-in measure).

Counts registered VCSE organisations BASED IN each Tees Valley local authority
(registered office / HQ in the borough) — the canonical headline measure.

Design: the Find That Charity CSV location export already carries organisation
type, active status, dates and income, so segment classification and the active
count come straight from it each run (always current). The one field it lacks is
the HQ geo-code needed for the based-in test, so that is cached per org in
data/cache/hq_geocodes.json and an org is only re-fetched when it is new or the
CSV says its record changed (dateModified advanced). After the cache is seeded a
weekly run is five CSV downloads plus a handful of lookups.

Outputs each run:
  data/snapshots/<YYYY-MM-DD>/<Borough>.csv   based-in VCSE orgs that week
  data/tees-valley-vcse-timeseries.csv        the living spine (appended, deduped)
  data/cache/hq_geocodes.json                 HQ-geocode cache (committed)
"""
from __future__ import annotations
import ast, csv, io, json, os, datetime, time
from collections import Counter
from pathlib import Path
import requests

FTC = "https://findthatcharity.uk"
BOROUGHS = [("E06000001","Hartlepool"),("E06000002","Middlesbrough"),
            ("E06000003","Redcar-and-Cleveland"),("E06000004","Stockton-on-Tees"),
            ("E06000005","Darlington")]
SEGMENTS = ["Charities","CICs","Societies","CASCs"]

CORE = {'registered-charity','registered-charity-england-and-wales',
 'charitable-incorporated-organisation','charitable-incorporated-organisation-foundation',
 'charitable-incorporated-organisation-association','community-interest-company',
 'registered-society','community-benefit-society','co-operative-society',
 'community-amateur-sports-club','credit-union','working-mens-club','friendly-society',
 'parochial-church-council','mutual'}
CHAR = {'registered-charity','registered-charity-england-and-wales',
 'charitable-incorporated-organisation','charitable-incorporated-organisation-foundation',
 'charitable-incorporated-organisation-association'}
SOC = {'registered-society','community-benefit-society','co-operative-society',
 'credit-union','working-mens-club','friendly-society','mutual'}
EXCL_PRIM = {'Local authority maintained school','Academy','Academy converter','Academy sponsor led',
 'Special school','Independent school','Community school','Foundation school','Voluntary aided school',
 'Voluntary controlled school','Community special school','College','Pupil referral unit',
 'Other education provider','Other independent school','Other independent special school',
 'Health organisation','NHS organisation','GP practice','NHS Trust','Local Authority','Government Organisation'}
EXCL_SRC = {'gias','nhsods-epraccur','nhsods-etr','lae'}

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE/"data"/"snapshots"
TIMESERIES = HERE/"data"/"tees-valley-vcse-timeseries.csv"
CACHE = HERE/"data"/"cache"/"hq_geocodes.json"
TS_HEADER = ["segment","borough","snapshot_date","definition","active","total","n_sources"]
SNAP_HEADER = ["id","name","charityNumber","companyNumber","postalCode","segment",
               "active","dateRegistered","dateRemoved","latestIncome"]
SNAPSHOT_DATE = os.environ.get("SNAPSHOT_DATE") or datetime.date.today().isoformat()

def slugs(r):
    try: return set(ast.literal_eval(r["organisationType"]))
    except Exception: return set()
def is_vcse(r):
    return bool(slugs(r)&CORE) and r["organisationTypePrimary"] not in EXCL_PRIM and r["source"] not in EXCL_SRC
def segment(s):
    if s&CHAR: return "Charities"
    if "community-interest-company" in s: return "CICs"
    if "community-amateur-sports-club" in s: return "CASCs"
    if s&SOC: return "Societies"
    return "Other VCSE"

def fetch_csv(code, session):
    r = session.get(FTC+"/", params={"q":"","location":code,"filetype":"csv"}, timeout=120)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))

def hq_of(data):
    for l in (data.get("location") or []):
        if isinstance(l,dict) and (l.get("type") or "").upper()=="HQ":
            return (l.get("geoCode") or "").strip()
    return ""

def load_cache():
    if CACHE.exists():
        try: return json.loads(CACHE.read_text())
        except Exception: return {}
    return {}

def refresh_hq(vcse_rows, cache, session):
    """Fetch HQ geocode for ids that are new or whose record changed."""
    need = []
    for r in vcse_rows:
        rec = cache.get(r["id"]); dm = r.get("dateModified","")
        if rec is None or rec.get("dm","") != dm:
            need.append((r["id"], dm))
    fetched = 0
    for oid, dm in need:
        try:
            resp = session.get(f"{FTC}/orgid/{oid}.json", timeout=15)
            if resp.status_code == 404:
                cache[oid] = {"geoCode":"","dm":dm,"missing":True}
            else:
                resp.raise_for_status()
                cache[oid] = {"geoCode":hq_of(resp.json()),"dm":dm}
            fetched += 1
        except Exception as e:
            if oid not in cache:            # keep any prior value on transient error
                cache[oid] = {"geoCode":"","dm":dm,"error":str(e)[:60]}
        time.sleep(0.3)
    return fetched

def main():
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    summary = []
    with requests.Session() as s:
        csvs = {code: fetch_csv(code, s) for code,_ in BOROUGHS}
        vcse_all = {}
        for rows in csvs.values():
            for r in rows:
                if is_vcse(r): vcse_all[r["id"]] = r
        fetched = refresh_hq(list(vcse_all.values()), cache, s)
        print(f"hq cache: {len(cache)} entries ({fetched} fetched this run)")
        for code, name in BOROUGHS:
            act, tot, snap = Counter(), Counter(), []
            for r in csvs[code]:
                if not is_vcse(r): continue
                rec = cache.get(r["id"])
                if not rec or rec.get("geoCode") != code: continue
                seg = segment(slugs(r))
                tot[seg]+=1; active = 1 if r["active"]=="True" else 0
                if active: act[seg]+=1
                snap.append([r["id"], r["name"], r["charityNumber"], r["companyNumber"],
                             r["postalCode"], seg, active, r["dateRegistered"],
                             r["dateRemoved"], r["latestIncome"]])
            outdir = SNAP_DIR/SNAPSHOT_DATE; outdir.mkdir(parents=True, exist_ok=True)
            with open(outdir/(name+".csv"), "w", newline="", encoding="utf-8") as fh:
                w=csv.writer(fh); w.writerow(SNAP_HEADER); w.writerows(snap)
            for seg in SEGMENTS:
                summary.append([seg, name, SNAPSHOT_DATE, "based-in", act[seg], tot[seg], 1])
            print(f"  {name}: active {sum(act[seg] for seg in SEGMENTS)}  (" +
                  ", ".join(f"{seg} {act[seg]}/{tot[seg]}" for seg in SEGMENTS) + ")")
    CACHE.write_text(json.dumps(cache, separators=(',',':'), sort_keys=True))
    # append to timeseries, dedup on (segment,borough,date)
    existing = []
    if TIMESERIES.exists():
        rd = list(csv.reader(open(TIMESERIES, encoding="utf-8")))
        existing = rd[1:] if rd else []
    seen = {(r[0],r[1],r[2]) for r in existing if len(r)>=3}
    added = [r for r in summary if (r[0],r[1],str(r[2])) not in seen]
    with open(TIMESERIES, "w", newline="", encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(TS_HEADER); w.writerows(existing); w.writerows(added)
    print(f"timeseries: +{len(added)} rows (total now {len(existing)+len(added)})")

if __name__ == "__main__":
    main()
