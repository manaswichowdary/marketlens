"""Remotive remote jobs API: https://remotive.com/api/remote-jobs. Free, no key.

Remotive asks people to call it at most a few times a day and to credit them, so the pipeline
calls it once per run and the README links back to them.
"""
import re

import requests

from .schema import Posting

URL = "https://remotive.com/api/remote-jobs"


def fetch_raw(category="software-dev", search="", limit=100, session=None):
    session = session or requests.Session()
    params = {"category": category, "limit": limit}
    if search:
        params["search"] = search
    resp = session.get(URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("jobs", [])


def _parse_salary(text):
    """Remotive salary is free text such as "$80k - $100k". Return (min, max) or (None, None)."""
    if not text:
        return None, None
    nums = []
    for value, k in re.findall(r"(\d[\d,]*\.?\d*)\s*([kK])?", text):
        n = float(value.replace(",", ""))
        nums.append(n * 1000 if k else n)
    nums = [n for n in nums if n >= 1000]  # ignore stray small numbers
    if not nums:
        return None, None
    return min(nums), max(nums)


def normalize(raw_jobs, fetched_at):
    postings = []
    for r in raw_jobs:
        low, high = _parse_salary(r.get("salary"))
        postings.append(
            Posting(
                source="remotive",
                source_id=str(r.get("id", "")),
                title=(r.get("title") or "").strip(),
                company=(r.get("company_name") or "").strip(),
                location=(r.get("candidate_required_location") or "Remote").strip(),
                description=re.sub(r"<[^>]+>", " ", r.get("description") or "").strip(),
                posted_at=r.get("publication_date") or "",
                url=r.get("url") or "",
                category=(r.get("category") or "").strip(),
                salary_min=low,
                salary_max=high,
                fetched_at=fetched_at,
            )
        )
    return postings
