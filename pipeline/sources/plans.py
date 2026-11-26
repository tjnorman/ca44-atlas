"""Where the district is, for each district plan (map) the atlas follows.

Built for a district that lies inside one large county, where county figures would describe the
county rather than the district. Everything is built up from 2020 Census blocks:

  1. Census Bureau block equivalency files (BEFs) assign every 2020 census block to a district,
     one file per plan (for example the 119th Congress plan and the 120th Congress plan).
  2. The 2020 Census redistricting data (P.L. 94-171) give each block's population and the city
     or census-designated place it belongs to.
  3. TIGER/Line 2020 block shapes give land and water area and, dissolved, each district's outline.

Each plan's population, land area, cities, and census tracts come from those three files. Where a
Census product reports the same thing for a plan directly (the 2020 Census tabulation and the
Gazetteer for the 119th Congress), the build compares the two.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .. import census
from ..config import District
from ..http import Fetcher, FetchError
from ..provenance import Source

SQ_M_PER_SQ_MI = 2_589_988.110336
PL_ZIP = ("https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/"
          "{state_name}/{abbr}2020.pl.zip")
TIGER_BLOCKS = "https://www2.census.gov/geo/tiger/TIGER2020PL/LAYER/TABBLOCK/2020/tl_2020_{st}{co}_tabblock20.zip"
GENZ_PLACE = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_{st}_place_500k.zip"
GENZ_COUNTY = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_county_500k.zip"
GAZ = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/{y}_Gazetteer/{y}_Gaz_{c}CDs_national.zip"

# 2020 P.L. 94-171 geographic header: 0-based positions of the fields used. The build confirms the
# layout by reading the state's own record (summary level 040) before trusting any other row.
GEO = {"sumlev": 2, "logrecno": 7, "geoid": 8, "state": 12, "county": 14, "place": 29, "placecc": 30,
       "tract": 32, "block": 34, "name": 87}
POP_COL = 5  # P0010001 (total population) in segment 1


def read_bef(raw: bytes, member: str, state_fips: str, district: str) -> tuple[set[str], int]:
    """Blocks assigned to one district in a Census block equivalency file, and the state's block count.

    Handles both layouts Census uses: GEOID,CDFP (national files) and
    GEOID,STATEFP,COUNTYFP,TRACTCE,BLOCKCE,CDFP (state files of the 120th Congress)."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        if member not in names:
            raise FetchError(f"{member} is not in the block equivalency file (has {', '.join(names[:12])})")
        text = io.TextIOWrapper(z.open(member), encoding="utf-8-sig", newline="")
        reader = csv.reader(text)
        header = [h.strip().upper() for h in next(reader)]
        if "GEOID" not in header or "CDFP" not in header:
            raise ValueError(f"Unexpected block equivalency layout in {member}: {header}")
        gi, ci = header.index("GEOID"), header.index("CDFP")
        blocks, in_state = set(), 0
        for row in reader:
            if not row:
                continue
            g = row[gi].strip()
            if not g.startswith(state_fips):
                continue
            in_state += 1
            if row[ci].strip() == district:
                blocks.add(g)
    return blocks, in_state


