"""Greenhouse public job boards: https://boards-api.greenhouse.io/v1/boards/<company>/jobs?content=true

Free, no key. Each company that uses Greenhouse has a board name (the "token"), usually the company name in
lower case. A board that does not exist answers 404, and we skip it and say so.
"""
import html
import re
import time

import requests

from .schema import Posting

URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def load_boards(path):
    """One board name per line. Blank lines and lines starting with # are ignored."""
    boards = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                boards.append(line)
    return boards


def fetch_raw(boards, session=None, pause=0.5):
    """Return ({board: [raw job dicts]}, [(board, reason), ...]) for boards we could not read."""
    session = session or requests.Session()
    raw, skipped = {}, []
    for board in boards:
        try:
            resp = session.get(URL.format(board=board), params={"content": "true"}, timeout=60)
        except requests.RequestException as e:
            skipped.append((board, type(e).__name__))
            continue
        if resp.status_code != 200:
            skipped.append((board, f"HTTP {resp.status_code}"))
            continue
        raw[board] = resp.json().get("jobs", [])
        time.sleep(pause)
    return raw, skipped


def _clean_html(text):
    """Greenhouse sends the description as HTML that is itself escaped (&lt;p&gt;). Undo that, then drop tags."""
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def normalize(raw_by_board, fetched_at):
    postings = []
    for board, jobs in raw_by_board.items():
        for r in jobs:
            departments = r.get("departments") or []
            postings.append(
                Posting(
                    source="greenhouse",
                    source_id=f"{board}:{r.get('id', '')}",
                    title=(r.get("title") or "").strip(),
                    company=(r.get("company_name") or board).strip(),
                    location=((r.get("location") or {}).get("name") or "").strip(),
                    description=_clean_html(r.get("content")),
                    posted_at=r.get("first_published") or r.get("updated_at") or "",
                    url=r.get("absolute_url") or "",
                    category=(departments[0].get("name") or "").strip() if departments else "",
                    salary_min=None,
                    salary_max=None,
                    fetched_at=fetched_at,
                )
            )
    return postings
