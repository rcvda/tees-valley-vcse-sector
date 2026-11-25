#!/usr/bin/env python3
"""Weekly Tees Valley VCSE sector snapshot (based-in measure).

Counts registered VCSE organisations BASED IN each Tees Valley local authority
(registered office / HQ in the borough) — the canonical headline measure.

Design: the Find That Charity CSV location export already carries organisation
type, active status, dates, income and website, so segment classification, the
active count and the richer analytics all come straight from it each run (always
current). The one field it lacks is the HQ geo-code needed for the based-in test,
so that is cached per org in data/cache/hq_geocodes.json and an org is only
re-fetched when it is new or the CSV says its record changed (dateModified
advanced). After the cache is seeded a weekly run is five CSV downloads plus a
handful of lookups.

Preserve by default (DATA-STANDARD §2-3): nothing fetched is discarded.

Outputs each run:
  data/snapshots/<YYYY-MM-DD>/raw/<LA code>-<Borough>.csv.gz
                                              the five FTC location exports, byte-for-byte
                                              as downloaded (unfiltered: every org FTC returns)
  data/snapshots/<YYYY-MM-DD>/records.jsonl.gz
                                              the full FTC org record (orgid JSON) for every
                                              based-in VCSE org that week — address, finances,
                                              employees, volunteers, trustees, links, etc.
  data/snapshots/<YYYY-MM-DD>/<Borough>.csv   based-in VCSE orgs that week: the 10 legacy
                                              columns, then EVERY other column of the FTC
                                              export, then the scalar record fields
                                              (RECORD_FIELDS), then borough / laCode / hqGeoCode
  data/tees-valley-vcse-timeseries.csv        the living spine — counts (appended, deduped)
  data/tees-valley-vcse-aggregates.json       the living detail — per-snapshot analytics
  data/cache/hq_geocodes.json                 HQ-geocode cache (committed)
  data/cache/org_records.jsonl.gz             full-record cache; a record is re-fetched when
                                              FTC's dateModified for it changes (committed)
"""
from __future__ import annotations
import ast, csv, gzip, io, json, os, datetime, time, statistics
from collections import Counter
from pathlib import Path
import requests

FTC = "https://findthatcharity.uk"
BOROUGHS = [("E06000001","Hartlepool"),("E06000002","Middlesbrough"),
            ("E06000003","Redcar-and-Cleveland"),("E06000004","Stockton-on-Tees"),
            ("E06000005","Darlington")]
BOROUGH_NAMES = [n for _, n in BOROUGHS]
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
CIO = {'charitable-incorporated-organisation','charitable-incorporated-organisation-foundation',
 'charitable-incorporated-organisation-association'}
SOC = {'registered-society','community-benefit-society','co-operative-society',
 'credit-union','working-mens-club','friendly-society','mutual'}
EXCL_PRIM = {'Local authority maintained school','Academy','Academy converter','Academy sponsor led',
 'Special school','Independent school','Community school','Foundation school','Voluntary aided school',
 'Voluntary controlled school','Community special school','College','Pupil referral unit',
 'Other education provider','Other independent school','Other independent special school',
 'Health organisation','NHS organisation','GP practice','NHS Trust','Local Authority','Government Organisation'}
EXCL_SRC = {'gias','nhsods-epraccur','nhsods-etr','lae'}
BANDS = [("£1m +",1_000_000),("£500k - £1m",500_000),("£250k - £500k",250_000),
         ("£100k - £250k",100_000),("£75k - £100k",75_000),("£50k - £75k",50_000),
         ("Over 25k",25_000),("Over 10k",10_000),("Under 10k",0)]
DECADES = ["2020s","2010s","2000s","1990s","1980s","1970s","1960s","Pre-1960"]