def read_pl(raw: bytes, abbr: str, state_name: str, counties: set[str]) -> dict:
    """Block populations and places for the given counties, plus state, county, and place totals."""
    abbr = abbr.lower()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        geo_rows = io.TextIOWrapper(z.open(f"{abbr}geo2020.pl"), encoding="latin-1")
        seg1 = io.TextIOWrapper(z.open(f"{abbr}000012020.pl"), encoding="latin-1")
        want: dict[str, tuple] = {}   # logrecno -> (kind, key)
        names: dict[str, str] = {}
        place_cc: dict[str, str] = {}
        block_place: dict[str, str] = {}
        state_ok = False
        for line in geo_rows:
            p = line.rstrip("\n").split("|")
            lev = p[GEO["sumlev"]]
            if lev == "040":
                if p[GEO["name"]] != state_name:
                    raise ValueError(f"P.L. 94-171 header layout changed: state record name is {p[GEO['name']]!r}")
                state_ok = True
                want[p[GEO["logrecno"]]] = ("state", "")
            elif lev == "050" and p[GEO["county"]] in counties:
                want[p[GEO["logrecno"]]] = ("county", p[GEO["county"]])
                names["county:" + p[GEO["county"]]] = p[GEO["name"]]
            elif lev == "160":
                want[p[GEO["logrecno"]]] = ("place", p[GEO["place"]])
                names[p[GEO["place"]]] = p[GEO["name"]]
                place_cc[p[GEO["place"]]] = p[GEO["placecc"]]
            elif lev == "750" and p[GEO["county"]] in counties:
                g = p[GEO["geoid"]].split("US")[-1]
                if len(g) != 15:
                    raise ValueError(f"Unexpected block GEOID in P.L. 94-171 header: {p[GEO['geoid']]!r}")
                want[p[GEO["logrecno"]]] = ("block", g)
                block_place[g] = p[GEO["place"]]
        if not state_ok:
            raise ValueError("No state record in the P.L. 94-171 header")
        out = {"state": None, "counties": {}, "places": {}, "blocks": {}}
        for line in seg1:
            p = line.split("|", POP_COL + 2)
            hit = want.get(p[4])
            if not hit:
                continue
            kind, key = hit
            pop = int(p[POP_COL])
            if kind == "state":
                out["state"] = pop
            elif kind == "county":
                out["counties"][key] = pop
            elif kind == "place":
                out["places"][key] = pop
            else:
                out["blocks"][key] = pop
    out["names"] = names
    out["place_cc"] = place_cc
    out["block_place"] = block_place
    return out


def place_type(name: str) -> str:
    n = name.lower()
    for suffix, kind in ((" cdp", "CDP"), (" city", "city"), (" town", "town")):
        if n.endswith(suffix):
            return kind
    return "place"


