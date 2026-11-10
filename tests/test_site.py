import datetime

from marketlens import site, trends
from tests.test_trends import P, make_db

D = datetime.date


def small_db():
    posts = [P(i, "Data Engineer", f"We use Python for project {i}.", "2026-11-01", company=f"Company{i}") for i in range(35)]
    posts += [P(100 + i, "Account Executive", f"Salesforce is needed for deal {i}.", "2026-11-02", location="Austin, TX",
                company=f"Seller{i}") for i in range(5)]
    con = make_db(posts)
    trends.build(con, today=D(2026, 11, 10))
    return con


def test_collect_counts_jobs_and_skills():
    data = site.collect(small_db())
    assert data["total"] == 40 and data["days"] == 1
    assert data["top_skills"][0][0] == "python"
    families = [f for f, _, _ in data["by_family"]]
    assert families == ["Data Engineering"]                     # Sales has only 5 jobs, under the minimum


def test_page_says_no_trend_with_one_day():
    html = site.render(site.collect(small_db()))
    assert "does not draw one yet" in html
    assert "<script" not in html and "40</b>" in html


def test_labels_are_escaped():
    html = site._bars([("<script>alert(1)</script>", 50)])
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_snapshot_change_needs_enough_days_then_reports_change():
    con = small_db()
    assert site.snapshot_change(con)["enough"] is False
    con.execute("DELETE FROM skill_snapshots")
    for day in range(14):
        con.execute("INSERT INTO skill_snapshots VALUES (?, 'python', ?, 100)", [D(2026, 11, 1) + datetime.timedelta(days=day), 40 + day])
        con.execute("INSERT INTO skill_snapshots VALUES (?, 'rust', ?, 100)", [D(2026, 11, 1) + datetime.timedelta(days=day), 80 - day])
    change = site.snapshot_change(con)
    assert change["enough"] and change["rising"][0][0] == "python" and change["falling"][0][0] == "rust"
    assert "Rising" in site.render({**site.collect(con)})


def test_empty_database_still_renders():
    con = make_db([])
    trends.build(con, today=D(2026, 11, 10))
    html = site.render(site.collect(con))
    assert "MarketLens" in html and "0.0%" in html
