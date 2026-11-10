"""Skill trends by role and city, plus a daily snapshot so real trends build up over time.

Tables written: job_facts (role family, city and posting date for each job), skill_by_role, skill_by_city,
skill_weekly, and skill_snapshots (one row per skill per day, added to on every run).

Two kinds of trend, and an honest warning about the first:
  * Posting date trend (rising and falling): compares jobs first published in the last 4 weeks with the 4 weeks
    before. It only sees jobs that are STILL OPEN today. Jobs that were filled and taken down are missing, which
    favors older postings that are hard to fill. Treat it as a hint, not a measurement.
  * Daily snapshots: the share of open jobs that name each skill, saved every day. After a few weeks of daily runs
    this is a real trend, because every day is measured the same way.

Run: python -m marketlens.trends --db data/marketlens.duckdb
"""
import argparse
import datetime
import re

from . import dedupe, store

# First match wins, so the specific families come before the general ones. Legal and Compliance sits before
# Marketing on purpose: "Ads Policy" is a policy job, not a marketing job.
ROLE_RULES = [
    ("Engineering Management", r"engineering manager|director of engineering|head of engineering|vp of engineering|vp, engineering|manager, engineering|director, engineering|tech lead manager|manager i, engineering"),
    ("Solutions Engineering", r"solutions? architect|solutions? engineer|solutions? consultant|sales engineer|forward deployed|technical account|customer engineer|technical consultant|consulting architect|technical architect|applied ai architect|industry consultant|transformation consultant|field engineer"),
    ("ML and Data Science", r"machine learning|\bml\b|data scientist|research scientist|applied scientist|ai engineer|research engineer|deep learning"),
    ("Data Engineering", r"data engineer|analytics engineer|data platform|etl|data infrastructure"),
    ("Data Analysis", r"data analyst|business analyst|analytics|business intelligence|\bbi\b"),
    ("Security", r"security|infosec|penetration|threat|appsec|incident response"),
    ("Infrastructure", r"devops|\bsre\b|site reliability|platform engineer|infrastructure|cloud engineer|systems engineer|reliability"),
    ("Software Engineering", r"software engineer|software developer|\bsde\b|developer|backend|back end|frontend|front end|full.?stack|mobile engineer|\bios\b|android|\bengineer\b"),
    ("Product", r"product manager|product management|product owner|\bgroup product\b"),
    ("Design", r"designer|design\b|ux\b|ui\b"),
    ("Sales", r"account executive|sales|business development|\bsdr\b|\bbdr\b|account manager|partnerships?|\bae\b|seller|renewals?|regional vice president|partner manager|channels?|bid coordinator|account director"),
    ("Finance", r"finance|accounting|controller|financial|tax\b|treasury|payroll|credit|underwrit"),
    ("Legal and Compliance", r"legal|counsel|compliance|attorney|paralegal|lawyer|regulatory|privacy|policy|advocacy|trust and safety|trust & safety|audit|sox|kyc|\baml\b|risk|fraud|contracts manager"),
    ("Marketing", r"marketing|brand|content|communications|\bseo\b|growth|ad ops|campaigns?|advertising|\bads\b"),
    ("Customer", r"customer success|customer support|support engineer|customer service|implementation|customer experience|claims|product support|support specialist|customer care|community"),
    ("People", r"recruit|talent|people|\bhr\b|human resources|sourcer|benefits"),
    ("Operations and Strategy", r"operations|operational|program manager|program lead|project manager|strateg|chief of staff|corporate development|\bgtm\b|deployment|installation|logistics|supply chain|procurement|customs|localization|facilities|workplace|area manager|lab manager|merchandising"),
]
TECH_FAMILIES = ["Software Engineering", "Infrastructure", "ML and Data Science", "Data Engineering",
                 "Data Analysis", "Security", "Engineering Management", "Solutions Engineering"]
ROLE_PATTERNS = [(name, re.compile(rx)) for name, rx in ROLE_RULES]

CITY_ALIASES = {"sf": "san francisco", "nyc": "new york", "ny": "new york", "new york city": "new york",
                "chi": "chicago", "sea": "seattle", "atl": "atlanta", "la": "los angeles", "dc": "washington",
                "bos": "boston", "aus": "austin"}
# Text that names a work arrangement or a whole country or region, not a city.
NOT_A_CITY = {"", "location", "n a", "tbd", "united states", "usa", "us", "u s", "united kingdom", "uk", "canada",
              "india", "germany", "ireland", "australia", "emea", "apac", "amer", "latam", "global", "worldwide",
              "anywhere", "americas", "europe"}