def short_place(name: str) -> str:
    for suffix in (" city", " CDP", " town"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def tiger_blocks(raw: bytes) -> tuple[pathlib.Path, dict[str, tuple[int, int]], tempfile.TemporaryDirectory]:
    """Unpack a TIGER/Line block file; return its shapefile path and land and water area by block."""
    import shapefile  # pyshp

    tmp = tempfile.TemporaryDirectory()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        z.extractall(tmp.name)
    shp = next(pathlib.Path(tmp.name).glob("*.shp"))
    reader = shapefile.Reader(str(shp))
    fields = [f[0] for f in reader.fields[1:]]
    for need in ("GEOID20", "ALAND20", "AWATER20"):
        if need not in fields:
            raise ValueError(f"TIGER block file lacks {need}")
    area = {rec["GEOID20"]: (int(rec["ALAND20"]), int(rec["AWATER20"]))
            for rec in reader.iterRecords(fields=["GEOID20", "ALAND20", "AWATER20"])}
    return shp, area, tmp


def _mapshaper() -> str:
    return shutil.which("mapshaper") or str(pathlib.Path("node_modules/.bin/mapshaper").resolve())


def dissolve(shp: pathlib.Path, assign: dict[str, list[str]], workdir: pathlib.Path) -> dict[str, dict]:
    """Dissolve blocks into one outline per plan. assign: plan id -> block GEOIDs."""
    out = {}
    for pid, blocks in assign.items():
        keys = workdir / f"{pid}.csv"
        keys.write_text("GEOID20,keep\n" + "".join(f"{g},1\n" for g in sorted(blocks)))
        dest = workdir / f"{pid}.json"
        subprocess.run([_mapshaper(), "-i", str(shp), "-join", str(keys), "keys=GEOID20,GEOID20",
                        "field-types=GEOID20:str", "-filter", "keep==1", "-dissolve2",
                        "-o", "format=geojson", str(dest)], check=True, capture_output=True)
        geo = json.loads(dest.read_text())
        feats = geo["features"] if geo.get("type") == "FeatureCollection" else (
            [{"type": "Feature", "properties": {}, "geometry": g} for g in geo.get("geometries", [])])
        for f in feats:
            f["properties"] = {"plan": pid}
        out[pid] = {"type": "FeatureCollection", "features": feats}
    return out


def _shapes(zip_bytes: bytes, keep) -> list[dict]:
    import shapefile

    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "layer.zip"
        p.write_bytes(zip_bytes)
        reader = shapefile.Reader(str(p))
        fields = [f[0] for f in reader.fields[1:]]
        return [{"type": "Feature", "properties": dict(zip(fields, sr.record)), "geometry": sr.shape.__geo_interface__}
                for sr in reader.iterShapeRecords() if keep(dict(zip(fields, sr.record)))]


def gazetteer_land(fetcher: Fetcher, congress: int, geoid: str) -> tuple[float | None, str | None]:
    year_now = datetime.now(timezone.utc).year
    for y in (year_now, year_now - 1, year_now - 2):
        url = GAZ.format(y=y, c=congress)
        try:
            raw = fetcher.fetch(url, retries=1)
        except FetchError:
            continue
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read(next(n for n in z.namelist() if n.endswith(".txt"))).decode("utf-8", "replace")
        for row in csv.DictReader(io.StringIO(text), delimiter="|" if "|" in text.splitlines()[0] else "\t"):
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if row.get("GEOID") == geoid:
                return float(row["ALAND_SQMI"]), url
    return None, None


def census_tabulation(fetcher: Fetcher, congress: int, d: District) -> tuple[int | None, str | None]:
    """2020 Census population of the district as the Census Bureau tabulated it for that Congress."""
    ds = f"2020/dec/cd{congress}"
    try:
        rows = census.query(fetcher, ds, ["P1_001N"], f"congressional district:{d.district}", f"state:{d.state_fips}")
        return (int(rows[0]["P1_001N"]) if rows else None), ds
    except (FetchError, KeyError, IndexError, ValueError):
        return None, None


def summarize_plan(blocks: set[str], pl: dict, area: dict[str, tuple[int, int]], tract_pop: dict[str, int]) -> dict:
    pop = {g: pl["blocks"].get(g) for g in blocks}
    missing = [g for g, v in pop.items() if v is None]
    places = Counter()
    tracts = Counter()
    for g, v in pop.items():
        places[pl["block_place"].get(g, "99999")] += v or 0
        tracts[g[:11]] += v or 0
    land = sum(area.get(g, (0, 0))[0] for g in blocks)
    water = sum(area.get(g, (0, 0))[1] for g in blocks)
    place_rows = []
    for code, n in places.most_common():
        if code == "99999":
            place_rows.append({"place": None, "name": "Unincorporated area outside any census place", "short": "Other unincorporated",
                               "type": "unincorporated", "pop_in_district": n, "pop_place": None, "share_of_place": None})
            continue
        name = pl["names"].get(code, code)
        total = pl["places"].get(code)
        place_rows.append({"place": code, "name": name, "short": short_place(name), "type": place_type(name),
                           "pop_in_district": n, "pop_place": total,
                           "share_of_place": (n / total) if total else None})
    tract_rows = [{"tract": t, "pop_in_district": n, "pop_tract": tract_pop.get(t),
                   "weight": (n / tract_pop[t]) if tract_pop.get(t) else 0.0}
                  for t, n in sorted(tracts.items())]
    return {
        "blocks": len(blocks),
        "blocks_missing_population": len(missing),
        "pop_2020": sum(v or 0 for v in pop.values()),
        "land_sq_mi": land / SQ_M_PER_SQ_MI,
        "water_sq_mi": water / SQ_M_PER_SQ_MI,
        "counties": sorted({g[2:5] for g in blocks}),
        "places": place_rows,
        "tracts": tract_rows,
    }


def fetch(fetcher: Fetcher, d: District, out_dir: pathlib.Path) -> tuple[dict, list[Source], list[dict]]:
    plans_cfg = d.raw.get("plans") or []
    if not plans_cfg:
        raise ValueError("No plans configured for this district")
    counties = set(d.raw.get("county_fips") or [])
    if not counties:
        raise ValueError("county_fips must list the county or counties the district can fall in")

    sources: list[Source] = []
    blocks: dict[str, set[str]] = {}
    bef_info: dict[str, dict] = {}
    checks: list[dict] = []
    bef_cache: dict[str, bytes] = {}
    for p in plans_cfg:
        raw = bef_cache.get(p["bef_zip"]) or fetcher.fetch(p["bef_zip"])
        bef_cache[p["bef_zip"]] = raw
        blocks[p["id"]], in_state = read_bef(raw, p["bef_member"], d.state_fips, d.district)
        bef_info[p["id"]] = {"state_blocks": in_state}
        if p.get("bef_cross_member"):   # the same plan in a second file in the same release
            alt, _ = read_bef(raw, p["bef_cross_member"], d.state_fips, d.district)
            same = alt == blocks[p["id"]]
            checks.append({"id": f"bef-files-{p['id']}", "title": f"Two Census block files give the same blocks for the {p['short']}",
                           "status": "pass" if same else "fail", "sources": [f"census-bef-{p['congress']}"], "values": {},
                           "detail": f"{p['bef_member']} and {p['bef_cross_member']} each assign {len(blocks[p['id']]):,} "
                                     f"and {len(alt):,} blocks to district {d.district}"
                                     + ("; the lists are identical." if same else "; the lists differ.")})
        if not blocks[p["id"]]:
            raise ValueError(f"No blocks assigned to district {d.district} in {p['bef_member']}")
        sources.append(Source(
            id=f"census-bef-{p['congress']}", publisher="U.S. Census Bureau",
            title=f"{p['congress']}th Congressional District block equivalency files", url=p["bef_page"],
            year=str(p.get("bef_year", "")), vintage=f"{p['congress']}th Congress",
            query=p["bef_zip"] + f" ({p['bef_member']})",
            notes=p.get("bef_note", "Whole 2020 census blocks assigned to each district of the plan, as submitted by the state.")))

    pl_url = PL_ZIP.format(state_name=d.state_name.replace(" ", "_"), abbr=d.state_abbr.lower())
    pl = read_pl(fetcher.fetch(pl_url), d.state_abbr, d.state_name, counties)
    sources.append(Source(id="census-pl", publisher="U.S. Census Bureau",
                          title="2020 Census Redistricting Data (Public Law 94-171) Summary File", url=pl_url,
                          year="2021", vintage="2020 Census", query=pl_url,
                          notes="Block, place, county, and state population counts as of April 1, 2020."))
    tract_pop = Counter()
    for g, v in pl["blocks"].items():
        tract_pop[g[:11]] += v

    county = sorted(counties)[0]
    braw = fetcher.fetch(TIGER_BLOCKS.format(st=d.state_fips, co=county))
    shp, area, tmp = tiger_blocks(braw)
    sources.append(Source(id="census-tiger-blocks", publisher="U.S. Census Bureau",
                          title="TIGER/Line Shapefiles, 2020 census tabulation blocks (P.L. 94-171 release)",
                          url=TIGER_BLOCKS.format(st=d.state_fips, co=county), year="2020", vintage="2020",
                          query=TIGER_BLOCKS.format(st=d.state_fips, co=county),
                          notes="Block outlines with land and water area; district outlines are these blocks dissolved."))

    plans_out: dict[str, dict] = {}
    for p in plans_cfg:
        s = summarize_plan(blocks[p["id"]], pl, area, tract_pop)
        outside = [c for c in s["counties"] if c not in counties]
        if outside:
            raise ValueError(f"Plan {p['id']} has blocks outside the configured counties: {outside}")
        plans_out[p["id"]] = {**{k: p.get(k) for k in ("id", "label", "short", "congress", "effective", "first_election",
                                                     "last_election", "law", "primary")}, **s, **bef_info[p["id"]]}

    # Overlap between plans (the first two configured)
    overlap = None
    if len(plans_cfg) >= 2:
        a, b = plans_cfg[0]["id"], plans_cfg[1]["id"]
        both = blocks[a] & blocks[b]
        only_a, only_b = blocks[a] - blocks[b], blocks[b] - blocks[a]
        pop = lambda S: sum(pl["blocks"].get(g, 0) for g in S)

        def by_place(S):
            c = Counter()
            for g in S:
                c[pl["block_place"].get(g, "99999")] += pl["blocks"].get(g, 0)
            return [{"place": k if k != "99999" else None,
                     "name": short_place(pl["names"].get(k, "Other unincorporated")) if k != "99999" else "Other unincorporated",
                     "pop": v} for k, v in c.most_common() if v > 0]
        overlap = {"a": a, "b": b, "pop_both": pop(both), "pop_only_a": pop(only_a), "pop_only_b": pop(only_b),
                   "blocks_both": len(both), "places_only_a": by_place(only_a), "places_only_b": by_place(only_b)}

    # Shapes
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as wd:
        wdp = pathlib.Path(wd)
        outlines = dissolve(shp, {p["id"]: blocks[p["id"]] for p in plans_cfg}, wdp)
        year_now = datetime.now(timezone.utc).year
        places_fc = county_fc = None
        place_codes = {r["place"] for pid in plans_out for r in plans_out[pid]["places"] if r["place"]}
        for y in (year_now - 1, year_now - 2, year_now - 3):
            try:
                place_zip = fetcher.fetch(GENZ_PLACE.format(y=y, st=d.state_fips), retries=1)
                county_zip = fetcher.fetch(GENZ_COUNTY.format(y=y), retries=1)
            except FetchError:
                continue
            places_fc = [f for f in _shapes(place_zip, lambda pr: str(pr.get("PLACEFP")) in place_codes)]
            county_fc = [f for f in _shapes(county_zip, lambda pr: str(pr.get("STATEFP")) == d.state_fips
                                            and str(pr.get("COUNTYFP")) in counties)]
            cb_year = y
            break
        else:
            raise FetchError("No cartographic place or county file found")
        for f in places_fc:
            pr = f["properties"]
            f["properties"] = {"place": pr.get("PLACEFP"), "name": pr.get("NAME"), "type": place_type(pr.get("NAMELSAD") or "")}
        for f in county_fc:
            f["properties"] = {"county_fips": f["properties"].get("COUNTYFP"), "name": f["properties"].get("NAME")}
        layers = {**{f"plan_{pid}": fc for pid, fc in outlines.items()},
                  "places": {"type": "FeatureCollection", "features": places_fc},
                  "counties": {"type": "FeatureCollection", "features": county_fc}}
        files = []
        for name, fc in layers.items():
            path = wdp / f"{name}.json"
            path.write_text(json.dumps(fc))
            files.append(str(path))
        subprocess.run([_mapshaper(), "-i", *files, "combine-files", "-simplify", "20%", "keep-shapes",
                        "-o", "format=topojson", "quantization=100000", str(out_dir / "district.topo.json")],
                       check=True, capture_output=True)
        (wdp / "simple").mkdir()
        subprocess.run([_mapshaper(), "-i", *files, "combine-files", "-simplify", "10%", "keep-shapes",
                        "-o", "format=geojson", "precision=0.00001", str(wdp / "simple") + "/"],
                       check=True, capture_output=True)
        simple = {}
        for name in layers:
            path = wdp / "simple" / f"{name}.json"
            if path.exists():
                simple[name] = json.loads(path.read_text())
        primary = next(p["id"] for p in plans_cfg if p.get("primary")) if any(p.get("primary") for p in plans_cfg) else plans_cfg[0]["id"]
        # "district" holds every plan's outline, so point tests keep places inside either plan;
        # records are then tagged with the plans that contain them.
        simple["district"] = {"type": "FeatureCollection",
                              "features": [f for pid in (p["id"] for p in plans_cfg) for f in simple[f"plan_{pid}"]["features"]]}
        simple["primary"] = primary
        (out_dir / "district.simple.geojson.json").write_text(json.dumps(simple, separators=(",", ":")))
    tmp.cleanup()
    sources.append(Source(id="census-cb", publisher="U.S. Census Bureau",
                          title=f"Cartographic Boundary Files, {cb_year}: places and counties (1:500,000)",
                          url=GENZ_PLACE.format(y=cb_year, st=d.state_fips), year=str(cb_year), vintage=str(cb_year),
                          query=GENZ_PLACE.format(y=cb_year, st=d.state_fips), notes="City and county outlines for the map."))

    # Cross-checks against Census products that report a plan directly
    for p in plans_cfg:
        po = plans_out[p["id"]]
        tab, ds = census_tabulation(fetcher, p["congress"], d) if p.get("census_tabulated") else (None, None)
        po["pop_2020_census_tabulation"] = tab
        if p.get("census_tabulated"):
            checks.append({"id": f"pop-2020-{p['id']}", "title": f"Block counts reproduce the Census Bureau's own 2020 population for the {p['short']}",
                           "status": "pass" if tab == po["pop_2020"] else ("skip" if tab is None else "fail"),
                           "sources": ["census-bef-%d" % p["congress"], "census-pl", f"census-cd{p['congress']}"],
                           "values": {"blocks": po["pop_2020"], "tabulation": tab},
                           "detail": (f"Sum of {po['blocks']:,} blocks: {po['pop_2020']:,}; Census {ds} tabulation: "
                                      f"{tab:,}." if tab is not None else "Census tabulation unavailable in this build.")})
            sources.append(Source(id=f"census-cd{p['congress']}", publisher="U.S. Census Bureau",
                                  title=f"2020 Census, {p['congress']}th Congressional District Summary File",
                                  url=f"https://api.census.gov/data/2020/dec/cd{p['congress']}", year="2023",
                                  vintage="2020 Census", query=f"https://api.census.gov/data/2020/dec/cd{p['congress']}?get=P1_001N",
                                  notes="Population as tabulated by the Census Bureau for the plan."))
        if p.get("gazetteer"):
            g, url = gazetteer_land(fetcher, p["congress"], d.geoid)
            po["land_sq_mi_gazetteer"] = g
            ok = g is not None and abs(po["land_sq_mi"] - g) / g < 0.005
            checks.append({"id": f"land-area-{p['id']}", "title": f"Block land area matches the Census Gazetteer for the {p['short']}",
                           "status": "pass" if ok else ("skip" if g is None else "fail"),
                           "sources": [f"census-bef-{p['congress']}", "census-tiger-blocks", "census-gaz"],
                           "values": {"blocks": po["land_sq_mi"], "gazetteer": g},
                           "detail": (f"Blocks: {po['land_sq_mi']:.2f} sq mi of land; Gazetteer: {g:.2f} sq mi "
                                      f"(tolerance 0.5%; the Gazetteer uses a newer boundary vintage)." if g else
                                      "Gazetteer unavailable in this build.")})
            if url:
                sources.append(Source(id="census-gaz", publisher="U.S. Census Bureau",
                                      title=f"Gazetteer Files: {p['congress']}th Congressional Districts", url=url,
                                      year=url.split("/")[-2][:4], query=url, notes="Land and water area by district."))
        exp = (d.expectations.get("pop_2020") or {}).get(p["id"])
        if exp is not None:
            checks.append({"id": f"pop-recorded-{p['id']}", "title": f"2020 population for the {p['short']} matches the recorded figure",
                           "status": "pass" if exp == po["pop_2020"] else "fail", "sources": ["census-pl"],
                           "values": {"blocks": po["pop_2020"], "recorded": exp},
                           "detail": f"Blocks: {po['pop_2020']:,}; recorded {exp:,} ({d.expectations.get('pop_2020_source', '')})."})
        ideal = pl["state"] / int(d.raw.get("districts_in_state", 1))
        dev = po["pop_2020"] / ideal - 1
        checks.append({"id": f"equal-pop-{p['id']}", "title": f"The {p['short']} holds about one equal share of the state's people",
                       "status": "pass" if abs(dev) < 0.01 else "warn", "sources": ["census-pl"],
                       "values": {"pop": po["pop_2020"], "ideal": ideal, "deviation": dev},
                       "detail": (f"{po['pop_2020']:,} people against an equal share of {ideal:,.0f} "
                                  f"({d.state_name}'s {pl['state']:,} divided by {d.raw.get('districts_in_state')}): {dev:+.2%}. "
                                  "Tolerance 1%; states may balance districts on adjusted counts, so a small gap is expected.")})
        covered = sum(r["pop_in_district"] for r in po["places"])
        checks.append({"id": f"places-cover-{p['id']}", "title": f"Cities and places add up to the whole {p['short']}",
                       "status": "pass" if covered == po["pop_2020"] and not po["blocks_missing_population"] else "fail",
                       "sources": ["census-pl"], "values": {},
                       "detail": f"{len(po['places'])} places and unincorporated remainder sum to {covered:,}; district {po['pop_2020']:,}; "
                                 f"blocks without a population record: {po['blocks_missing_population']}."})

    payload = {
        "primary": next((p["id"] for p in plans_cfg if p.get("primary")), plans_cfg[0]["id"]),
        "plans": plans_out,
        "overlap": overlap,
        "state_pop_2020": pl["state"],
        "county_pop_2020": pl["counties"],
        "county_names": {k.split(":")[1]: v for k, v in pl["names"].items() if k.startswith("county:")},
        "as_of": datetime.now(timezone.utc).date().isoformat(),
    }
    return payload, sources, checks
