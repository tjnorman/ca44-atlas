# CA-44 Atlas

California's 44th Congressional District, counted. A nonpartisan, sourced record of the seat:
who lives in it, what the federal government spends there, and how it is represented.

**Site: [ca-44.com](https://ca-44.com)** (public since Nov. 27, 2026; ca-44thcd.com redirects there).

## Publisher

Thomas J. Norman publishes the atlas as a personal project and is responsible for its contents. It is
nonpartisan: it endorses no candidate and takes no position on legislation. It is not a product of the
Northwest San Pedro Neighborhood Council, of California State University, Dominguez Hills, or of any
other government body, employer, campaign, party, or officeholder.

## Two maps of one seat

California redrew its congressional map for the 2026 elections. The atlas follows both versions of
CA-44 and says which one every figure describes.

| Plan | In effect | Source of the lines |
|---|---|---|
| **New lines** (primary) | 120th Congress, from Jan. 3, 2027; first used in the Nov. 3, 2026 election | AB 604 (Chapter 96, Statutes of 2025), put into effect by Proposition 50 (Nov. 4, 2025) |
| **2021 lines** | 118th and 119th Congresses (2023 to Jan. 3, 2027); 2022 and 2024 elections | California Citizens Redistricting Commission (2021) |

Both plans are read from the Census Bureau's block equivalency files, which assign every 2020
census block to a district. See [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

## How this differs from the WI-7 Atlas

This repository adapts the pipeline of the [WI-7 Atlas](https://github.com/tjnorman/wi7-atlas).
WI-7 spans 26 counties, so that atlas is organized by county. CA-44 lies inside Los Angeles County
(about 10 million people), where county figures would describe the county rather than the district.
The CA-44 Atlas therefore builds the district up from census blocks, tracts, and cities:

- **Population and land** for each plan: sums of 2020 census blocks.
- **Cities and places**: each block's place code from the 2020 Census.
- **ACS figures for the 2021 lines**: the Census Bureau's own district tabulation.
- **Unemployment**: BLS monthly series for each city in either plan (whole-city figures).
- **Ports**: Corps of Engineers dock locations tested against each plan, and each port's own
  monthly container counts.
- **ACS figures for the new lines**: an estimate by the atlas from census tracts, labeled "est.",
  with its error measured against the Census Bureau's figures for the 2021 lines.

## Run it

```bash
pip install -r requirements.txt
npm install
python -m pipeline build --district ca-44     # writes data/ca-44/
python -m pytest -q
bash scripts/build-site.sh                    # copies site/ and data/ca-44 into _site/
python -m http.server -d _site 8000
```

Secrets for GitHub Actions: `CENSUS_API_KEY`, `FEC_API_KEY`, and `BLS_API_KEY`. Keys are removed from
every logged request.

## How the site is served

Cloudflare Pages builds the site from the `main` branch with `bash scripts/build-site.sh` (output
folder `_site`), so each data refresh that changes a file publishes itself. No deploy secret is stored
in this repository.

## Not yet built

Jobs by industry for cities, Port budgets and Harbor Commission records, Caltrans projects,
state election results for the 2026 general election (after certification), and Los Angeles
neighborhood boundaries within the city's part of the district.

## License

Code: MIT (see [LICENSE](LICENSE)). Text and compiled tables: CC BY 4.0 (see
[LICENSE-CONTENT.md](LICENSE-CONTENT.md)). Federal records are in the public domain; port-reported
figures and compiled election results keep their publishers' terms. Cite the primary sources listed
in each data file.
