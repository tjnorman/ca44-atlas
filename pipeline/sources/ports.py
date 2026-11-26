"""The Port of Los Angeles and the Port of Long Beach: where their docks are, and how much cargo they move.

Three public sources:
  * U.S. Army Corps of Engineers, Navigation Facilities (docks), published through the Bureau of
    Transportation Statistics' National Transportation Atlas Database. Each dock has coordinates and
    a port name; the atlas tests each dock against both district plans. (The dataset's own
    congressional district fields name older Congresses and are not used.)
  * Port of Los Angeles, container statistics: one page per calendar year with monthly TEUs and a
    calendar-year total row.
  * Port of Long Beach, container statistics: a calendar-year-by-month table with a year-to-date
    row, and a table of the most recent 25 months.

Checks: months add up to each port's own year totals, and the two Long Beach tables agree where
they overlap.
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..config import District
from ..geo import contains
from ..http import Fetcher, FetchError
from ..provenance import Source

DOCKS = "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/Docks/FeatureServer/0"
POLA_YEAR = "https://www.portoflosangeles.org/business/statistics/container-statistics/historical-teu-statistics-{y}"
POLB_CY = "https://thehelm.polb.com/stellar_custom_table/table102"
POLB_RECENT = "https://thehelm.polb.com/stellar_custom_table/table100"
POLB_PAGE = "https://polb.com/business/port-statistics/"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
MON3 = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}
PORTS = {"Port of Los Angeles, CA": "pola", "Port of Long Beach, CA": "polb"}
DOCK_FIELDS = ["NAV_UNIT_ID", "NAV_UNIT_NAME", "PORT_NAME", "FAC_TYPE", "OPERATORS", "OWNERS", "PURPOSE",
               "LATITUDE", "LONGITUDE", "CITY_OR_TOWN", "BERTHING_TOTAL", "COMMODITIES"]


class _Tables(HTMLParser):
    """Collect every table on a page as rows of cell text."""

    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
            self.tables.append([])
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self.tables:
                self.tables[-1].append(self._row)
            self._row = None
        elif tag == "table":
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def tables(html: str) -> list[list[list[str]]]:
    p = _Tables()
    p.feed(html)
    return [t for t in p.tables if t]


def num(s: str) -> float | None:
    s = (s or "").replace(",", "").replace("%", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def find_table(html: str, must: list[str]) -> list[list[str]]:
    """The first table whose header row contains every expected column name (case-insensitive)."""
    for t in tables(html):
        head = [c.lower() for c in t[0]]
        if all(any(m.lower() == h for h in head) for m in must):
            return t
    raise ValueError(f"No table with columns {must}")


def parse_pola_year(html: str, year: int) -> dict:
    t = find_table(html, ["Loaded Imports", "Empty Imports", "Loaded Exports", "Empty Exports", "Total TEUs"])
    head = [c.lower() for c in t[0]]
    col = {k: head.index(k.lower()) for k in ("Loaded Imports", "Empty Imports", "Loaded Exports", "Empty Exports", "Total TEUs")}
    months, total_row = [], None
    for r in t[1:]:
        label = (r[0] if r else "").strip().lower()
        if label in MONTHS:
            vals = {k: num(r[i]) if i < len(r) else None for k, i in col.items()}
            if vals["Total TEUs"] is None:
                continue
            months.append({"month": f"{year}-{MONTHS.index(label) + 1:02d}", "loaded_imports": vals["Loaded Imports"],
                           "empty_imports": vals["Empty Imports"], "loaded_exports": vals["Loaded Exports"],
                           "empty_exports": vals["Empty Exports"], "total": vals["Total TEUs"]})
        elif label.startswith("total calendar year"):
            total_row = num(r[col["Total TEUs"]])
    return {"year": year, "months": months, "calendar_year_total": total_row}


def parse_polb_cy(html: str, year: int) -> dict:
    t = find_table(html, ["Month", "Loaded Inbound", "Loaded Outbound", "Empties Inbound", "Empties Outbound", "Total"])
    head = [c.lower() for c in t[0]]
    idx = {k: head.index(k) for k in ("loaded inbound", "loaded outbound", "empties inbound", "empties outbound", "total")}
    months, ytd = [], None
    for r in t[1:]:
        label = (r[0] if r else "").strip().lower()
        if label in MONTHS:
            v = {k: num(r[i]) if i < len(r) else None for k, i in idx.items()}
            if v["total"] is None:
                continue
            months.append({"month": f"{year}-{MONTHS.index(label) + 1:02d}", "loaded_imports": v["loaded inbound"],
                           "empty_imports": v["empties inbound"], "loaded_exports": v["loaded outbound"],
                           "empty_exports": v["empties outbound"], "total": v["total"]})
        elif label == "year-to-date":
            ytd = num(r[idx["total"]])
    return {"year": year, "months": months, "year_to_date": ytd}


def parse_polb_recent(html: str) -> list[dict]:
    t = find_table(html, ["Date", "Loaded Inbound", "Loaded Outbound", "Empty Inbound", "Empty Outbound", "Total"])
    head = [c.lower() for c in t[0]]
    idx = {k: head.index(k) for k in ("loaded inbound", "loaded outbound", "empty inbound", "empty outbound", "total")}
    out = []
    for r in t[1:]:
        m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})$", (r[0] if r else "").strip())
        if not m or m.group(1).lower() not in MON3:
            continue
        v = {k: num(r[i]) if i < len(r) else None for k, i in idx.items()}
        out.append({"month": f"{m.group(2)}-{MON3[m.group(1).lower()]:02d}", "loaded_imports": v["loaded inbound"],
                    "empty_imports": v["empty inbound"], "loaded_exports": v["loaded outbound"],
                    "empty_exports": v["empty outbound"], "total": v["total"]})
    return sorted(out, key=lambda x: x["month"])


def docks(fetcher: Fetcher, plan_shapes: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    where = "STATE='CA' AND (PORT_NAME='Port of Los Angeles, CA' OR PORT_NAME='Port of Long Beach, CA')"
    meta = fetcher.json(DOCKS, params={"f": "json"})
    have = {f["name"] for f in meta.get("fields", [])}
    missing = [f for f in DOCK_FIELDS if f not in have]
    if missing:
        raise ValueError(f"USACE dock layer lacks fields {missing}")
    rows, offset = [], 0
    while True:
        page = fetcher.json(f"{DOCKS}/query", params={"where": where, "outFields": ",".join(DOCK_FIELDS),
                                                       "returnGeometry": "false", "f": "json",
                                                       "resultOffset": offset, "resultRecordCount": 1000,
                                                       "orderByFields": "NAV_UNIT_ID"})
        if "error" in page:
            raise FetchError(f"USACE dock query failed: {page['error']}")
        feats = page.get("features", [])
        rows += [f["attributes"] for f in feats]
        if not page.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    out = []
    for a in rows:
        lat, lon = a.get("LATITUDE"), a.get("LONGITUDE")
        if lat is None or lon is None:
            continue
        lon = -abs(float(lon)) if float(lon) > 0 else float(lon)   # some extracts store west longitude as positive
        in_plans = [pid for pid, geoms in plan_shapes.items() if any(contains(g, lon, float(lat)) for g in geoms)]
        out.append({"id": a.get("NAV_UNIT_ID"), "name": " ".join(str(a.get("NAV_UNIT_NAME") or "").split()),
                    "port": PORTS.get(a.get("PORT_NAME"), a.get("PORT_NAME")), "type": a.get("FAC_TYPE"),
                    "operators": " ".join(str(a.get("OPERATORS") or "").split())[:160] or None,
                    "purpose": " ".join(str(a.get("PURPOSE") or "").split())[:160] or None,
                    "berthing_ft": a.get("BERTHING_TOTAL"), "lat": round(float(lat), 5), "lon": round(lon, 5),
                    "in_plans": in_plans})
    summary = {}
    for port in ("pola", "polb"):
        ds = [x for x in out if x["port"] == port]
        summary[port] = {"docks": len(ds), **{f"in_{pid}": sum(1 for x in ds if pid in x["in_plans"]) for pid in plan_shapes},
                         "outside_all": sum(1 for x in ds if not x["in_plans"])}
    return out, summary


def fetch(fetcher: Fetcher, d: District, full_shape_path: pathlib.Path) -> tuple[dict, list[Source], list[dict]]:
    now = datetime.now(timezone.utc)
    raw = json.loads(pathlib.Path(full_shape_path).read_text(encoding="utf-8"))
    plan_shapes = {k[5:]: [f["geometry"] for f in v["features"]] for k, v in raw.items() if k.startswith("plan_")}
    checks: list[dict] = []
    sources: list[Source] = []

    dock_rows, dock_summary = docks(fetcher, plan_shapes)
    sources.append(Source(id="usace-docks", publisher="U.S. Army Corps of Engineers; Bureau of Transportation Statistics",
                          title="Navigation Facilities (Dock), National Transportation Atlas Database", url=DOCKS,
                          year=str(now.year), query=f"{DOCKS}/query (Port of Los Angeles, CA; Port of Long Beach, CA)",
                          notes="Dock locations, operators, and purposes as recorded by the Corps' Navigation and Civil Works Decision Support Center."))
    if not dock_rows:
        raise ValueError("The USACE dock layer returned no docks for either port")

    # Port of Los Angeles: one page per year
    start = int(d.trends.get("ports_start_year", now.year - 9))
    pola_years, pola_bad = [], []
    for y in range(start, now.year + 1):
        try:
            py = parse_pola_year(fetcher.text(POLA_YEAR.format(y=y)), y)
        except (FetchError, ValueError) as exc:
            if y == now.year:
                raise
            pola_bad.append(f"{y}: {exc}")
            continue
        if not py["months"]:
            continue
        s = sum(m["total"] for m in py["months"])
        py["sum_of_months"] = round(s, 2)
        py["months_match_total"] = py["calendar_year_total"] is not None and abs(s - py["calendar_year_total"]) < 1.0
        pola_years.append(py)
    mismatched = [str(p["year"]) for p in pola_years if not p["months_match_total"]]
    checks.append({"id": "pola-months-sum", "title": "Port of Los Angeles months add up to its calendar-year totals",
                   "status": "pass" if pola_years and not mismatched else "warn", "sources": ["pola-teu"], "values": {},
                   "detail": f"{len(pola_years)} years read ({pola_years[0]['year']}–{pola_years[-1]['year']}); "
                             + ("every year's monthly TEUs sum to the page's calendar-year total within one TEU."
                                if not mismatched else f"months do not match the total for {', '.join(mismatched)}.")
                             + (f" Not read: {'; '.join(pola_bad[:3])}." if pola_bad else "")})
    sources.append(Source(id="pola-teu", publisher="Port of Los Angeles", title="Container statistics by calendar year",
                          url="https://www.portoflosangeles.org/business/statistics/container-statistics", year=str(now.year),
                          query=POLA_YEAR.format(y="YYYY"), notes="TEUs (twenty-foot equivalent units) reported by the port; the latest month may be revised."))

    # Port of Long Beach: calendar year by month, and the last 25 months
    cy = parse_polb_cy(fetcher.text(POLB_CY), now.year)
    if not cy["months"]:   # early in a year the table may already hold the new year
        cy = parse_polb_cy(fetcher.text(POLB_CY), now.year - 1)
    recent = parse_polb_recent(fetcher.text(POLB_RECENT))
    s = sum(m["total"] for m in cy["months"])
    ok_ytd = cy["year_to_date"] is not None and abs(s - cy["year_to_date"]) < 1.0
    checks.append({"id": "polb-months-sum", "title": "Port of Long Beach months add up to its year-to-date total",
                   "status": "pass" if ok_ytd else "warn", "sources": ["polb-teu"], "values": {"sum": s, "ytd": cy["year_to_date"]},
                   "detail": f"{len(cy['months'])} months of {cy['year']} sum to {s:,.0f} TEUs; the table's year-to-date row is "
                             f"{cy['year_to_date']:,.0f}." if cy["year_to_date"] is not None else "No year-to-date row found."})
    rec = {m["month"]: m["total"] for m in recent}
    overlap = [(m["month"], m["total"], rec[m["month"]]) for m in cy["months"] if m["month"] in rec]
    differ = [o for o in overlap if abs(o[1] - o[2]) >= 1.0]
    checks.append({"id": "polb-tables-agree", "title": "Two Port of Long Beach tables agree month by month",
                   "status": "pass" if overlap and not differ else "warn", "sources": ["polb-teu"], "values": {},
                   "detail": (f"{len(overlap)} months appear in both the calendar-year table and the 25-month table; "
                              + ("all match." if not differ else f"{len(differ)} differ, for example {differ[0][0]}: {differ[0][1]:,.0f} vs {differ[0][2]:,.0f}."))})
    sources.append(Source(id="polb-teu", publisher="Port of Long Beach", title="Port statistics: container trade in TEUs",
                          url=POLB_PAGE, year=str(now.year), query=f"{POLB_CY}; {POLB_RECENT}",
                          notes="The port describes its latest numbers as preliminary estimates."))

    # One monthly series per port for the page: Long Beach from the 25-month table plus this year's table.
    polb_months = {m["month"]: m for m in recent}
    for m in cy["months"]:
        polb_months.setdefault(m["month"], m)
    pola_months = {m["month"]: m for p in pola_years for m in p["months"]}
    latest_common = max(set(pola_months) & set(polb_months)) if set(pola_months) & set(polb_months) else None

    def ytd(series: dict, month: str | None, years_back: int = 0) -> float | None:
        if not month:
            return None
        y, mm = int(month[:4]) - years_back, int(month[5:])
        vals = [series.get(f"{y}-{i:02d}", {}).get("total") for i in range(1, mm + 1)]
        return sum(vals) if all(v is not None for v in vals) else None

    payload = {
        "docks": dock_rows,
        "dock_summary": dock_summary,
        "dock_note": ("Docks are placed by the coordinates in the Corps' facility records. A dock counts as inside a plan when "
                      "its point falls inside the plan's outline; the outline includes harbor water."),
        "pola": {"years": [{k: p[k] for k in ("year", "calendar_year_total", "sum_of_months", "months_match_total")} for p in pola_years],
                 "months": sorted(pola_months.values(), key=lambda m: m["month"])[-24:]},
        "polb": {"months": sorted(polb_months.values(), key=lambda m: m["month"])[-24:], "year_to_date": cy["year_to_date"], "year": cy["year"]},
        "latest_common_month": latest_common,
        "ytd": {port: {"this_year": ytd(series, latest_common), "last_year": ytd(series, latest_common, 1)}
                for port, series in (("pola", pola_months), ("polb", polb_months))},
        "as_of": now.date().isoformat(),
    }
    return payload, sources, checks
