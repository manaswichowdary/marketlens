"""Adzuna job search API: https://developer.adzuna.com. Needs a free app id and key."""
import time

import requests

from .schema import Posting

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


def fetch_raw(app_id, app_key, what, where="", country="us", pages=2, per_page=50, session=None, pause=1.0):
    """Return a list of raw result dicts, exactly as Adzuna sent them."""
    session = session or requests.Session()
    results = []
    for page in range(1, pages + 1):
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": per_page,
            "what": what,
            "content-type": "application/json",
        }
        if where:
            params["where"] = where
        resp = session.get(BASE.format(country=country, page=page), params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json().get("results", [])
        results.extend(batch)
        if len(batch) < per_page:
            break  # last page
        time.sleep(pause)
    return results


def normalize(raw_results, fetched_at):
    postings = []
    for r in raw_results:
        postings.append(
            Posting(
                source="adzuna",
                source_id=str(r.get("id", "")),
                title=(r.get("title") or "").strip(),
                company=((r.get("company") or {}).get("display_name") or "").strip(),
                location=((r.get("location") or {}).get("display_name") or "").strip(),
                description=(r.get("description") or "").strip(),
                posted_at=r.get("created") or "",
                url=r.get("redirect_url") or "",
                category=((r.get("category") or {}).get("label") or "").strip(),
                salary_min=r.get("salary_min"),
                salary_max=r.get("salary_max"),
                fetched_at=fetched_at,
            )
        )
    return postings
