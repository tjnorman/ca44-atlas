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
    area = {g: (2_589_988, 0) for g in pl["blocks"]}
    tract_pop = {"06037000100": 150, "06037000200": 60}
    s = plans.summarize_plan({"060370001001000", "060370001001001", "060370002001000"}, pl, area, tract_pop)
    assert s["pop_2020"] == 180 and round(s["land_sq_mi"], 3) == 3.0
    city = next(r for r in s["places"] if r["place"] == "11111")
    assert city["pop_in_district"] == 130 and city["short"] == "Sample" and city["type"] == "city"
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
