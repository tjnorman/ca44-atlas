"""Unit tests for the CA-44 sources, using small files in the real Census layouts."""

from __future__ import annotations

import io
import zipfile

import pytest

from pipeline import config
from pipeline.sources import acs_plan, plans


def zip_of(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_config_loads():
    d = config.load("ca-44")
    assert d.geoid == "0644" and d.raw["geography"] == "plans"
    ids = [p["id"] for p in d.raw["plans"]]
    assert ids == ["cd120", "cd119"] and sum(1 for p in d.raw["plans"] if p.get("primary")) == 1


def test_read_bef_national_layout_with_crlf():
    raw = zip_of("NationalCD119.txt", "GEOID,CDFP\r\n060370001001000,44\r\n060370001001001,43\r\n010010201001000,01\r\n")
    blocks, in_state = plans.read_bef(raw, "NationalCD119.txt", "06", "44")
    assert blocks == {"060370001001000"} and in_state == 2


def test_read_bef_state_layout():
    raw = zip_of("CD120_06.txt", "GEOID,STATEFP,COUNTYFP,TRACTCE,BLOCKCE,CDFP\n"
                                 "060370001001000,06,037,000100,1000,44\n060370001001001,06,037,000100,1001,44\n")
    blocks, _ = plans.read_bef(raw, "CD120_06.txt", "06", "44")
    assert len(blocks) == 2


def test_read_bef_rejects_wrong_layout():
    with pytest.raises(ValueError):
        plans.read_bef(zip_of("x.txt", "BLOCK,DISTRICT\n1,2\n"), "x.txt", "06", "44")


def test_summarize_plan_places_and_tracts():
    pl = {"blocks": {"060370001001000": 100, "060370001001001": 50, "060370002001000": 30},
          "block_place": {"060370001001000": "11111", "060370001001001": "99999", "060370002001000": "11111"},
          "names": {"11111": "Sample city"}, "places": {"11111": 1000}}
    area = {g: (2_589_988, 0, -118.0, 34.0) for g in pl["blocks"]}
    tract_pop = {"06037000100": 150, "06037000200": 60}
    s = plans.summarize_plan({"060370001001000", "060370001001001", "060370002001000"}, pl, area, tract_pop)
    assert s["pop_2020"] == 180 and round(s["land_sq_mi"], 3) == 3.0
    city = next(r for r in s["places"] if r["place"] == "11111")
    assert city["pop_in_district"] == 130 and city["short"] == "Sample" and city["type"] == "city"
    assert (city["label_lon"], city["label_lat"]) == (-118.0, 34.0)
    assert sum(r["pop_in_district"] for r in s["places"]) == s["pop_2020"]
    weights = {t["tract"]: t["weight"] for t in s["tracts"]}
    assert weights["06037000100"] == 1.0 and weights["06037000200"] == 0.5


def test_weighted_row_sums_counts_and_skips_medians():
    rows = {"A": {"B01003_001E": 1000, "B01003_001M": 100, "B19013_001E": 50000},
            "B": {"B01003_001E": 2000, "B01003_001M": 200, "B19013_001E": 90000}}
    est, moe = acs_plan.weighted_row(rows, {"A": 1.0, "B": 0.5}, ["B01003_001E", "B19013_001E"])
    assert est["B01003_001E"] == 2000 and "B19013_001E" not in est
    assert round(moe["B01003_001E"], 3) == round((100 ** 2 + 100 ** 2) ** 0.5, 3)


def test_place_names():
    assert plans.short_place("Florence-Graham CDP") == "Florence-Graham"
    assert plans.place_type("Los Angeles city") == "city" and plans.place_type("West Carson CDP") == "CDP"


def test_fold_ignores_accents():
    from pipeline.checks import fold
    assert fold("Barragán") == fold("BARRAGAN") == "barragan"


def test_canonical_names_fixes_accents_and_damage():
    from pipeline.sources.elections import canonical_names, surname
    res = [{"year": 2016, "candidates": [{"name": "Nanette Diaz Barrag�___�__�n"}]},
           {"year": 2018, "candidates": [{"name": "Nanette Diaz Barragán"}]},
           {"year": 2020, "candidates": [{"name": "Nanette Diaz Barragan"}]}]
    assert canonical_names(res) == 2
    assert {r["candidates"][0]["name"] for r in res} == {"Nanette Diaz Barragán"}
    assert res[0]["candidates"][0]["original_name"].startswith("Nanette Diaz Barrag")
    assert surname("Nanette Diaz Barragán") == surname("NANETTE DIAZ BARRAGAN")


POLA_HTML = """<table><tr><td></td><td></td></tr></table><table>
<tr><td></td><td>Loaded Imports</td><td>Empty Imports</td><td>Total Imports</td><td>Loaded Exports</td><td>Empty Exports</td><td>Total Exports</td><td>Total TEUs</td><td>Prior Year Change</td></tr>
<tr><td>January</td><td>421,593.75</td><td>115.00</td><td>421,708.75</td><td>104,297.00</td><td>285,994.50</td><td>390,291.50</td><td>812,000.25</td><td>-12.14%</td></tr>
<tr><td>February</td><td>433,812.25</td><td>17.25</td><td>433,829.50</td><td>116,633.25</td><td>273,860.50</td><td>390,493.75</td><td>824,323.25</td><td>2.86%</td></tr>
<tr><td>March</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>Total Calendar Year 2026</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1,636,323.50</td><td>1%</td></tr>
<tr><td>Total Fiscal Year 2026/27 (FY in progress)</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1</td><td>9</td><td>1%</td></tr></table>"""

POLB_CY_HTML = """<table><tr><th>Month</th><th>Loaded Inbound</th><th>Loaded Outbound</th><th>Empties Inbound</th><th>Empties Outbound</th><th>Total</th></tr>
<tr><td>January</td><td>409,818</td><td>99,478</td><td>16,273</td><td>322,197</td><td>847,765</td></tr>
<tr><td>February</td><td>368,060</td><td>97,422</td><td>15,618</td><td>286,426</td><td>767,525</td></tr>
<tr><td>March</td><td></td><td></td><td></td><td></td><td></td></tr>
<tr><td>Year-to-Date</td><td>1</td><td>1</td><td>1</td><td>1</td><td>1,615,290</td></tr>
<tr><td>YTD % Change</td><td>6.4%</td><td>8.4%</td><td>5.1%</td><td>1.3%</td><td>4.7%</td></tr></table>"""

POLB_RECENT_HTML = """<table><tr><th>Date</th><th>Loaded Inbound</th><th>Loaded Outbound</th><th>Total Loaded</th><th>Empty Inbound</th><th>Empty Outbound</th><th>Total Empties</th><th>Total</th></tr>
<tr><td>Feb 2026</td><td>368,060</td><td>97,422</td><td>465,482</td><td>15,618</td><td>286,426</td><td>302,044</td><td>767,525</td></tr>
<tr><td>Jan 2026</td><td>409,818</td><td>99,478</td><td>509,296</td><td>16,273</td><td>322,197</td><td>338,470</td><td>847,765</td></tr></table>"""


def test_parse_pola_year():
    from pipeline.sources.ports import parse_pola_year
    p = parse_pola_year(POLA_HTML, 2026)
    assert [m["month"] for m in p["months"]] == ["2026-01", "2026-02"]
    assert p["months"][0]["loaded_imports"] == 421593.75 and p["calendar_year_total"] == 1636323.5
    assert abs(sum(m["total"] for m in p["months"]) - p["calendar_year_total"]) < 1


def test_parse_polb_tables():
    from pipeline.sources.ports import parse_polb_cy, parse_polb_recent
    cy = parse_polb_cy(POLB_CY_HTML, 2026)
    assert len(cy["months"]) == 2 and cy["year_to_date"] == 1615290
    assert cy["months"][1]["empty_exports"] == 286426
    rec = parse_polb_recent(POLB_RECENT_HTML)
    assert [m["month"] for m in rec] == ["2026-01", "2026-02"] and rec[1]["total"] == 767525


def test_laus_series_ids_and_gaps():
    from pipeline.sources.laus import city_series, county_series, missing_months, state_series
    assert city_series("06", "44000") == "LAUCT064400000000003" and len(city_series("06", "44000")) == 20
    assert county_series("06", "037") == "LAUCN060370000000003" and state_series("06") == "LAUST060000000000003"
    assert missing_months([{"date": "2025-09"}, {"date": "2025-11"}]) == ["2025-10"]


def test_pola_documented_correction():
    from pipeline.sources.ports import parse_pola_year
    html = POLA_HTML.replace("824,323.25", "824.,323.25")
    p = parse_pola_year(html, 2026, {"2026-02": {"shown": "824.,323.25", "value": 824323.25}})
    assert len(p["months"]) == 2 and p["corrections"][0]["used"] == 824323.25
    p2 = parse_pola_year(html, 2026, {})
    assert len(p2["months"]) == 1


def test_clean_operators_drops_phone_numbers():
    from pipeline.sources.ports import clean_operators
    out = clean_operators("Current Operator: American President Lines, Ltd. Phone: 310-548-8700 FAX: 310-548-8890")
    assert out == "American President Lines, Ltd" and "310" not in out


def test_read_state_bef_no_header_with_bom():
    raw = zip_of("AB604.csv", '\ufeff"060370001001000","44"\r\n"060370001001001","43"\r\n"060650444033050","25"\r\n')
    blocks, total = plans.read_state_bef(raw, "AB604.csv", "44")
    assert blocks == {"060370001001000"} and total == 3


def test_read_state_bef_rejects_other_layouts():
    with pytest.raises(ValueError):
        plans.read_state_bef(zip_of("AB604.csv", "GEOID,CDFP\n060370001001000,44\n"), "AB604.csv", "44")


def test_projects_every_fact_sourced():
    from pipeline import config
    from pipeline.sources import projects
    payload, sources, checks = projects.fetch(None, config.load("ca-44"))
    p = payload["projects"][0]
    assert p["id"] == "vincent-thomas-bridge" and checks[0]["status"] in ("pass", "warn")
    ids = {s.id for s in sources}
    assert all(f["source"] in ids for f in p["facts"] + p["timeline"])


def test_cameras_parse_cwwp2_layout():
    from pipeline.sources.cameras import parse
    raw = {"data": [{"cctv": {"index": "950", "inService": "true",
                              "location": {"locationName": "SR-47 : (950) I-110", "nearbyPlace": "San Pedro", "route": "SR-47",
                                           "latitude": "33.75", "longitude": "-118.27", "county": "Los Angeles", "direction": "East"},
                              "imageData": {"streamingVideoURL": "https://wzmedia.dot.ca.gov/D7/CCTV-950.stream/playlist.m3u8",
                                            "static": {"currentImageURL": "https://cwwp2.dot.ca.gov/x.jpg", "currentImageUpdateFrequency": "2"}}}}]}
    c = parse(raw)[0]
    assert c["id"] == "950" and c["in_service"] and c["route"] == "SR-47" and c["lat"] == 33.75
    import pytest
    with pytest.raises(ValueError):
        parse({"data": [{"camera": {}}]})


def test_airports_dms():
    from pipeline.sources.airports import dms
    assert abs(dms(34, 29, 12.3) - 34.48675) < 1e-5
