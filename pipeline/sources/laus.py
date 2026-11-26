"""Bureau of Labor Statistics: monthly unemployment for the district's cities (LAUS).

The Local Area Unemployment Statistics program publishes monthly estimates for cities of 25,000 or
more people, counties, states, and the nation. It does not publish congressional districts. The
atlas shows every city in either plan for which BLS publishes a series, beside Los Angeles County,
California, and the United States. City figures describe the whole city, including any part outside
the district (most of Los Angeles and Long Beach lie outside it).

All series are not seasonally adjusted, because city and county series are published only that way.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ..config import District
from ..http import Fetcher, FetchError
from ..provenance import Source

V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
US_SERIES = "LNU04000000"   # national unemployment rate, not seasonally adjusted


def city_series(state_fips: str, place_fips: str, measure: str = "03") -> str:
    """LAUS city series: LAU + CT + area code (state 2 + place 5 + six zeros) + measure."""
    return f"LAUCT{state_fips}{place_fips}000000{measure}"


def county_series(state_fips: str, county_fips: str, measure: str = "03") -> str:
    return f"LAUCN{state_fips}{county_fips}00000000{measure}"


def state_series(state_fips: str, measure: str = "03") -> str:
    return f"LAUST{state_fips}00000000000{measure}"


def _request(fetcher: Fetcher, series: list[str], start: int, end: int) -> tuple[list[dict], list[str]]:
    key = (os.environ.get("BLS_API_KEY") or "").strip()
    body = {"seriesid": series, "startyear": str(start), "endyear": str(end)}
    url = V1
    if key:
        body["registrationkey"] = key
        url = V2
    data = fetcher.json(url, method="POST", json_body=body)
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise FetchError(f"BLS: {data.get('status')} {data.get('message')}")
    return data["Results"]["series"], [str(m) for m in (data.get("message") or [])]


def missing_months(points: list[dict]) -> list[str]:
    """Calendar months absent between a series' first and last month."""
    if not points:
        return []
    have = {p["date"] for p in points}
    y, m = map(int, points[0]["date"].split("-"))
    ly, lm = map(int, points[-1]["date"].split("-"))
    gaps = []
    while (y, m) < (ly, lm):
        if f"{y}-{m:02d}" not in have:
            gaps.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return gaps