HERE = Path(__file__).resolve().parent
SNAP_DIR = HERE/"data"/"snapshots"
TIMESERIES = HERE/"data"/"tees-valley-vcse-timeseries.csv"
AGGREGATES = HERE/"data"/"tees-valley-vcse-aggregates.json"
CACHE = HERE/"data"/"cache"/"hq_geocodes.json"
RECORDS = HERE/"data"/"cache"/"org_records.jsonl.gz"
TS_HEADER = ["segment","borough","snapshot_date","definition","active","total","n_sources"]
SNAP_HEADER = ["id","name","charityNumber","companyNumber","postalCode","segment",
               "active","dateRegistered","dateRemoved","latestIncome"]   # legacy order kept
# scalar fields lifted from the full org record into the per-org CSV (the whole
# record is also kept, unflattened, in records.jsonl.gz)
RECORD_FIELDS = ["latestFinancialYearEnd","latestSpending","latestEmployees",
                 "latestVolunteers","trusteeCount","description","telephone","email"]
DERIVED = ["borough","laCode","hqGeoCode"]
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
def income_of(r):
    v = r.get("latestIncome","")
    try: return float(v) if v not in (None,"") else None
    except Exception: return None
def band_of(v):
    for lab, lo in BANDS:
        if v >= lo: return lab
    return "Under 10k"
def decade_of(r):
    d = r.get("dateRegistered","")
    if not d or len(d) < 4: return None
    try: y = int(d[:4])
    except Exception: return None
    return "Pre-1960" if y < 1960 else f"{(y//10)*10}s"

def fetch_csv(code, session):
    r = session.get(FTC+"/", params={"q":"","location":code,"filetype":"csv"}, timeout=120)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    header = next(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))), [])
    return rows, header, r.content

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

