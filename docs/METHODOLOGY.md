# Methodology

How the CA-44 Atlas turns public records into figures, and how it checks them.

## Two plans

The atlas follows the seat, not one officeholder, and California drew the seat twice this decade:

- **2021 lines (cd119):** drawn by the California Citizens Redistricting Commission; in effect for the
  118th and 119th Congresses.
- **New lines (cd120):** AB 604 (Chapter 96, Statutes of 2025), approved by voters as Proposition 50 on
  Nov. 4, 2025, for the 2026 through 2030 elections; the 120th Congress is seated Jan. 3, 2027.

Every figure names the plan it describes.

## Geography from census blocks

1. **Block assignment.** The Census Bureau's block equivalency files list every 2020 census block and
   its district: the 119th Congress national file for the 2021 lines, and the 120th Congress files
   (California state file and national file, which must agree) for the new lines.
   The new lines are also read from the state's own AB 604 block file, published by the Statewide
   Database at UC Berkeley; the build fails its check unless that file and the Census file assign
   the same blocks to the district and list the same number of California blocks.
2. **Population.** Each block's 2020 population comes from the 2020 Census redistricting data
   (P.L. 94-171). A plan's population is the sum of its blocks.
3. **Area and outline.** TIGER/Line 2020 block shapes give land and water area; the district outline
   is the plan's blocks dissolved into one shape.
4. **Cities and places.** Each block carries the code of its incorporated city or census-designated
   place (CDP). Blocks in no place are "other unincorporated."

### Checks

- Block populations for the 2021 lines are compared with the Census Bureau's own 2020 tabulation for
  the 119th Congress district.
- Block land area for the 2021 lines is compared with the Census Gazetteer (tolerance 0.5%).
- Each plan's population is compared with an equal share of California's 2020 population (52 seats).
  California balanced its districts on adjusted counts, so a gap of a few tenths of a percent is expected.
- Places and the unincorporated remainder must add up to the whole plan.

## People and homes (ACS)

- **2021 lines:** the Census Bureau tabulates the ACS for the 119th Congress district directly. The
  atlas uses those figures, 1-year and 5-year, with margins of error at 90% confidence.
- **New lines:** no Census tabulation exists yet. The atlas multiplies each census tract's ACS 5-year
  counts by the share of the tract's 2020 population inside the new lines, sums them, and computes
  shares from the sums. Medians and averages (median age, income, home value, rent) cannot be summed
  and are not estimated. Margins of error for counts are combined as the root of summed squares and
  understate the true uncertainty, because the population weights are themselves fixed at 2020.
- **Method check:** the same tract calculation is run for the 2021 lines and compared with the Census
  Bureau's own figures for the same ACS release (counts within 1%, shares within 1.5 points). On Nov. 26,
  2026, a test run on the 2020-2024 release reproduced the 2021-lines population within 0.09%, poverty
  within 0.05 points, and homeownership within 0.03 points.

## Work

Monthly unemployment comes from the Bureau of Labor Statistics' Local Area Unemployment Statistics, not
seasonally adjusted. BLS publishes cities of 25,000 or more people, counties, states, and the nation, but no
congressional districts. The atlas lists every city in either plan that BLS publishes; city figures describe the
whole city. The latest month is preliminary.

## Ports

- **Docks:** U.S. Army Corps of Engineers navigation facility records (National Transportation Atlas Database).
  Each dock's coordinates are tested against both plans' full-resolution outlines, which include harbor water.
  The records' own congressional district fields name older Congresses and are not used.
- **Containers:** each port's own monthly TEU reports (Port of Los Angeles calendar-year pages; Port of Long Beach
  calendar-year and 25-month tables). Checks: months sum to each port's year totals, and the two Long Beach
  tables agree. Long Beach calls its latest figures preliminary.

## Bridge, cameras, and airports

- **Vincent Thomas Bridge:** facts read by hand from Caltrans District 7 releases and project pages, each tied to its
  page in `data/curated/projects.yaml`, with a review date. News reports are not used for facts. Day counts on the
  page are computed from Caltrans's closure and reopening dates.
- **County motion:** the Nov. 17, 2026 motion before the Los Angeles County Board of Supervisors is described from the
  County's own copy of the motion. That document shows what was moved, not how the Board voted, so the atlas does
  not state the vote until the Board's record of it (the Statement of Proceedings) is read.
- **In the news:** a short list of news reports, shown apart from the facts and labeled as news. Each entry gives the
  outlet, date, headline as printed, and link. The list points readers toward public records; no fact on the page
  cites it. The build refuses a fact that cites a news link, and the list carries its own review date. An entry
  comes off once the official record it points to is cited.
- **Cameras:** Caltrans's CWWP2 camera status file for District 7. Cameras inside either plan's outline are listed with
  links to the current image and live video. City, port, and private cameras are not included.
- **Airports and heliports:** FAA landing facility records (BTS National Transportation Atlas Database), tested against
  both plans. Includes private-use heliports.

## Representation, elections, and money

- **Member:** congress-legislators (unitedstates project) checked against the Clerk of the House.
- **House votes:** Clerk of the House roll calls.
- **Election results:** MIT Election Data and Science Lab and FEC certified compilations, from 2012,
  the first election near today's district. Before 2012, "the 44th" was in Riverside County.
- **Campaign finance:** FEC candidate totals by cycle.
- **Federal awards:** USAspending.gov by place of performance, under the district lines USAspending
  uses (currently the 2021 lines).
- **Income tax:** IRS Statistics of Income by congressional district (2021 lines).

## Labels

"est." marks a figure computed by the atlas rather than published by the source. Unofficial election
results are labeled until certified.
