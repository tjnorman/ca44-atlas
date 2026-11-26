"""Run every source, keep what worked, check it, and write the outputs."""

from __future__ import annotations

import json
import pathlib
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

import yaml

from . import checks as checks_mod
from .config import DATA_ROOT, ROOT, District
from .http import Fetcher
from .provenance import dataset
from .sources import acs, acs_plan, broadcast, colleges, elections, fec, irs, laus, legislators, plans, ports, usaspending, votes

DEFAULT_ORDER = ["plans", "legislators", "acs", "acs_plan", "laus", "ports", "usaspending", "irs", "elections", "fec", "votes", "colleges", "broadcast"]


def data_dir(d: District) -> pathlib.Path:
    return DATA_ROOT / d.id


def load_json(path: pathlib.Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_json(path: pathlib.Path, obj: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(obj, ensure_ascii=False, indent=1)
    path.write_text(text + "\n", encoding="utf-8")


def load_notes() -> list[dict]:
    path = ROOT / "data" / "curated" / "notes.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    notes = raw.get("notes", [])
    for n in notes:
        for k in ("verified_on", "review_by"):
            if k in n:
                n[k] = str(n[k])
    return notes


def order_for(d: District) -> list[str]:
    return list(d.raw.get("sources") or DEFAULT_ORDER)


def annotate_plans(records: list[dict], shape_path: pathlib.Path) -> None:
    """Mark which district plans contain each record with a lat/lon (districts drawn as several plans)."""
    from .geo import contains
    full = shape_path.parent / "district.full.geojson.json"
    raw = load_json(full) or load_json(shape_path) or {}
    shapes = {k[5:]: [f["geometry"] for f in v["features"]] for k, v in raw.items() if k.startswith("plan_")}
    for r in records:
        if r.get("lat") is None or r.get("lon") is None:
            continue
        r["in_plans"] = [pid for pid, geoms in shapes.items() if any(contains(g, r["lon"], r["lat"]) for g in geoms)]


def rejudge_ipeds(check: dict, payload: dict, d: District) -> dict:
    """IPEDS codes each institution with its district under the current (Census-tabulated) plan.
    With several plans, compare that code with the current plan's outline only."""
    cur = next((p["id"] for p in d.raw.get("plans", []) if int(p["congress"]) == d.congress), None)
    rows = [r for r in payload.get("institutions", []) if r.get("ipeds_cd") is not None]
    if not cur or not rows:
        return check
    bad = [r for r in rows if (r["ipeds_cd"].lstrip("0") == d.geoid.lstrip("0")) != (cur in (r.get("in_plans") or []))]
    new_only = sum(1 for r in payload["institutions"] if cur not in (r.get("in_plans") or []))
    return {**check, "status": "pass" if not bad else "warn", "values": {"listed": len(payload["institutions"]), "disagree": len(bad)},
            "detail": (f"For the {cur} lines, IPEDS district codes agree with the outline for all {len(rows)} institutions listed"
                       + (f"; {new_only} are inside the new lines only and carry a neighboring district's code, as expected." if new_only else ".")
                       if not bad else f"{len(bad)} differ from the {cur} outline: "
                       + "; ".join(f"{r['name']} (IPEDS {r['ipeds_cd']})" for r in bad[:6]))}


def run(d: District, only: list[str] | None = None) -> dict:
    ORDER = order_for(d)
    out = data_dir(d)
    out.mkdir(parents=True, exist_ok=True)
    f = Fetcher()
    manifest_path = out / "manifest.json"
    manifest = load_json(manifest_path) or {"sources": {}}
    data: dict[str, dict | None] = {name: load_json(out / f"{name}.json") for name in ORDER}
    extra_checks: list[dict] = []

    plans_mode = d.raw.get("geography") == "plans"

    def plans_data() -> dict:
        p = data.get("plans")
        if not p:
            raise RuntimeError("District plans unavailable: plans has never succeeded")
        return p["data"]

    def counties_fips() -> list[str]:
        if plans_mode:
            return sorted({c for p in plans_data()["plans"].values() for c in p["counties"]})
        g = data.get("geography")
        if not g:
            raise RuntimeError("County list unavailable: geography has never succeeded")
        return [c["county_fips"] for c in g["data"]["counties"]]

    def county_names() -> dict[str, str]:
        if plans_mode:
            return {k: v.replace(" County", "") for k, v in plans_data()["county_names"].items()}
        g = data.get("geography")
        return {c["county_fips"]: c["short_name"] for c in g["data"]["counties"]} if g else {}

    def split_fips() -> set[str]:
        g = data.get("geography")
        return {c["county_fips"] for c in g["data"]["counties"] if not c["whole"]} if g else set()

    def communities() -> set[str]:
        if plans_mode:
            pd_ = plans_data()
            return {r["short"].upper() for p in pd_["plans"].values() for r in p["places"]
                    if r["place"] and (r["share_of_place"] or 0) >= 0.5}
        m = data.get("municipalities")
        if not m:
            raise RuntimeError("Municipality list unavailable")
        # Cities and villages mostly inside the district. Town names repeat across the state
        # (Berlin, Jackson, Cleveland), so a town name alone cannot place a station here.
        return {x["name"].upper() for x in m["data"]["municipalities"]
                if x["type"] in ("city", "village") and x["land_share_in_district"] >= 0.5}

    steps: dict[str, Callable[[], tuple]] = {
        "plans": lambda: plans.fetch(f, d, out / "geo"),
        "acs_plan": lambda: acs_plan.fetch(f, d, plans_data(), (data.get("acs") or {}).get("data")),
        "legislators": lambda: legislators.fetch(f, d),
        "acs": lambda: acs.fetch(f, d),
        "usaspending": lambda: usaspending.fetch(f, d, counties_fips()),
        "irs": lambda: irs.fetch(f, d),
        "colleges": lambda: colleges.fetch(f, d, out / "geo" / "district.simple.geojson.json"),
        "broadcast": lambda: broadcast.fetch(f, d, out / "geo" / "district.simple.geojson.json", county_names(), communities()),

        "laus": lambda: laus.fetch(f, d, plans_data()),
        "ports": lambda: ports.fetch(f, d, out / "geo" / "district.full.geojson.json"),
        "elections": lambda: elections.fetch(f, d),
        "fec": lambda: fec.fetch(f, d),
        "votes": lambda: votes.fetch(f, d, (data.get("legislators") or {}).get("data", {}).get("terms", [])),
    }

    for name in ORDER:
        if only and name not in only:
            continue
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            payload, sources, src_checks = steps[name]()
            if plans_mode and name in ("colleges", "broadcast"):
                for key in ("institutions", "stations", "licensed_here_outside"):
                    if isinstance(payload.get(key), list):
                        annotate_plans(payload[key], out / "geo" / "district.simple.geojson.json")
                if name == "colleges":
                    src_checks = [rejudge_ipeds(c, payload, d) if c["id"] == "ipeds-district" else c for c in src_checks]
            data[name] = dataset(payload, sources, district=d.id, source_module=name)
            write_json(out / f"{name}.json", data[name], compact=name in {"votes"})
            extra_checks += src_checks
            manifest["sources"][name] = {"status": "ok", "updated": started, "error": None,
                                         "sources": [s.id for s in sources]}
            print(f"  ok      {name}")
        except Exception as exc:  # keep the last good file; record why this run failed
            prev = manifest["sources"].get(name, {})
            manifest["sources"][name] = {
                "status": "stale" if data.get(name) else "missing",
                "updated": prev.get("updated"),
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "sources": prev.get("sources", []),
                "attempted": started,
            }
            print(f"  FAILED  {name}: {exc}")
            traceback.print_exc()

    notes = load_notes()
    results = checks_mod.run(d, data, notes, extra_checks)
    # Keep checks contributed by sources that were not re-run in this build.
    previous = load_json(out / "integrity.json") or {}
    run_ids = {c["id"] for c in results}
    for c in previous.get("checks", []):
        kept = (c["id"] == "acs-labels" and "acs" not in (only or [])) or \
               (c["id"].startswith("irs-") and "irs" not in (only or [])) or \
               (c["id"].startswith("ipeds-") and "colleges" not in (only or [])) or \
               (c["id"] == "municipalities-cover" and "municipalities" not in (only or [])) or \
               (c["id"] in ("fcc-layout", "station-links") and "broadcast" not in (only or [])) or \
               (c["id"] == "projects-sourced" and "projects" not in (only or [])) or \
               (c["id"] == "wisdot-program" and "roads" not in (only or [])) or \
               (c["id"].startswith("ssa-") and "ssa" not in (only or [])) or \
               (c["id"].split("-")[0] in ("bef", "pop", "land", "equal", "places") and "plans" not in (only or [])) or \
               (c["id"].startswith("acs-method") and "acs_plan" not in (only or [])) or \
               (c["id"] in ("election-sources-agree", "election-names") and "elections" not in (only or [])) or \
               (c["id"] == "laus-current" and "laus" not in (only or [])) or \
               (c["id"].split("-")[0] in ("pola", "polb") and "ports" not in (only or []))
        if c["id"] not in run_ids and only and kept:
            results.insert(0, c)
    integrity = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "summary": checks_mod.summarize(results), "checks": results}
    write_json(out / "integrity.json", integrity)
    write_json(out / "notes.json", {"notes": notes})

    manifest.update({
        "district": d.id,
        "name": d.name,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requests": len(f.log),
        "requests_from_cache": sum(1 for r in f.log if r.from_cache),
    })
    write_json(manifest_path, manifest)
    write_json(out / "fetch-log.json", [asdict(r) for r in f.log], compact=True)

    from . import summary
    summ = summary.build(d, data, integrity, notes, manifest)
    write_json(out / "summary.json", summ)
    print(f"  checks: {integrity['summary']}")
    for c in results:
        print(f"    {c['status']:5} {c['id']}: {c['detail'][:300]}")
    return {"manifest": manifest, "integrity": integrity, "summary": summ}
