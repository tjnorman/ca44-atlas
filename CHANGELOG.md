# Changelog

## 0.2.1 — Nov. 26, 2026 (private draft)

- New check `bef-state-cd120`: the state's own AB 604 block file (Statewide Database) must assign the same
  blocks to the district as the Census Bureau's 120th Congress file. On Nov. 26, 2026 the two files agreed
  on all 519,723 California blocks, including the 6,672 in CA-44.

## 0.2.0 — Nov. 26, 2026 (private draft)

- New `laus` source: BLS monthly unemployment for every city of 25,000 or more in either plan, with Los Angeles
  County, California, and the United States; whole-city scope labeled.
- New `ports` source: Corps of Engineers dock records for the Port of Los Angeles and the Port of Long Beach,
  each dock tested against both plans; monthly container counts from each port, checked against the ports'
  own year totals and, for Long Beach, between two of its tables.
- Full-resolution plan outlines saved for point tests (colleges, stations, docks).
- License: code MIT; text and compiled tables CC BY 4.0 (`LICENSE-CONTENT.md`).

## 0.1.0 — Nov. 26, 2026 (private draft)

- First build, adapted from the WI-7 Atlas pipeline.
- New `plans` source: both CA-44 plans from Census block equivalency files, 2020 block populations,
  and TIGER/Line block shapes; cities and places; overlap between plans.
- New `acs_plan` source: tract-based ACS estimates for the new lines, with a method check against
  the Census Bureau's figures for the 2021 lines.
- Removed county-based sources (unemployment, jobs, county population estimates, municipalities) and
  Wisconsin-only sources (WisDOT roads and cameras, the Blatnik Bridge, Wisconsin Social Security tables).
