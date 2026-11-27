"""Airports, heliports, and other aviation facilities inside the district (FAA, through BTS NTAD).

The FAA's airport records (updated every 28 days) give each landing facility's type, ownership, use,
status, and position. The atlas keeps facilities in the district's county and tests each position
against both district plans. A layout check confirms that each record's decimal position matches its
degrees, minutes, and seconds.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from ..config import District
from ..geo import contains
from ..http import Fetcher, FetchError
from ..provenance import Source

LAYER = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Aviation_Facilities/FeatureServer/0"
FIELDS = ["SITE_NO", "SITE_TYPE_CODE", "ARPT_ID", "ARPT_NAME", "CITY", "COUNTY_NAME", "OWNERSHIP_TYPE_CODE",
          "FACILITY_USE_CODE", "ARPT_STATUS", "LAT_DECIMAL", "LONG_DECIMAL", "LAT_DEG", "LAT_MIN", "LAT_SEC",
          "LONG_DEG", "LONG_MIN", "LONG_SEC", "EFF_DATE", "ICAO_ID"]
TYPES = {"A": "Airport", "H": "Heliport", "C": "Seaplane base", "B": "Balloonport", "G": "Gliderport", "U": "Ultralight"}
OWNERS = {"PU": "Publicly owned", "PR": "Privately owned", "MA": "Air Force", "MN": "Navy", "MR": "Army",
          "CG": "Coast Guard"}
USE = {"PU": "Open to the public", "PR": "Private use"}
STATUS = {"O": "Operational", "CI": "Closed indefinitely", "CP": "Closed permanently"}


def dms(deg, mins, secs) -> float | None:
    try:
        return float(deg) + float(mins) / 60 + float(secs) / 3600
    except (TypeError, ValueError):
        return None


def fetch(fetcher: Fetcher, d: District, full_shape_path: pathlib.Path) -> tuple[dict, list[Source], list[dict]]:
    meta = fetcher.json(LAYER, params={"f": "json"})
    have = {f["name"] for f in meta.get("fields", [])}
    missing = [f for f in FIELDS if f not in have]
    if missing:
        raise ValueError(f"FAA facility layer lacks fields {missing}")
    county = str(d.raw.get("county_name", "LOS ANGELES")).upper()
    page = fetcher.json(f"{LAYER}/query", params={"where": f"STATE_CODE='{d.state_abbr}' AND COUNTY_NAME='{county}'",
                                                   "outFields": ",".join(FIELDS), "returnGeometry": "false",
                                                   "resultRecordCount": 2000, "f": "json"})
    if "error" in page:
        raise FetchError(f"FAA facility query failed: {page['error']}")
    rows = [f["attributes"] for f in page.get("features", [])]
    if not rows:
        raise FetchError(f"No FAA facilities returned for {county} County")
    shapes = json.loads(pathlib.Path(full_shape_path).read_text(encoding="utf-8"))
    plans = {k[5:]: [f["geometry"] for f in v["features"]] for k, v in shapes.items() if k.startswith("plan_")}

    layout_ok, out = 0, []
    for a in rows:
        lat, lon = a.get("LAT_DECIMAL"), a.get("LONG_DECIMAL")
        if lat is None or lon is None:
            continue
        lat_d, lon_d = dms(a["LAT_DEG"], a["LAT_MIN"], a["LAT_SEC"]), dms(a["LONG_DEG"], a["LONG_MIN"], a["LONG_SEC"])
        if lat_d is not None and lon_d is not None and abs(lat_d - lat) < 1e-3 and abs(lon_d - abs(lon)) < 1e-3:
            layout_ok += 1
        in_plans = [pid for pid, geoms in plans.items() if any(contains(g, float(lon), float(lat)) for g in geoms)]
        if not in_plans:
            continue
        out.append({"id": a.get("ARPT_ID"), "name": " ".join(str(a.get("ARPT_NAME") or "").split()).title(),
                    "type": TYPES.get(a.get("SITE_TYPE_CODE"), a.get("SITE_TYPE_CODE")),
                    "ownership": OWNERS.get(a.get("OWNERSHIP_TYPE_CODE"), a.get("OWNERSHIP_TYPE_CODE")),
                    "use": USE.get(a.get("FACILITY_USE_CODE"), a.get("FACILITY_USE_CODE")),
                    "status": STATUS.get(a.get("ARPT_STATUS"), a.get("ARPT_STATUS")),
                    "city": str(a.get("CITY") or "").title(), "lat": round(float(lat), 5), "lon": round(float(lon), 5),
                    "in_plans": in_plans, "faa_record_date": a.get("EFF_DATE")})
    out.sort(key=lambda x: (x["type"] != "Airport", x["name"]))
    eff = sorted({str(a.get("EFF_DATE")) for a in rows if a.get("EFF_DATE")})
    checks = [{
        "id": "faa-layout", "title": "FAA facility positions agree in decimal and in degrees, minutes, and seconds",
        "status": "pass" if layout_ok >= 0.98 * len(rows) else "warn", "sources": ["faa-ntad-aviation"],
        "values": {"rows": len(rows), "agree": layout_ok},
        "detail": (f"{layout_ok:,} of {len(rows):,} {county.title()} County records agree; {len(out)} facilities fall inside either plan "
                   f"({sum(1 for x in out if x['type'] == 'Airport')} airports, {sum(1 for x in out if x['type'] == 'Heliport')} heliports). "
                   f"FAA record date: {eff[-1] if eff else 'not stated'}."),
    }]
    payload = {"facilities": out, "county_records": len(rows), "faa_record_date": eff[-1] if eff else None,
               "note": "Includes private-use heliports, such as those at hospitals and industrial sites; private-use facilities are not open to the public.",
               "as_of": datetime.now(timezone.utc).date().isoformat()}
    src = Source(id="faa-ntad-aviation", publisher="Federal Aviation Administration; Bureau of Transportation Statistics",
                 title="Aviation Facilities, National Transportation Atlas Database", url=LAYER, year=str(datetime.now(timezone.utc).year),
                 query=f"{LAYER}/query (STATE_CODE={d.state_abbr}, COUNTY_NAME={county})",
                 notes="FAA landing facility records, updated every 28 days.")
    return payload, [src], checks
