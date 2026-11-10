import json

import pytest

from marketlens import store
from marketlens.ingest import adzuna, remotive, run

ADZUNA_PAGE = {
    "results": [
        {"id": 111, "title": "Data Engineer", "company": {"display_name": "Acme"},
         "location": {"display_name": "Phoenix, Arizona"}, "description": "Python and SQL",
         "created": "2026-11-09T10:00:00Z", "redirect_url": "https://adzuna.example/111",
         "category": {"label": "IT Jobs"}, "salary_min": 100000, "salary_max": 130000},
        {"id": 112, "title": "Backend Developer ", "company": {"display_name": "Globex"},
         "location": {"display_name": "Tempe, Arizona"}, "description": "Go",
         "created": "2026-11-08T10:00:00Z", "redirect_url": "https://adzuna.example/112",
         "category": {"label": "IT Jobs"}},
    ]
}
REMOTIVE_PAGE = {
    "jobs": [
        {"id": 9, "url": "https://remotive.example/9", "title": "Data Engineer", "company_name": "Acme Inc",
         "category": "Software Development", "publication_date": "2026-11-09T09:00:00",
         "candidate_required_location": "USA Only", "salary": "$80k - $100k",
         "description": "<p>Python and <b>dbt</b></p>"},
        {"id": 10, "url": "https://remotive.example/10", "title": "QA Engineer", "company_name": "Initech",
         "category": "QA", "publication_date": "2026-11-07T09:00:00", "candidate_required_location": "",
         "salary": "", "description": "<p>Testing</p>"},
    ]
}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse(self.payload, self.status)


def test_adzuna_normalize_maps_fields_and_trims():
    rows = adzuna.normalize(ADZUNA_PAGE["results"], "2026-11-10T00:00:00Z")
    assert rows[0].title == "Data Engineer" and rows[0].company == "Acme"
    assert rows[0].salary_min == 100000
    assert rows[1].title == "Backend Developer"  # trailing space removed
    assert rows[1].salary_min is None             # missing salary stays missing, not zero


def test_remotive_normalize_strips_html_and_parses_salary():
    rows = remotive.normalize(REMOTIVE_PAGE["jobs"], "2026-11-10T00:00:00Z")
    assert "Python" in rows[0].description and "dbt" in rows[0].description
    assert "<" not in rows[0].description
    assert (rows[0].salary_min, rows[0].salary_max) == (80000, 100000)
    assert rows[1].location == "Remote"           # empty location defaults to Remote
    assert rows[1].salary_min is None


def test_adzuna_fetch_sends_key_and_stops_on_short_page():
    s = FakeSession(ADZUNA_PAGE)
    out = adzuna.fetch_raw("id", "key", "data engineer", pages=3, per_page=50, session=s, pause=0)
    assert len(out) == 2 and len(s.calls) == 1    # 2 < 50, so it stops after page 1
    assert s.calls[0][1]["app_id"] == "id" and s.calls[0][1]["what"] == "data engineer"


def test_upsert_does_not_duplicate_same_source_and_id():
    con = store.connect(":memory:")
    rows = adzuna.normalize(ADZUNA_PAGE["results"], "t1")
    assert store.upsert(con, rows) == 2
    assert store.upsert(con, rows) == 0           # same postings again: nothing new
    assert con.execute("SELECT count(*) FROM postings").fetchone()[0] == 2


def test_same_id_from_different_sources_are_kept_separate():
    con = store.connect(":memory:")
    a = adzuna.normalize([{"id": 9, "title": "A"}], "t")
    r = remotive.normalize([{"id": 9, "title": "B"}], "t")
    store.upsert(con, a + r)
    assert con.execute("SELECT count(*) FROM postings").fetchone()[0] == 2


def test_run_source_saves_raw_file_and_logs_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    con = store.connect(":memory:")
    fetched, new_rows = run.run_source("adzuna", con, str(tmp_path), session=FakeSession(ADZUNA_PAGE), what="x", pages=1)
    assert (fetched, new_rows) == (2, 2)
    files = list((tmp_path / "adzuna").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())[0]["id"] == 111
    assert con.execute("SELECT status, fetched, new_rows FROM runs").fetchall() == [("ok", 2, 2)]


def test_failed_run_is_logged_and_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    con = store.connect(":memory:")
    with pytest.raises(RuntimeError):
        run.run_source("adzuna", con, str(tmp_path), session=FakeSession({}, status=401), what="x", pages=1)
    status, err = con.execute("SELECT status, error FROM runs").fetchone()
    assert status == "failed" and "401" in err
