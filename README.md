# CA-44 Atlas

California's 44th Congressional District, counted. A nonpartisan, sourced record of the seat:
who lives in it, what the federal government spends there, and how it is represented.

**Status: private working draft (Nov. 26, 2026).** Nothing here is published. The publisher reviews
the data and the site before the repository or any page is made public.

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
- **ACS figures for the new lines**: an estimate by the atlas from census tracts, labeled "est.",
  with its error measured against the Census Bureau's figures for the 2021 lines.

## Run it

```bash
pip install -r requirements.txt
npm install
python -m pipeline build --district ca-44     # writes data/ca-44/
python -m pytest -q
python -m http.server -d site 8000            # after copying or linking data/ca-44 to site/data
```

Optional secrets for GitHub Actions: `CENSUS_API_KEY` and `FEC_API_KEY`.

## Not yet built

Unemployment and jobs for cities, Port of Los Angeles and Long Beach records, Caltrans projects,
state election results for the 2026 general election (after certification), and Los Angeles
neighborhood boundaries within the city's part of the district.

## License

Code: MIT (see [LICENSE](LICENSE)). Federal data in `data/` is in the public domain; cite the
primary sources listed in each data file.