def load_records():
    out = {}
    if RECORDS.exists():
        try:
            with gzip.open(RECORDS, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        d = json.loads(line); out[d["id"]] = d
        except Exception: return {}
    return out

def save_records(records):
    with gzip.open(RECORDS, "wt", encoding="utf-8", compresslevel=9) as fh:
        for oid in sorted(records):
            fh.write(json.dumps(records[oid], ensure_ascii=False, sort_keys=True)+"\n")

def refresh_hq(vcse_rows, cache, session, records):
    """Fetch the full org record for ids that are new, whose record changed, or
    whose full record is not yet held. Keeps the WHOLE record (records) and the
    HQ geocode (cache)."""
    need = []
    for r in vcse_rows:
        rec = cache.get(r["id"]); dm = r.get("dateModified","")
        if rec is None or rec.get("dm","") != dm or r["id"] not in records:
            need.append((r["id"], dm))
    fetched = 0
    for oid, dm in need:
        try:
            resp = session.get(f"{FTC}/orgid/{oid}.json", timeout=15)
            if resp.status_code == 404:
                cache[oid] = {"geoCode":"","dm":dm,"missing":True}
            else:
                resp.raise_for_status()
                data = resp.json()
                records[oid] = data
                cache[oid] = {"geoCode":hq_of(data),"dm":dm}
            fetched += 1
        except Exception as e:
            if oid not in cache:            # keep any prior value on transient error
                cache[oid] = {"geoCode":"","dm":dm,"error":str(e)[:60]}
        time.sleep(0.15)
    return fetched

def compute_rich(rows):
    """Rich analytics for one scope (list of annotated based-in VCSE csv rows).

    Every metric is derived from the FTC location export the run already holds —
    no extra fetches. Figures describe the ACTIVE sector unless noted.
    """
    active = [r for r in rows if r["active"] == "True"]
    o = {"total_all": len(rows), "active": len(active), "inactive": len(rows)-len(active)}
    sc = Counter(r["_seg"] for r in active)
    o["by_segment"] = {k: sc.get(k,0) for k in SEGMENTS}
    char = [r for r in active if r["_seg"] == "Charities"]
    def is_inc(r): return bool(slugs(r)&CIO) or "incorporated-charity" in slugs(r)
    inc_n = sum(1 for r in char if is_inc(r))
    o["legal"] = {
        "total_charities": len(char),
        "incorporated": inc_n,
        "unincorporated": len(char)-inc_n,
        "cio_foundation": sum(1 for r in char if "charitable-incorporated-organisation-foundation" in slugs(r)),
        "cio_association": sum(1 for r in char if "charitable-incorporated-organisation-association" in slugs(r)),
        "charitable_company": sum(1 for r in char if "registered-company" in slugs(r) and not (slugs(r)&CIO)),
        "trust": sum(1 for r in char if "trust" in slugs(r)),
    }
    dc = Counter((decade_of(r), r["_seg"]) for r in active if decade_of(r))
    o["decades"] = {k: {s: dc.get((k,s),0) for s in SEGMENTS} for k in DECADES}
    incomes = [income_of(r) for r in active]
    have = [v for v in incomes if v is not None]
    o["no_income"] = sum(1 for v in incomes if v is None)
    o["income_bands"] = {lab: 0 for lab,_ in BANDS}
    for v in have: o["income_bands"][band_of(v)] += 1
    o["avg_income"] = round(sum(have)/len(have)) if have else 0
    o["median_income"] = round(statistics.median(have)) if have else 0
    sv = sum(have)
    o["sector_value"] = round(sv)
    sh = sorted(have, reverse=True)
    o["concentration"] = {"top10": round(100*sum(sh[:10])/sv) if sv else 0,
                          "top25": round(100*sum(sh[:25])/sv) if sv else 0}
    def bucket(v): return "none" if v is None else ("large" if v>=100000 else ("medium" if v>=10000 else "small"))
    size = {k: {"n":0,"val":0.0} for k in ("large","medium","small","none")}
    for r in active:
        v = income_of(r); b = bucket(v); size[b]["n"] += 1; size[b]["val"] += (v or 0)
    for k in size:
        size[k]["pct"] = round(100*size[k]["val"]/sv) if sv else 0
        size[k]["val"] = round(size[k]["val"])
    o["size"] = size
    def num(v):
        try: return float(v) if v not in (None,"") else None
        except Exception: return None
    wf = {}
    for f, k in (("latestEmployees","employees"),("latestVolunteers","volunteers"),
                 ("trusteeCount","trustees"),("latestSpending","spending")):
        vals = [num((r.get("_rec") or {}).get(f)) for r in active]
        vals = [v for v in vals if v is not None]
        wf[k] = round(sum(vals)); wf[k+"_n"] = len(vals)
    o["workforce"] = wf
    o["has_web"] = sum(1 for r in active if (r.get("url") or "").strip())
    o["web_pct"] = round(100*o["has_web"]/len(active), 1) if active else 0
    top = sorted(active, key=lambda r: (income_of(r) or -1), reverse=True)[:10]
    o["top10"] = [{"name": r["name"], "income": round(income_of(r)) if income_of(r) else 0,
                   "segment": r["organisationTypePrimary"] or r["_seg"], "la": r["_la"],
                   "url": (r.get("url") or "").strip()} for r in top]
    reg = len(char); total = round(reg/0.26) if reg else 0
    o["navca"] = {"registered": reg, "community": round(total*0.68),
                  "social": round(total*0.06), "total": total}
    return o

def main():
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    records = load_records()
    summary = []
    based = {name: [] for name in BOROUGH_NAMES}   # annotated based-in VCSE rows per borough
    with requests.Session() as s:
        fetched_csv = {code: fetch_csv(code, s) for code,_ in BOROUGHS}
        csvs = {code: v[0] for code, v in fetched_csv.items()}
        outdir = SNAP_DIR/SNAPSHOT_DATE; (outdir/"raw").mkdir(parents=True, exist_ok=True)
        ftc_cols = []
        for code, name in BOROUGHS:
            with open(outdir/"raw"/f"{code}-{name}.csv.gz", "wb") as fh:
                fh.write(gzip.compress(fetched_csv[code][2], mtime=0))
            for c in fetched_csv[code][1]:
                if c not in ftc_cols: ftc_cols.append(c)
        extra_cols = [c for c in ftc_cols if c not in SNAP_HEADER]
        header = SNAP_HEADER + extra_cols + RECORD_FIELDS + DERIVED
        vcse_all = {}
        for rows in csvs.values():
            for r in rows:
                if is_vcse(r): vcse_all[r["id"]] = r
        fetched = refresh_hq(list(vcse_all.values()), cache, s, records)
        print(f"hq cache: {len(cache)} entries; full records held: {len(records)} ({fetched} fetched this run)")
        week_records = []
        for code, name in BOROUGHS:
            act, tot, snap = Counter(), Counter(), []
            for r in csvs[code]:
                if not is_vcse(r): continue
                rec = cache.get(r["id"])
                if not rec or rec.get("geoCode") != code: continue
                seg = segment(slugs(r))
                r["_seg"] = seg; r["_la"] = name
                full = records.get(r["id"]) or {}
                r["_rec"] = full
                if full: week_records.append(full)
                based[name].append(r)
                tot[seg]+=1; active = 1 if r["active"]=="True" else 0
                if active: act[seg]+=1
                snap.append([r["id"], r["name"], r["charityNumber"], r["companyNumber"],
                             r["postalCode"], seg, active, r["dateRegistered"],
                             r["dateRemoved"], r["latestIncome"]]
                            + [r.get(c,"") for c in extra_cols]
                            + [("" if full.get(f) is None else full.get(f)) for f in RECORD_FIELDS]
                            + [name, code, rec.get("geoCode","")])
            with open(outdir/(name+".csv"), "w", newline="", encoding="utf-8") as fh:
                w=csv.writer(fh); w.writerow(header); w.writerows(snap)
            for seg in SEGMENTS:
                summary.append([seg, name, SNAPSHOT_DATE, "based-in", act[seg], tot[seg], 1])
            print(f"  {name}: active {sum(act[seg] for seg in SEGMENTS)}  (" +
                  ", ".join(f"{seg} {act[seg]}/{tot[seg]}" for seg in SEGMENTS) + ")")
        with gzip.open(outdir/"records.jsonl.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
            for d in sorted(week_records, key=lambda d: d.get("id","")):
                fh.write(json.dumps(d, ensure_ascii=False, sort_keys=True)+"\n")
        print(f"records: {len(week_records)} full org records written for {SNAPSHOT_DATE}")
    CACHE.write_text(json.dumps(cache, separators=(',',':'), sort_keys=True))
    save_records(records)

    # append to timeseries (counts spine), dedup on (segment,borough,date)
    existing = []
    if TIMESERIES.exists():
        rd = list(csv.reader(open(TIMESERIES, encoding="utf-8")))
        existing = rd[1:] if rd else []
    seen = {(r[0],r[1],r[2]) for r in existing if len(r)>=3}
    added = [r for r in summary if (r[0],r[1],str(r[2])) not in seen]
    with open(TIMESERIES, "w", newline="", encoding="utf-8") as fh:
        w=csv.writer(fh); w.writerow(TS_HEADER); w.writerows(existing); w.writerows(added)
    print(f"timeseries: +{len(added)} rows (total now {len(existing)+len(added)})")

    # write/append the rich analytics for this snapshot (per borough + Tees Valley)
    scopes = {"Tees Valley": [r for name in BOROUGH_NAMES for r in based[name]]}
    for name in BOROUGH_NAMES:
        scopes[name] = based[name]
    block = {scope: compute_rich(rows) for scope, rows in scopes.items()}
    agg = {"latest": SNAPSHOT_DATE, "generated": SNAPSHOT_DATE, "snapshots": {}}
    if AGGREGATES.exists():
        try:
            prev = json.loads(AGGREGATES.read_text())
            if isinstance(prev.get("snapshots"), dict): agg["snapshots"] = prev["snapshots"]
        except Exception: pass
    agg["snapshots"][SNAPSHOT_DATE] = block
    agg["latest"] = max(agg["snapshots"])
    AGGREGATES.write_text(json.dumps(agg, separators=(',',':'), ensure_ascii=False))
    print(f"aggregates: snapshot {SNAPSHOT_DATE} written ({len(agg['snapshots'])} snapshot(s) total)")

if __name__ == "__main__":
    main()
