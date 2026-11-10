"""Build one static web page (docs/index.html) from the DuckDB tables, so the results can be read without running SQL.

The page has no JavaScript and no outside files. It shows what the data says today and says plainly what it cannot
say yet (a real trend needs several weeks of daily snapshots).

Run: python -m marketlens.site --db data/marketlens.duckdb --out docs
Then turn on GitHub Pages for the repo (Settings, Pages, branch main, folder /docs).
"""
import argparse
import os
from html import escape

from . import store
from .trends import TECH_FAMILIES

MIN_TREND_DAYS = 14   # fewer daily snapshots than this and the page refuses to draw a trend
MIN_FAMILY_JOBS = 30  # a role family needs this many jobs before its skill shares mean anything


def collect(con):
    """Everything the page shows, as plain Python data. Kept separate from the HTML so it can be tested."""
    total = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
    with_skill = con.execute("SELECT count(DISTINCT job_key) FROM job_skills").fetchone()[0]
    days = con.execute("SELECT count(DISTINCT run_date) FROM skill_snapshots").fetchone()[0]
    latest = con.execute("SELECT max(run_date) FROM skill_snapshots").fetchone()[0]
    data = {"total": total, "with_skill": with_skill, "days": days, "latest": latest}

    data["families"] = con.execute(
        "SELECT role_family, count(*) FROM job_facts GROUP BY 1 ORDER BY 2 DESC").fetchall()
    data["top_skills"] = con.execute(
        "SELECT skill, jobs_with_skill * 100.0 / jobs_total, jobs_with_skill FROM skill_snapshots "
        "WHERE run_date = ? ORDER BY jobs_with_skill DESC, skill LIMIT 15", [latest]).fetchall() if latest else []

    by_family = []
    for family, count in data["families"]:
        if count < MIN_FAMILY_JOBS or family == "Other":
            continue
        top = con.execute(
            "SELECT skill, jobs_with_skill * 100.0 / jobs_total FROM skill_by_role WHERE role_family = ? "
            "ORDER BY jobs_with_skill DESC, skill LIMIT 8", [family]).fetchall()
        by_family.append((family, count, top))
    data["by_family"] = by_family

    by_city = []
    for place, count in con.execute(
        "SELECT city, count(*) FROM job_facts WHERE city <> 'unknown' GROUP BY 1 ORDER BY 2 DESC LIMIT 8").fetchall():
        top = con.execute(
            "SELECT skill, jobs_with_skill * 100.0 / jobs_total FROM skill_by_city WHERE city = ? "
            "ORDER BY jobs_with_skill DESC, skill LIMIT 5", [place]).fetchall()
        by_city.append((place, count, top))
    data["by_city"] = by_city
    data["trend"] = snapshot_change(con)
    return data


def snapshot_change(con, min_days=MIN_TREND_DAYS, top=8, min_jobs=40):
    """Change in the share of open jobs naming each skill, from the first daily snapshot to the latest.
    Returns {"enough": False, "days": n} until there are `min_days` days of snapshots."""
    days = con.execute("SELECT count(DISTINCT run_date) FROM skill_snapshots").fetchone()[0]
    if days < min_days:
        return {"enough": False, "days": days}
    first, last = con.execute("SELECT min(run_date), max(run_date) FROM skill_snapshots").fetchone()
    rows = []
    for skill, a, b, c in con.execute(
        "SELECT l.skill, f.jobs_with_skill * 100.0 / f.jobs_total, l.jobs_with_skill * 100.0 / l.jobs_total, l.jobs_with_skill "
        "FROM skill_snapshots l JOIN skill_snapshots f ON f.skill = l.skill AND f.run_date = ? "
        "WHERE l.run_date = ?", [first, last]).fetchall():
        if c >= min_jobs:
            rows.append((skill, a, b, b - a))
    rows.sort(key=lambda r: -r[3])
    return {"enough": True, "days": days, "first": first, "last": last,
            "rising": rows[:top], "falling": sorted(rows, key=lambda r: r[3])[:top]}


def _bars(rows):
    """rows: (label, percent). A bar is a div whose width is the percent."""
    if not rows:
        return "<p class='muted'>Nothing to show yet.</p>"
    out = ["<ul class='bars'>"]
    for label, pct in rows:
        out.append(f"<li><span class='label'>{escape(str(label))}</span>"
                   f"<span class='track'><span class='fill' style='width:{min(pct, 100):.1f}%'></span></span>"
                   f"<span class='num'>{pct:.0f}%</span></li>")
    out.append("</ul>")
    return "".join(out)


