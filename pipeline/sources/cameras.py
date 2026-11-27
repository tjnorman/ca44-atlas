"""Caltrans highway cameras inside the district.

Caltrans publishes the location, status, and current image of every state highway camera through its
Commercial Wholesale Web Portal (CWWP2), one file per district, so that travel information reaches the
public widely. The atlas keeps the cameras that fall inside either district plan and links to each
camera's current image and live video. City and port cameras are not in this file.

Written for the CA-44 Atlas; not derived from the WI-7 Atlas camera code.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from ..config import District
from ..geo import contains
from ..http import Fetcher, FetchError
from ..provenance import Source

CWWP2 = "https://cwwp2.dot.ca.gov/data/d{d}/cctv/cctvStatusD{d:02d}.json"
CWWP2_DOCS = "https://cwwp2.dot.ca.gov/documentation/cctv/cctv.htm"


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse(raw: dict) -> list[dict]:
    rows = raw.get("data")
    if not isinstance(rows, list) or not rows or "cctv" not in rows[0]:
        raise ValueError("Unexpected CWWP2 camera layout: expected data[].cctv")
    out = []
    for r in rows:
        c = r["cctv"]
        loc = c.get("location") or {}
        img = c.get("imageData") or {}
        static = img.get("static") or {}
        lat, lon = _f(loc.get("latitude")), _f(loc.get("longitude"))
        if lat is None or lon is None:
            continue
        url = static.get("currentImageURL")
        video = img.get("streamingVideoURL")
        out.append({
            "id": str(c.get("index")),
            "name": " ".join(str(loc.get("locationName") or "").split()),
            "nearby": loc.get("nearbyPlace"),
            "route": loc.get("route"),
            "direction": loc.get("direction"),
            "county": loc.get("county"),
            "in_service": str(c.get("inService")).lower() == "true",
            "image_url": url if url and url.startswith("http") else None,
            "video_url": video if video and str(video).startswith("http") else None,
            "image_minutes": static.get("currentImageUpdateFrequency"),
            "lat": round(lat, 5), "lon": round(lon, 5),
        })
    return out


def fetch(fetcher: Fetcher, d: District, full_shape_path: pathlib.Path) -> tuple[dict, list[Source], list[dict]]:
    caltrans_district = int(d.raw.get("caltrans_district", 7))
    url = CWWP2.format(d=caltrans_district)
    raw = fetcher.json(url)
    cams = parse(raw)
    shapes = json.loads(pathlib.Path(full_shape_path).read_text(encoding="utf-8"))
    plans = {k[5:]: [f["geometry"] for f in v["features"]] for k, v in shapes.items() if k.startswith("plan_")}
    inside = []
    for c in cams:
        c["in_plans"] = [pid for pid, geoms in plans.items() if any(contains(g, c["lon"], c["lat"]) for g in geoms)]
        if c["in_plans"]:
            inside.append(c)
    inside.sort(key=lambda c: (c["route"] or "", c["name"]))
    if not inside:
        raise FetchError("No Caltrans cameras fall inside either plan; the file or the outlines may have changed")
    wrong_county = [c for c in inside if c["county"] and c["county"].lower() != "los angeles"]
    in_service = sum(1 for c in inside if c["in_service"])
    checks = [{
        "id": "cameras-inside", "title": "Caltrans cameras placed inside the district are mostly in service",
        "status": "pass" if in_service >= 0.5 * len(inside) else "warn",
        "sources": ["caltrans-cctv"], "values": {"inside": len(inside), "in_service": in_service},
        "detail": (f"{len(inside)} of {len(cams)} District {caltrans_district} cameras fall inside either plan; {in_service} are in service. "
                   + (f"Caltrans's file labels {len(wrong_county)} of them with another county ("
                      + "; ".join(f"{c['name']}: {c['county']}" for c in wrong_county[:4])
                      + "), but their coordinates fall inside the district, so the labels appear to be errors in the file."
                      if wrong_county else "All are labeled Los Angeles County.")),
    }]
    payload = {
        "cameras": inside,
        "total_in_file": len(cams),
        "by_route": {r: sum(1 for c in inside if c["route"] == r) for r in sorted({c["route"] for c in inside if c["route"]})},
        "note": ("Caltrans highway cameras only. Images refresh every few minutes on Caltrans's servers; the atlas stores links, "
                 "not pictures. Cameras that Caltrans installed on local detour streets for the bridge closure are not in this file "
                 "unless Caltrans added them to it."),
        "as_of": datetime.now(timezone.utc).date().isoformat(),
    }
    src = Source(id="caltrans-cctv", publisher="California Department of Transportation (Caltrans)",
                 title=f"Commercial Wholesale Web Portal 2: CCTV status, District {caltrans_district}", url=CWWP2_DOCS,
                 year=str(datetime.now(timezone.utc).year), query=url,
                 notes="Camera locations, status, and image links for the state highway network.")
    return payload, [src], checks
