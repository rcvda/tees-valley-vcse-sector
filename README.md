# Tees Valley VCSE Sector Size - a living time series

A weekly-updated count of the registered Voluntary, Community and Social
Enterprise (VCSE) organisations **based in** each Tees Valley local authority -
registered charities and CIOs, Community Interest Companies, registered
societies / mutuals, and Community Amateur Sports Clubs.

"Based in" means the organisation's registered office (HQ) is in the borough -
the canonical headline measure. (The wider "operating from" / area-of-benefit
count is a separate, secondary measure and is not published here.)

## How it updates

`build_snapshot.py` runs every Monday via GitHub Actions
(`.github/workflows/weekly-snapshot.yml`). Each run queries
[Find That Charity](https://findthatcharity.uk) for every Tees Valley borough,
applies the based-in + registered-VCSE filter, and writes:

Nothing fetched is discarded (RCVDA `DATA-STANDARD.md` §2-3, preserve by default).

- `data/snapshots/<date>/raw/<LA code>-<Borough>.csv.gz` - the five Find That Charity
  location exports exactly as downloaded, unfiltered (every organisation FTC returns
  for the area, before the based-in and VCSE filters).
- `data/snapshots/<date>/records.jsonl.gz` - the full FTC organisation record (JSON)
  for every based-in VCSE organisation that week: address, finances, employees,
  volunteers, trustees, description, links and all other fields.
- `data/snapshots/<date>/<Borough>.csv` - one row per based-in VCSE organisation (the
  audit trail for that week). Columns: the 10 original columns (`id`, `name`,
  `charityNumber`, `companyNumber`, `postalCode`, `segment`, `active` (1/0),
  `dateRegistered`, `dateRemoved`, `latestIncome`), then every other column of the FTC
  export (`url`, `latestIncomeDate`, `dateModified`, `orgIDs`, `linked_orgs`,
  `linked_orgs_verified`, `organisationType`, `organisationTypePrimary`, `source`, plus any
  FTC adds later), then `latestFinancialYearEnd`, `latestSpending`, `latestEmployees`,
  `latestVolunteers`, `trusteeCount`, `description`, `telephone`, `email` from the full
  record, then `borough`, `laCode`, `hqGeoCode`.
- `data/tees-valley-vcse-aggregates.json` - per-snapshot summary analytics for the
  dashboard (a summary only; the full data is in the files above), now including
  `workforce` (employees, volunteers, trustees, spending and the number reporting each).
- `data/cache/org_records.jsonl.gz` - full-record cache; a record is re-fetched when FTC's
  `dateModified` for it changes.

**Known gap:** the 2026-11-24 snapshot (the first run) kept only the 10 original
columns; the other FTC fields and the full records for that week were not saved and
cannot be recovered (FTC serves current records only). Every snapshot from the
2026-11-25 re-run onwards is complete.
- `data/tees-valley-vcse-timeseries.csv` - the living spine: one row per
  `snapshot_date x borough x segment`, with the active and total counts.
  Weeks with no change are not duplicated.

No API keys are required - all sources are public.

## Reproduce locally

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python build_snapshot.py
```

## Licensing

- **Code** (`build_snapshot.py` and the workflow): MIT - see `LICENSE`.
- **Data** (everything under `data/`): Creative Commons
  Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) -
  see `data/LICENSE`. Underlying register data is Crown copyright / Open
  Government Licence via Find That Charity.

Author: Peter Neal (https://orcid.org/0009-0005-8101-5785).
Publisher: Redcar and Cleveland Voluntary Development Agency (RCVDA).