def _trend_html(trend):
    if not trend["enough"]:
        n = trend["days"]
        return (f"<p>There {'is' if n == 1 else 'are'} <b>{n} day{'s' if n != 1 else ''}</b> of daily snapshots so far. "
                f"A trend needs at least {MIN_TREND_DAYS} days, measured the same way every day, so this page does not "
                "draw one yet. It will appear on its own once the daily runs have built up enough history.</p>")

    def table(title, rows):
        body = "".join(f"<tr><td>{escape(s)}</td><td>{a:.1f}%</td><td>{b:.1f}%</td><td>{d:+.1f} points</td></tr>"
                       for s, a, b, d in rows)
        return (f"<h3>{title}</h3><table><tr><th>Skill</th><th>{trend['first']}</th><th>{trend['last']}</th>"
                f"<th>Change</th></tr>{body}</table>")
    return (f"<p>Share of open jobs that name each skill, {trend['first']} compared with {trend['last']} "
            f"({trend['days']} daily snapshots).</p>" + table("Rising", trend["rising"]) + table("Falling", trend["falling"]))


CSS = """
:root{--bg:#fbfaf7;--fg:#1d2327;--muted:#5b656b;--card:#fff;--line:#e3e0d8;--accent:#0f766e;--track:#e8efed}
@media (prefers-color-scheme:dark){:root{--bg:#14181a;--fg:#e8ecee;--muted:#9aa5ab;--card:#1c2224;--line:#2c3437;--accent:#2dd4bf;--track:#27312f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:1.9rem;margin:0 0 4px}h2{font-size:1.25rem;margin:40px 0 8px}h3{font-size:1.05rem;margin:20px 0 6px}
.muted{color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
.stat b{display:block;font-size:1.6rem}.stat span{color:var(--muted);font-size:.9rem}
.bars{list-style:none;margin:8px 0;padding:0}
.bars li{display:grid;grid-template-columns:150px 1fr 48px;gap:10px;align-items:center;margin:5px 0}
.track{background:var(--track);border-radius:4px;height:12px;overflow:hidden}.fill{display:block;height:100%;background:var(--accent)}
.num{text-align:right;font-variant-numeric:tabular-nums}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin:8px 0}
summary{cursor:pointer;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:.95rem}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
@media (max-width:520px){.bars li{grid-template-columns:110px 1fr 40px}}
"""


def render(data):
    total, with_skill = data["total"], data["with_skill"]
    pct = (with_skill * 100 / total) if total else 0
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>MarketLens job market snapshot</title>", f"<style>{CSS}</style></head><body><main>",
        "<h1>MarketLens</h1>",
        "<p class='muted'>What skills job postings ask for, from public company job boards. Rebuilt from the daily run.</p>",
        "<div class='stats'>",
        f"<div class='stat'><b>{total:,}</b><span>open jobs after removing duplicates</span></div>",
        f"<div class='stat'><b>{pct:.1f}%</b><span>of jobs have at least one skill found</span></div>",
        f"<div class='stat'><b>{data['days']}</b><span>day(s) of daily snapshots</span></div>",
        f"<div class='stat'><b>{data['latest'] or 'none'}</b><span>latest snapshot</span></div></div>",
        "<h2>Most requested skills</h2>",
        "<p class='muted'>Share of all open jobs whose description names the skill.</p>",
        _bars([(s, p) for s, p, _ in data["top_skills"]]),
        "<h2>Jobs by role family</h2>",
        _bars([(f, c * 100 / total) for f, c in data["families"]] if total else []),
        "<h2>Top skills by role family</h2>",
        "<p class='muted'>Share of that family's jobs that name the skill. Families with fewer than "
        f"{MIN_FAMILY_JOBS} jobs are left out.</p>",
    ]
    for family, count, top in data["by_family"]:
        parts.append(f"<details{' open' if family in TECH_FAMILIES[:1] else ''}><summary>{escape(family)} "
                     f"<span class='muted'>({count:,} jobs)</span></summary>{_bars(top)}</details>")
    parts.append("<h2>Top skills by city</h2><p class='muted'>The eight places with the most jobs. "
                 "\"remote\" is jobs listed as remote.</p>")
    for place, count, top in data["by_city"]:
        parts.append(f"<details><summary>{escape(place.title())} <span class='muted'>({count:,} jobs)</span>"
                     f"</summary>{_bars(top)}</details>")
    parts += ["<h2>Trend over time</h2>", _trend_html(data["trend"]),
              "<h2>What this does not show</h2><ul>",
              "<li>It covers jobs on about 36 company job boards plus one remote jobs feed. It is not the whole market, "
              "and it leans toward tech companies.</li>",
              "<li>A share is how often a skill is <em>named</em> in a posting, not how much employers need it.</li>",
              "<li>Skills come from a fixed dictionary, so a skill not in the dictionary is never counted.</li>",
              "<li>Only jobs that are still open are seen. Filled jobs disappear before they can be counted.</li></ul>",
              "</main></body></html>"]
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Build the static results page.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    ap.add_argument("--out", default="docs")
    args = ap.parse_args()
    con = store.connect(args.db)
    html = render(collect(con))
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "index.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"wrote {path} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
