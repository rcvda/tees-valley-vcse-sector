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

- `data/snapshots/<date>/<Borough>.csv` - one row per based-in VCSE organisation
  (the audit trail for that week).
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
