import datetime

from marketlens import dedupe, extract, store, trends
from marketlens.ingest.schema import Posting

D = datetime.date


def test_role_family_examples():
    cases = {
        "Senior Software Engineer, Payments": "Software Engineering",
        "Staff Data Engineer": "Data Engineering",
        "Machine Learning Engineer": "ML and Data Science",
        "Engineering Manager, Platform": "Engineering Management",
        "Solutions Architect - Financial Services": "Solutions Engineering",
        "Account Executive, Commercial": "Sales",
        "Product Security Engineer": "Security",
        "Site Reliability Engineer": "Infrastructure",
        "Senior Operations Manager": "Operations and Strategy",
        "Product Manager, Growth": "Product",
        "Corporate Counsel": "Legal and Compliance",
        "Solutions Consultant": "Solutions Engineering",
        "Senior Technical Program Manager": "Operations and Strategy",
        "Specialist Seller, Enterprise Core (AI Products)": "Sales",
        "Senior Internal Auditor": "Legal and Compliance",
        "Credit Risk Analyst Commercial Underwriter": "Finance",
        "Benefits Program Manager, EMEA": "People",
        "AE, Okta & Auth0": "Sales",
        "Digital Ad Ops Coordinator, Lyft Ads": "Marketing",
        "Trust and Safety Policy, Ads Policy, Lead (Europe)": "Legal and Compliance",   # policy, not marketing
        "Account Executive - Financial Services": "Sales",
        "Incident Response Manager - Product & Engineering": "Security",
    }
    for title, family in cases.items():
        assert trends.role_family(title) == family, title


def test_city_normalization():
    assert trends.city("San Francisco, CA; New York, NY") == "san francisco"   # first listed, not first alphabetically
    assert trends.city("SF, NYC, CHI") == "san francisco"
    assert trends.city("London OR Dublin") == "london"
    assert trends.city("US-NY") == "new york"
    assert trends.city("Remote - Texas") == "remote"
    assert trends.city("") == "unknown" and trends.city("LOCATION") == "unknown"
    assert trends.city("Hybrid") == "unknown" and trends.city("United States") == "unknown"
    assert trends.city("Hybrid - San Francisco, New York City, Austin") == "san francisco"
    assert trends.city("New York City, NY") == "new york"
    assert trends.city("San Mateo, CA United States") == "san mateo"
    assert trends.city("San Francisco, CA \u2022 New York, NY \u2022 United States") == "san francisco"


def test_parse_date_handles_bad_and_missing_dates():
    assert trends.parse_date("2026-11-09T10:00:00-05:00") == D(2026, 11, 9)
    assert trends.parse_date("") is None and trends.parse_date("not a date") is None


def make_db(posts):
    con = store.connect(":memory:")
    store.upsert(con, posts)
    dedupe.run(con)
    extract.run(con)
    return con


def P(i, title, desc, posted, location="Phoenix, AZ", company="Acme"):
    return Posting("greenhouse", str(i), title, company, location, desc, posted, "u", "", None, None, "t")


def test_build_makes_role_city_and_snapshot_tables_and_snapshot_is_repeatable():
    con = make_db([
        P(1, "Data Engineer", "Python and SQL", "2026-11-01"),
        P(2, "Data Engineer", "Python and Airflow", "2026-11-02", location="Austin, TX"),
        P(3, "Account Executive", "Salesforce experience", "2026-11-03"),
    ])
    trends.build(con, today=D(2026, 11, 10))
    role = dict(con.execute("SELECT skill, jobs_with_skill FROM skill_by_role WHERE role_family = 'Data Engineering'").fetchall())
    assert role == {"python": 2, "sql": 1, "airflow": 1}
    assert con.execute("SELECT jobs_total FROM skill_by_city WHERE city = 'phoenix' LIMIT 1").fetchone()[0] == 2
    snap = dict(con.execute("SELECT skill, jobs_with_skill FROM skill_snapshots").fetchall())
    assert snap["python"] == 2 and snap["salesforce"] == 1
    trends.build(con, today=D(2026, 11, 10))                       # same day again: replaced, not doubled
    assert con.execute("SELECT count(*) FROM skill_snapshots").fetchone()[0] == len(snap)
    trends.build(con, today=D(2026, 11, 11))                       # next day: a second set of rows
    assert con.execute("SELECT count(DISTINCT run_date) FROM skill_snapshots").fetchone()[0] == 2


def test_rising_and_falling_compare_two_windows_and_refuse_when_too_small():
    posts = []
    # Each posting is one sentence that is unique to it, so the boilerplate rule does not remove it.
    # prior window (Oct 1 to Oct 28): 120 jobs, python in 90, rust in 0
    for i in range(120):
        posts.append(P(i, f"Engineer {i}", (f"We need Python for project {i}." if i < 90 else f"We need nothing special for project {i}."), f"2026-10-{1 + i % 28:02d}"))
    # recent window (Oct 29 to Nov 25): 120 jobs, python in 30, rust in 60
    for i in range(120, 240):
        word = "Rust" if i < 180 else ("Python" if i < 210 else "nothing special")
        desc = f"We need {word} for project {i}."
        posts.append(P(i, f"Engineer {i}", desc, f"2026-11-{1 + i % 25:02d}" if i % 2 else f"2026-10-{29 + i % 3:02d}"))
    con = make_db(posts)
    trends.build(con, today=D(2026, 11, 26))
    rf = trends.rising_falling(con, window_days=28, min_jobs=40)
    assert rf["enough"]
    assert rf["rising"][0][0] == "rust" and rf["falling"][0][0] == "python"

    small = make_db([P(1, "Engineer", "Python", "2026-11-01")])
    trends.build(small, today=D(2026, 11, 2))
    assert trends.rising_falling(small)["enough"] is False


def test_rising_and_falling_ignore_non_technical_jobs():
    # A burst of sales jobs that all name Salesforce must not show up as a rising tech skill.
    posts = []
    for i in range(120):
        posts.append(P(i, f"Engineer {i}", f"We need Python for project {i}.", f"2026-10-{1 + i % 28:02d}"))
    for i in range(120, 240):
        posts.append(P(i, f"Engineer {i}", f"We need Python for project {i}.", f"2026-11-{1 + i % 25:02d}"))
    for i in range(240, 600):
        posts.append(P(i, f"Account Executive {i}", f"We need Salesforce for deal {i}.", f"2026-11-{1 + i % 25:02d}"))
    con = make_db(posts)
    trends.build(con, today=D(2026, 11, 26))
    rf = trends.rising_falling(con, min_jobs=10)
    assert rf["enough"]
    names = {r[0] for r in rf["rising"]} | {r[0] for r in rf["falling"]}
    assert "salesforce" not in names and rf["n_recent"] == 120