def fetch(fetcher: Fetcher, d: District, plans_payload: dict) -> tuple[dict, list[Source], list[dict]]:
    now = datetime.now(timezone.utc)
    key = bool((os.environ.get("BLS_API_KEY") or "").strip())
    span, per_req = (20, 50) if key else (10, 25)
    start_year = max(int(d.trends.get("laus_start_year", now.year - 9)), now.year - span + 1)
    min_pop = int(d.trends.get("laus_min_place_pop", 25000))

    # Places in either plan large enough for BLS to publish (by 2020 Census population of the whole place).
    places: dict[str, dict] = {}
    for pid, p in plans_payload["plans"].items():
        for r in p["places"]:
            if r["place"] and (r["pop_place"] or 0) >= min_pop:
                rec = places.setdefault(r["place"], {"place": r["place"], "name": r["short"], "type": r["type"],
                                                    "pop_place": r["pop_place"], "in_plans": [], "share_in": {}})
                rec["in_plans"].append(pid)
                rec["share_in"][pid] = r["share_of_place"]
    counties = sorted({c for p in plans_payload["plans"].values() for c in p["counties"]})

    ids: dict[str, tuple[str, str]] = {}   # series id -> (key, measure)
    for code in places:
        ids[city_series(d.state_fips, code, "03")] = (code, "rate")
        ids[city_series(d.state_fips, code, "06")] = (code, "labor_force")
    for c in counties:
        ids[county_series(d.state_fips, c, "03")] = (f"county:{c}", "rate")
    ids[state_series(d.state_fips)] = ("state", "rate")
    ids[US_SERIES] = ("us", "rate")
    all_ids = list(ids)

    series_out: dict[str, dict[str, dict]] = {}
    messages: list[str] = []
    y = start_year
    while y <= now.year:
        end = min(y + span - 1, now.year)
        for i in range(0, len(all_ids), per_req):
            res, msg = _request(fetcher, all_ids[i: i + per_req], y, end)
            messages += msg
            for s in res:
                k, measure = ids[s["seriesID"]]
                for pnt in s.get("data", []):
                    if not pnt["period"].startswith("M") or pnt["period"] == "M13":
                        continue
                    try:
                        v = float(pnt["value"])
                    except ValueError:
                        continue
                    date = f"{pnt['year']}-{pnt['period'][1:]}"
                    rec = series_out.setdefault(k, {}).setdefault(date, {"date": date})
                    rec[measure] = v
                    if any(f.get("code") == "P" for f in pnt.get("footnotes", []) if f):
                        rec["preliminary"] = True
        y = end + 1
    series = {k: sorted(v.values(), key=lambda p: p["date"]) for k, v in series_out.items()}

    published = [c for c in places if series.get(c)]
    not_published = [places[c]["name"] for c in places if not series.get(c)]
    if not published:
        raise FetchError("BLS returned no city series. Messages: " + "; ".join(messages[:3]))
    # BLS releases city estimates after county, state, and national ones, so the page compares every area in the
    # newest month that all published cities share.
    city_last = {places[c]["name"]: series[c][-1]["date"] for c in published}
    newest = min(city_last.values())
    behind = [n for n, v in city_last.items() if v != max(city_last.values())]
    gaps = sorted({g for s in series.values() for g in missing_months(s)})
    known_gaps = d.trends.get("laus_known_gaps") or {}

    newer = {k: s[-1]["date"] for k, s in series.items() if not k.isdigit() and s and s[-1]["date"] > newest}
    unexplained = [g for g in gaps if g not in known_gaps]
    checks = [{
        "id": "laus-current", "title": "Every published city has unemployment data through the same month, and gaps are explained",
        "status": "pass" if not behind and not unexplained else "warn", "sources": ["bls-laus"], "values": {"latest": newest},
        "detail": (f"{len(published)} cities run through {newest}."
                   + (f" Behind: {', '.join(behind)}." if behind else "")
                   + (f" County, state, or national series run to {max(newer.values())}; the page compares all areas in {newest}." if newer else "")
                   + (f" BLS does not publish monthly series for {', '.join(not_published)} (cities and places under its threshold "
                      "or census-designated places it does not cover)." if not_published else "")
                   + (f" Months with no estimate in any series: {', '.join(gaps)}." if gaps else "")
                   + "".join(f" {g}: {' '.join(str(known_gaps[g]).split())}" for g in gaps if g in known_gaps)),
    }]
    payload = {
        "places": [places[c] | {"published": c in published} for c in sorted(places, key=lambda c: -places[c]["pop_place"])],
        "series": series,
        "latest_month": newest,
        "gap_months": gaps,
        "gap_notes": {g: " ".join(str(known_gaps[g]).split()) for g in gaps if g in known_gaps},
        "seasonally_adjusted": False,
        "series_ids": {f"{k}:{m}": sid for sid, (k, m) in ids.items()},
        "scope_note": ("City figures describe whole cities. Most of Los Angeles and Long Beach lies outside the district, so their "
                       "rates are context, not district figures. BLS publishes no congressional-district series."),
    }
    src = Source(id="bls-laus", publisher="U.S. Bureau of Labor Statistics",
                 title="Local Area Unemployment Statistics: cities, county, state, and national, not seasonally adjusted",
                 url="https://www.bls.gov/lau/", year=str(now.year), query=f"{V2 if key else V1} (series {', '.join(all_ids[:3])}, ...)",
                 notes="The most recent month is preliminary and is revised the following month.")
    return payload, [src], checks