def role_family(title):
    t = (title or "").lower()
    for name, pattern in ROLE_PATTERNS:
        if pattern.search(t):
            return name
    return "Other"


def city(location):
    """The first place listed (not the first alphabetically), lower case, with common abbreviations spelled out.
    'remote' stays 'remote'. "Hybrid" and "Onsite" are dropped, so "Hybrid - San Francisco" is San Francisco.
    A country or region on its own, or empty or placeholder text, becomes 'unknown'."""
    text = (location or "").lower()
    first = re.split(r"[;|/\u2022]|\bor\b", text)[0]
    if "remote" in first:
        return "remote"
    first = re.sub(r"\b(hybrid|onsite|on site|in office|in-office)\b", " ", first)
    place = " ".join(re.sub(r"[^a-z0-9 ]", " ", first.split(",")[0]).split())
    place = place.removeprefix("us ").strip()
    if place in NOT_A_CITY:
        return "unknown"
    return CITY_ALIASES.get(place, place)


def parse_date(text):
    try:
        return datetime.date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


def build(con, today=None):
    today = today or datetime.date.today()
    jobs = con.execute("SELECT source || ':' || source_id, title, location, posted_at FROM jobs").fetchall()
    facts = [(k, role_family(t), city(loc), parse_date(p)) for k, t, loc, p in jobs]

    con.execute("DROP TABLE IF EXISTS job_facts")
    con.execute("CREATE TABLE job_facts (job_key VARCHAR, role_family VARCHAR, city VARCHAR, posted_date DATE)")
    if facts:
        con.executemany("INSERT INTO job_facts VALUES (?, ?, ?, ?)", facts)

    for table, col in (("skill_by_role", "role_family"), ("skill_by_city", "city")):
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"""
            CREATE TABLE {table} AS
            WITH sizes AS (SELECT {col}, count(*) AS jobs_total FROM job_facts GROUP BY 1)
            SELECT f.{col}, s.skill, count(*) AS jobs_with_skill, z.jobs_total
            FROM job_skills s JOIN job_facts f USING (job_key) JOIN sizes z ON z.{col} = f.{col}
            GROUP BY f.{col}, s.skill, z.jobs_total""")

    con.execute("DROP TABLE IF EXISTS skill_weekly")
    con.execute("""
        CREATE TABLE skill_weekly AS
        WITH weeks AS (
            SELECT date_trunc('week', posted_date)::DATE AS week, count(*) AS jobs_total
            FROM job_facts WHERE posted_date IS NOT NULL GROUP BY 1)
        SELECT date_trunc('week', f.posted_date)::DATE AS week, s.skill, count(*) AS jobs_with_skill, w.jobs_total
        FROM job_skills s JOIN job_facts f USING (job_key)
        JOIN weeks w ON w.week = date_trunc('week', f.posted_date)::DATE
        WHERE f.posted_date IS NOT NULL GROUP BY 1, 2, 4""")

    # The daily snapshot. Running twice on the same day replaces that day, so it never doubles.
    con.execute("""CREATE TABLE IF NOT EXISTS skill_snapshots
                   (run_date DATE, skill VARCHAR, jobs_with_skill INTEGER, jobs_total INTEGER)""")
    con.execute("DELETE FROM skill_snapshots WHERE run_date = ?", [today])
    total = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    con.execute(
        "INSERT INTO skill_snapshots SELECT ?, skill, count(DISTINCT job_key), ? FROM job_skills GROUP BY skill",
        [today, total],
    )


