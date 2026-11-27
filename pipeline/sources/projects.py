"""Major public works in the district (data/curated/projects.yaml).

These are not pulled from a data file. Each fact was read from an official project page or
press release, and the page is named beside it. The build refuses a fact without a listed
source and warns once the review date has passed, since schedules move.

A project may also carry a `news` list: reports that point toward public records. They are kept
apart from facts. The build refuses a news entry without an outlet, date, headline, and link,
refuses a fact that cites a news link, and warns once the list's own review date has passed.
"""

from __future__ import annotations

from datetime import date

import yaml

from ..config import ROOT, District
from ..provenance import Source

PATH = ROOT / "data" / "curated" / "projects.yaml"


def fetch(fetcher, d: District, path=PATH, today: date | None = None) -> tuple[dict, list[Source], list[dict]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    today = today or date.today()
    projects, sources, missing, news_problems = [], {}, [], []
    news_count, news_due = 0, []
    for p in raw.get("projects", []):
        ids = {s["id"] for s in p.get("sources", [])}
        for item in list(p.get("facts", [])) + list(p.get("timeline", [])):
            if item.get("source") not in ids:
                missing.append(f"{p['id']}: {item.get('label') or item.get('date')}")
        for s in p.get("sources", []):
            sources[s["id"]] = Source(id=s["id"], publisher=s["publisher"], title=s["title"], url=s["url"],
                                      year=str(s["year"]), kind=s.get("kind", "Web page"))
        news = p.get("news") or None
        if news:
            news = {"note": news.get("note"), "read_on": str(news.get("read_on")), "review_by": str(news.get("review_by")),
                    "items": [dict(n, date=str(n.get("date"))) for n in news.get("items", [])]}
            source_urls = {s["url"] for s in p.get("sources", [])}
            for key in ("note", "read_on", "review_by"):
                if news[key] in (None, "None", ""):
                    news_problems.append(f"{p['id']}: news list has no {key}")
            for n in news["items"]:
                for key in ("outlet", "date", "headline", "url"):
                    if not n.get(key) or n[key] == "None":
                        news_problems.append(f"{p['id']}: news entry without {key}: {n.get('headline') or n.get('url')}")
                if n.get("url") and not str(n["url"]).startswith("https://"):
                    news_problems.append(f"{p['id']}: news link is not https: {n['url']}")
                if n.get("url") in source_urls:
                    news_problems.append(f"{p['id']}: news link is also listed as a fact source: {n['url']}")
            news["items"].sort(key=lambda n: n["date"], reverse=True)
            news_count += len(news["items"])
            if news["review_by"] not in ("None", ""):
                news_due.append(news["review_by"])
        projects.append({k: p.get(k) for k in ("id", "title", "place", "county", "dates", "summary", "links", "facts", "timeline")}
                        | {"sources": sorted(ids), "news": news})
    if missing:
        raise ValueError("Project facts without a listed source: " + "; ".join(missing))
    if news_problems:
        raise ValueError("Project news list problems: " + "; ".join(news_problems))
    review_by = raw.get("review_by")
    overdue = bool(review_by) and today > date.fromisoformat(str(review_by))
    checks = [{
        "id": "projects-sourced", "title": "Every project fact names an official source",
        "status": "warn" if overdue else "pass", "sources": sorted(sources), "values": {"projects": len(projects)},
        "detail": (f"{sum(len(p['facts']) + len(p['timeline']) for p in projects)} facts across {len(projects)} project(s), "
                   f"each tied to a listed page. Read on {raw.get('verified_on')}; due for re-reading by {review_by}."
                   + (" The review date has passed." if overdue else "")),
    }]
    if news_count:
        news_overdue = any(today > date.fromisoformat(r) for r in news_due)
        checks.append({
            "id": "projects-news-apart", "title": "News links are listed apart from facts",
            "status": "warn" if news_overdue else "pass", "sources": [], "values": {"news_links": news_count},
            "detail": (f"{news_count} news link(s), each with its outlet, date, headline, and address. None is used as the "
                       f"source of a fact. Due for review by {min(news_due)}."
                       + (" The review date has passed." if news_overdue else "")),
        })
    payload = {"projects": projects, "verified_on": str(raw.get("verified_on")), "review_by": str(review_by),
               "note": "Dates and costs are the agencies' published plans as of the date read, and can change."}
    return payload, list(sources.values()), checks
