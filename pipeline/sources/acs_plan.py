"""American Community Survey estimates for a district plan the Census Bureau has not tabulated yet.

The Census Bureau publishes ACS estimates for the congressional districts in effect when the survey
year began. For a new plan (for example California's 120th Congress lines, first used in the 2026
election), the atlas builds an estimate from census tracts:

  * Each tract's ACS 5-year counts are multiplied by the share of the tract's 2020 Census population
    that lives in the plan (from the block assignment in plans.json), then summed.
  * Percentages are computed from the summed counts. Medians and averages cannot be summed, so they
    are not estimated for the new plan.
  * The same method is applied to the current plan, which the Census Bureau does tabulate, and the
    two are compared. That comparison is published as the method's measured error.

Every figure from this module is an estimate by the atlas, labeled "est." on the site.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .. import census
from ..config import District
from ..http import Fetcher
from ..provenance import Source
from . import acs

# Medians, per-person figures, and averages: not additive across tracts.
NOT_ADDITIVE = {"B01002_001E", "B19013_001E", "B19301_001E", "B25077_001E", "B25064_001E", "B25010_001E"}
NOT_ESTIMATED = ["median_age", "median_household_income", "per_capita_income", "median_home_value",
                 "median_gross_rent", "avg_household_size"]
# Metrics compared between the method and the Census Bureau's own district figures.
COMPARE = [("population", "count"), ("households", "count"), ("housing_units", "count"), ("poverty_pct", "pct"),
           ("owner_occupied_pct", "pct"), ("bachelors_plus_pct", "pct"), ("under_18_pct", "pct"),
           ("age_65_plus_pct", "pct"), ("uninsured_pct", "pct"), ("broadband_pct", "pct"), ("labor_force_pct", "pct")]
TOL_COUNT = 0.01   # 1% for counts
TOL_PCT = 1.5      # 1.5 percentage points for shares


def weighted_row(rows: dict[str, dict], weights: dict[str, float], variables: list[str]) -> tuple[dict, dict]:
    """Sum tract values times weights. Margins of error combine as the root of summed squares."""
    est: dict[str, float] = {}
    moe: dict[str, float] = {}
    for v in variables:
        if v in NOT_ADDITIVE or not v.endswith("E"):
            continue
        total, sq, seen = 0.0, 0.0, False
        m = v[:-1] + "M"
        for tract, w in weights.items():
            r = rows.get(tract)
            if not r or w <= 0:
                continue
            x = r.get(v)
            if x is None:
                continue
            seen = True
            total += w * x
            mx = r.get(m)
            if mx is not None:
                sq += (w * mx) ** 2
        if seen:
            est[v] = total
            moe[v] = math.sqrt(sq)
    return est, moe


def fetch(fetcher: Fetcher, d: District, plans_payload: dict, acs_payload: dict | None) -> tuple[dict, list[Source], list[dict]]:
    plans = plans_payload["plans"]
    year_now = datetime.now(timezone.utc).year
    counties = sorted({c for p in plans.values() for c in p["counties"]})

    def probe(y: int) -> bool:
        return bool(census.query(fetcher, f"{y}/acs/acs5", ["B01003_001E"], f"county:{counties[0]}", f"state:{d.state_fips}"))

    y5 = census.first_available(fetcher, [year_now - 1, year_now - 2, year_now - 3], probe)
    path = f"{y5}/acs/acs5"
    label_checks, bad, labels = acs.verify_labels(fetcher, path)
    edu = acs.edu_vars(labels)
    want = [v for v in acs.all_variables() if v[:-1] + "E" not in bad and v[:-1] + "E" in labels]
    want += [v[:-1] + "M" for v in want if v.endswith("E")]
    if edu:
        want += [edu["total"], *edu["hs"]]
    want = list(dict.fromkeys(want))

    rows: dict[str, dict] = {}
    for c in counties:
        for r in census.query(fetcher, path, want, "tract:*", f"state:{d.state_fips} county:{c}"):
            rows[f"{r['state']}{r['county']}{r['tract']}"] = r

    out_plans: dict[str, dict] = {}
    missing_tracts: dict[str, list[str]] = {}
    for pid, p in plans.items():
        weights = {t["tract"]: t["weight"] for t in p["tracts"]}
        missing_tracts[pid] = [t for t, w in weights.items() if w > 0 and t not in rows]
        est, moe = weighted_row(rows, weights, want)
        summ = acs.summarize(est, bad, edu)
        for k in NOT_ESTIMATED:
            summ["metrics"][k] = None
        summ["metrics"]["mean_commute_min"] = None if bad.intersection(acs.COMMUTE) else (
            est[acs.COMMUTE[0]] / est[acs.COMMUTE[1]] if est.get(acs.COMMUTE[1]) else None)
        summ["moe"] = {m.id: moe.get(m.num[0]) for m in acs.METRICS if m.moe and not m.den and m.id not in NOT_ESTIMATED}
        out_plans[pid] = {**summ, "tracts_used": sum(1 for t in weights if t in rows),
                          "tracts_partly_inside": sum(1 for w in weights.values() if 0 < w < 0.999)}

    # Method check: the same calculation for the plan Census tabulates, against Census's own figure.
    checks: list[dict] = []
    method = None
    official_pid = next((pid for pid, p in plans.items() if p.get("congress") == d.congress), None)
    official = (acs_payload or {}).get("district_5yr")
    if official_pid and official and (acs_payload or {}).get("vintage", {}).get("acs5") == y5:
        diffs, worst = [], ("", 0.0, "")
        for key, kind in COMPARE:
            a, b = out_plans[official_pid]["metrics"].get(key), official["metrics"].get(key)
            if a is None or b is None:
                continue
            gap = (a - b) / b if kind == "count" else a - b
            ok = abs(gap) <= (TOL_COUNT if kind == "count" else TOL_PCT)
            diffs.append({"metric": key, "kind": kind, "method": a, "census": b, "gap": gap, "ok": ok})
            score = abs(gap) / (TOL_COUNT if kind == "count" else TOL_PCT)
            if score > worst[1]:
                worst = (key, score, kind)
        method = {"plan": official_pid, "acs5": y5, "comparisons": diffs}
        n_ok = sum(1 for x in diffs if x["ok"])
        checks.append({
            "id": "acs-method", "title": "The tract method reproduces the Census Bureau's own figures for the current lines",
            "status": "pass" if diffs and n_ok == len(diffs) else "warn", "sources": ["acs5-tracts", "acs5"],
            "values": {"compared": len(diffs), "within_tolerance": n_ok},
            "detail": (f"Applied to the {plans[official_pid]['short']}, the method is within tolerance on {n_ok} of {len(diffs)} "
                       f"measures (counts within 1%, shares within 1.5 points). "
                       + "; ".join(f"{x['metric']}: method {x['method']:,.1f} vs Census {x['census']:,.1f}"
                                   for x in diffs if not x["ok"])).strip()})
    else:
        checks.append({"id": "acs-method", "title": "The tract method reproduces the Census Bureau's own figures for the current lines",
                       "status": "skip", "sources": ["acs5-tracts", "acs5"], "values": {},
                       "detail": "Not run: the Census Bureau's district figures for the same ACS release were not available."})
    for pid, miss in missing_tracts.items():
        if miss:
            checks.append({"id": f"acs-tracts-{pid}", "title": f"Every tract in the {plans[pid]['short']} has ACS data",
                           "status": "warn", "sources": ["acs5-tracts"], "values": {"missing": len(miss)},
                           "detail": f"{len(miss)} tracts with residents in 2020 returned no ACS row: {', '.join(miss[:8])}."})

    payload = {
        "vintage": {"acs5": y5},
        "method": ("Tract ACS 5-year counts weighted by each tract's share of 2020 Census population inside the plan, "
                   "then summed. Medians and averages are not estimated."),
        "not_estimated": NOT_ESTIMATED,
        "plans": out_plans,
        "method_check": method,
        "dropped_variables": sorted(bad),
    }
    src = Source(id="acs5-tracts", publisher="U.S. Census Bureau",
                 title=f"American Community Survey 5-year estimates, {y5 - 4}-{y5}: Detailed tables, census tracts",
                 url=f"https://api.census.gov/data/{y5}/acs/acs5", year=str(y5 + 1), vintage=f"ACS {y5 - 4}-{y5} 5-year",
                 query=f"https://api.census.gov/data/{y5}/acs/acs5?get=...&for=tract:*&in=state:{d.state_fips} county:{','.join(counties)}",
                 notes=("Tract figures combined by the atlas using 2020 block populations; the result is an estimate "
                        "by the atlas, not a Census Bureau tabulation."))
    return payload, [src], checks