def rising_falling(con, window_days=28, min_jobs=40, top=8, families=TECH_FAMILIES):
    """Compare the last `window_days` of posting dates with the window before it, inside the given role families
    only. Comparing all jobs would show a change in WHAT was hired for (more sales, fewer engineers) as if it were a
    change in skills. Returns a dict."""
    newest = con.execute("SELECT max(posted_date) FROM job_facts WHERE list_contains(?, role_family)", [families]).fetchone()[0]
    if newest is None:
        return {"enough": False}
    recent_start = newest - datetime.timedelta(days=window_days - 1)
    prior_start = recent_start - datetime.timedelta(days=window_days)
    n_recent = con.execute("SELECT count(*) FROM job_facts WHERE posted_date >= ? AND list_contains(?, role_family)", [recent_start, families]).fetchone()[0]
    n_prior = con.execute(
        "SELECT count(*) FROM job_facts WHERE posted_date >= ? AND posted_date < ? AND list_contains(?, role_family)",
        [prior_start, recent_start, families],
    ).fetchone()[0]
    out = {"newest": newest, "recent_start": recent_start, "prior_start": prior_start,
           "n_recent": n_recent, "n_prior": n_prior, "enough": n_recent >= 100 and n_prior >= 100}
    if not out["enough"]:
        return out
    counts = {}
    for skill, date, in con.execute(
        "SELECT s.skill, f.posted_date FROM job_skills s JOIN job_facts f USING (job_key) "
        "WHERE f.posted_date >= ? AND list_contains(?, f.role_family)",
        [prior_start, families],
    ).fetchall():
        key = "recent" if date >= recent_start else "prior"
        counts.setdefault(skill, {"recent": 0, "prior": 0})[key] += 1
    rows = []
    for skill, c in counts.items():
        if c["recent"] + c["prior"] < min_jobs:
            continue
        r, p = c["recent"] / n_recent, c["prior"] / n_prior
        rows.append((skill, p, r, (r - p) * 100, c["recent"], c["prior"]))
    rows.sort(key=lambda x: -x[3])
    out["rising"], out["falling"] = rows[:top], sorted(rows, key=lambda x: x[3])[:top]
    return out


def main():
    ap = argparse.ArgumentParser(description="Build skill trend tables.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    args = ap.parse_args()
    con = store.connect(args.db)
    build(con)

    n, first, last = con.execute("SELECT count(*), min(posted_date), max(posted_date) FROM job_facts").fetchone()
    undated = con.execute("SELECT count(*) FROM job_facts WHERE posted_date IS NULL").fetchone()[0]
    print(f"jobs: {n}   posting dates from {first} to {last}   (no date: {undated})")
    days = con.execute("SELECT count(DISTINCT run_date) FROM skill_snapshots").fetchone()[0]
    print(f"daily snapshots saved so far: {days} day(s). A real trend needs several weeks of them.")

    print("\nJobs by role family:")
    for fam, c in con.execute("SELECT role_family, count(*) FROM job_facts GROUP BY 1 ORDER BY 2 DESC").fetchall():
        print(f"  {fam:<26} {c}")

    print("\nTop skills by role family (share of that family's jobs that name the skill):")
    for fam, c in con.execute(
        "SELECT role_family, count(*) FROM job_facts GROUP BY 1 HAVING count(*) >= 30 ORDER BY 2 DESC LIMIT 6"
    ).fetchall():
        top = con.execute(
            "SELECT skill, jobs_with_skill * 100.0 / jobs_total FROM skill_by_role WHERE role_family = ? "
            "ORDER BY jobs_with_skill DESC LIMIT 6", [fam]).fetchall()
        print(f"  {fam}: " + ", ".join(f"{s} {p:.0f}%" for s, p in top))

    print("\nTop skills by city:")
    for place, c in con.execute(
        "SELECT city, count(*) FROM job_facts WHERE city NOT IN ('unknown') GROUP BY 1 ORDER BY 2 DESC LIMIT 6"
    ).fetchall():
        top = con.execute(
            "SELECT skill, jobs_with_skill * 100.0 / jobs_total FROM skill_by_city WHERE city = ? "
            "ORDER BY jobs_with_skill DESC LIMIT 5", [place]).fetchall()
        print(f"  {place} ({c} jobs): " + ", ".join(f"{s} {p:.0f}%" for s, p in top))

    rf = rising_falling(con)
    print("\nRising and falling by posting date, inside technical roles only (jobs still open today, so read this as a hint):")
    if not rf.get("enough"):
        print(f"  Not enough dated jobs in both windows yet (recent {rf.get('n_recent', 0)}, prior {rf.get('n_prior', 0)}).")
    else:
        print(f"  recent {rf['recent_start']} to {rf['newest']} ({rf['n_recent']} technical jobs) vs the 28 days before ({rf['n_prior']} jobs)")
        for label, rows in (("rising", rf["rising"]), ("falling", rf["falling"])):
            print(f"  {label}:")
            for skill, p, r, change, nr, np_ in rows:
                print(f"    {skill:<22} {p:.1%} -> {r:.1%}  ({change:+.1f} points, {nr} recent / {np_} prior jobs)")


if __name__ == "__main__":
    main()
