# Changelog

## 0.1.0 — Nov. 26, 2026 (private draft)

- First build, adapted from the WI-7 Atlas pipeline.
- New `plans` source: both CA-44 plans from Census block equivalency files, 2020 block populations,
  and TIGER/Line block shapes; cities and places; overlap between plans.
- New `acs_plan` source: tract-based ACS estimates for the new lines, with a method check against
  the Census Bureau's figures for the 2021 lines.
- Removed county-based sources (unemployment, jobs, county population estimates, municipalities) and
  Wisconsin-only sources (WisDOT roads and cameras, the Blatnik Bridge, Wisconsin Social Security tables).
