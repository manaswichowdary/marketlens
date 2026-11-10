from marketlens import store
from marketlens.ingest import greenhouse, run

JOBS = {
    "jobs": [
        {"id": 1, "title": "Data Engineer ", "company_name": "Stripe", "location": {"name": "Remote, US"},
         "first_published": "2026-11-01T10:00:00-05:00", "updated_at": "2026-11-05T10:00:00-05:00",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1",
         "content": "&lt;p&gt;Build &lt;b&gt;pipelines&lt;/b&gt; with Python &amp;amp; SQL&lt;/p&gt;",
         "departments": [{"name": "Data"}]},
        {"id": 2, "title": "Designer", "location": None, "updated_at": "2026-11-05T10:00:00-05:00",
         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/2", "content": "", "departments": []},
    ]
}


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def json(self):
        return self.payload


class Session:
    """Answers per board name: a payload means 200, the string 'missing' means 404."""
    def __init__(self, boards):
        self.boards, self.calls = boards, []

    def get(self, url, params=None, timeout=None):
        board = url.split("/boards/")[1].split("/")[0]
        self.calls.append(board)
        data = self.boards.get(board, "missing")
        return Resp({}, 404) if data == "missing" else Resp(data)


def test_normalize_unescapes_html_and_handles_missing_fields():
    rows = greenhouse.normalize({"stripe": JOBS["jobs"]}, "t")
    assert rows[0].source_id == "stripe:1" and rows[0].company == "Stripe"
    assert rows[0].title == "Data Engineer"
    assert rows[0].description == "Build pipelines with Python & SQL"   # escaped HTML decoded, tags and extra spaces gone
    assert rows[0].category == "Data" and rows[0].posted_at.startswith("2026-11-01")
    assert rows[1].company == "stripe"        # no company_name: falls back to the board name
    assert rows[1].location == "" and rows[1].category == ""


def test_missing_board_is_skipped_and_reported_not_fatal():
    s = Session({"stripe": JOBS})
    raw, skipped = greenhouse.fetch_raw(["stripe", "nosuchco"], session=s, pause=0)
    assert list(raw) == ["stripe"] and skipped == [("nosuchco", "HTTP 404")]


def test_load_boards_ignores_comments_and_blank_lines(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("# comment\nstripe\n\n  airbnb  \n")
    assert greenhouse.load_boards(str(f)) == ["stripe", "airbnb"]


def test_run_greenhouse_loads_rows_logs_skips_and_is_repeatable(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("stripe\nnosuchco\n")
    con = store.connect(":memory:")
    s = Session({"stripe": JOBS})
    kw = dict(session=s, companies_file=str(f), pause=0)
    assert run.run_source("greenhouse", con, str(tmp_path), **kw) == (2, 2)
    assert run.run_source("greenhouse", con, str(tmp_path), **kw) == (2, 0)   # same jobs again: no new rows
    status, note = con.execute("SELECT status, error FROM runs").fetchone()
    assert status == "ok" and "nosuchco" in note
