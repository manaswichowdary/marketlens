"""Write the skills found in each job to the job_skills table and print how well the dictionary did.

Run: python -m marketlens.extract --db data/marketlens.duckdb
"""
import argparse
import random
import re
from collections import Counter, defaultdict

from . import dedupe, skills, store


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
MIN_SHARE = 0.2   # a sentence in at least this share of one company's postings is boilerplate ...
MIN_COUNT = 10    # ... and it must appear in at least this many postings


def sentences(text):
    return [s.strip() for s in SENTENCE_SPLIT.split(text or "") if s.strip()]


def find_boilerplate(descriptions):
    """Sentences that repeat across many postings of one company ("About us", benefits, legal text).
    A skill named only in a sentence like that describes the company, not the job."""
    counts = Counter()
    for d in descriptions:
        counts.update({s.lower() for s in sentences(d)})
    threshold = max(MIN_COUNT, int(len(descriptions) * MIN_SHARE))
    return {s for s, c in counts.items() if c >= threshold}


def remove_boilerplate(text, boilerplate):
    return " ".join(s for s in sentences(text) if s.lower() not in boilerplate)


def own_product_skills(company, found):
    """Skills that are named after the company itself (Databricks, Datadog, MongoDB, Elastic -> elasticsearch).
    A job at that company talks about its own product, which does not mean the job needs it as a skill."""
    tokens = [t for t in dedupe.norm_company(company).split() if len(t) >= 5]
    return {s for s in found if any(s.startswith(t) for t in tokens)}


def run(con):
    jobs = con.execute(
        "SELECT source || ':' || source_id, title, description, category, company FROM jobs"
    ).fetchall()
    by_company = defaultdict(list)
    for job in jobs:
        by_company[job[4]].append(job[2])
    boilerplate = {company: find_boilerplate(texts) for company, texts in by_company.items()}

    con.execute("DROP TABLE IF EXISTS job_skills")
    con.execute("CREATE TABLE job_skills (job_key VARCHAR, skill VARCHAR, method VARCHAR)")
    rows, per_job = [], {}
    removed = total = 0
    for key, title, description, category, company in jobs:
        all_sentences = sentences(description)
        clean = remove_boilerplate(description, boilerplate[company])
        total += len(all_sentences)
        removed += len(all_sentences) - len(sentences(clean))
        found = skills.extract(title, clean)
        found -= own_product_skills(company, found) - skills.extract(title, "")   # keep it if it is in the title
        per_job[key] = (title, category, found)
        rows.extend([key, s, "dictionary"] for s in sorted(found))
    if rows:
        con.executemany("INSERT INTO job_skills VALUES (?, ?, ?)", rows)
    run.boilerplate_stats = (removed, total)    # read by main() for the report
    return per_job


def report(per_job, sample_size=10, seed=1):
    total = len(per_job)
    with_skill = sum(1 for _, _, f in per_job.values() if f)
    counts = {}
    for _, _, f in per_job.values():
        for s in f:
            counts[s] = counts.get(s, 0) + 1
    empty = [(t, c) for t, c, f in per_job.values() if not f]
    by_cat = {}
    for _, c in empty:
        by_cat[c or "(none)"] = by_cat.get(c or "(none)", 0) + 1
    rnd = random.Random(seed)
    sample = rnd.sample([(t, sorted(f)) for t, _, f in per_job.values() if f], min(sample_size, with_skill))
    return {
        "total": total, "with_skill": with_skill, "empty": len(empty),
        "avg_skills": (sum(len(f) for _, _, f in per_job.values()) / total) if total else 0,
        "top": sorted(counts.items(), key=lambda kv: -kv[1])[:25],
        "empty_by_category": sorted(by_cat.items(), key=lambda kv: -kv[1])[:10],
        "empty_titles": [t for t, _ in empty[:8]],
        "sample": sample,
    }


def main():
    ap = argparse.ArgumentParser(description="Extract skills with the dictionary.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    args = ap.parse_args()
    con = store.connect(args.db)
    rep = report(run(con))
    pct = rep["with_skill"] / rep["total"] if rep["total"] else 0
    removed, total = run.boilerplate_stats
    print(f"jobs: {rep['total']}")
    print(f"company boilerplate sentences ignored: {removed} of {total} ({removed / total:.1%})" if total else "")
    print(f"jobs with at least one skill: {rep['with_skill']} ({pct:.1%})")
    print(f"jobs with no skill found: {rep['empty']} ({1 - pct:.1%})   average skills per job: {rep['avg_skills']:.1f}")
    print("\nTop skills:")
    for s, n in rep["top"]:
        print(f"  {s:<24} {n}")
    print("\nJobs with no skill found, by category (these are what a language model would have to read):")
    for c, n in rep["empty_by_category"]:
        print(f"  {c:<32} {n}")
    print("\nSome titles with no skill found:")
    for t in rep["empty_titles"]:
        print(f"  {t}")
    print("\n10 random jobs and the skills found (check these by eye):")
    for t, f in rep["sample"]:
        print(f"  {t[:60]:<60} -> {', '.join(f)}")


if __name__ == "__main__":
    main()
