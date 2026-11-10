"""Find the same job posted more than once.

Two postings are treated as the same job when they have the same company and the same place, and the titles
match after cleaning. The cleaning is careful: a team, a customer type or a language in the title (for example
"(Tax)" or "- IAM" or "(German-Speaking)") is part of the job, so it is kept. The only fuzzy match allowed is one
misspelled word and nothing else. When in doubt, two postings are kept apart, because merging two real jobs
loses a posting, and leaving a repeat in costs only a small error in the counts.

Run: python -m marketlens.dedupe --db data/marketlens.duckdb
"""
import argparse
import re
from collections import defaultdict

from rapidfuzz import fuzz

from . import store

TYPO_RATIO = 85   # two words this similar (out of 100) are treated as one misspelled word
MIN_TYPO_LEN = 5  # short words such as "cxi" and "iam" are never treated as typos of each other

# Words that make two jobs different even if the rest of the title matches.
DIFFERENT_JOB_WORDS = {
    "senior", "staff", "principal", "junior", "lead", "intern", "internship", "associate", "manager", "director",
    "head", "vp", "backend", "frontend", "fullstack", "mobile", "ios", "android", "data", "ml", "security",
    "platform", "infrastructure", "sales", "marketing", "design", "product", "recruiter", "analyst", "scientist",
}
COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "gmbh"}
# Words inside brackets that say nothing about the job itself, so a title with only these in brackets is cleaned.
TITLE_NOISE = {"remote", "hybrid", "onsite", "on", "site", "us", "usa", "contract", "temporary", "fulltime",
               "full", "time", "part", "ok", "m", "f", "d", "w", "x", "all", "genders"}
# Words in a location that do not name a place.
LOCATION_NOISE = {"remote", "us", "usa", "united", "states", "america", "americas", "north", "anywhere",
                  "worldwide", "and", "or", "hybrid"}
ABBREVIATIONS = {"sr": "senior", "jr": "junior"}


def norm_company(text):
    words = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).split()
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def _drop_noise_brackets(match):
    inner = match.group(0)[1:-1]
    words = re.sub(r"[^a-z0-9 ]", " ", inner).split()
    return " " if all(w in TITLE_NOISE for w in words) else f" {inner} "   # keep meaningful notes


def norm_title(text):
    t = (text or "").lower().replace("&", " and ")
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", _drop_noise_brackets, t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return " ".join(ABBREVIATIONS.get(w, w) for w in t.split())


def norm_location(text):
    """All the places listed, cleaned and sorted. "Remote" on its own stays "remote". "Remote - Texas" stays
    apart from "Remote - Virginia", because those are usually separate openings."""
    places = []
    for part in re.split(r"[;|/]|\bor\b", (text or "").lower()):
        if "remote" in part:
            rest = [w for w in re.sub(r"[^a-z0-9 ]", " ", part).split() if w not in LOCATION_NOISE]
            places.append("remote " + " ".join(rest) if rest else "remote")
        else:
            city = part.split(",")[0]
            clean = " ".join(re.sub(r"[^a-z0-9 ]", " ", city).split())
            if clean:
                places.append(clean)
    return "|".join(sorted(set(places)))


def _same_job(title_a, title_b):
    """Same number of words, and exactly one word differs by a spelling slip."""
    a, b = title_a.split(), title_b.split()
    if len(a) != len(b):
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    if min(len(x), len(y)) < MIN_TYPO_LEN or x.isdigit() or y.isdigit():
        return False
    if x in DIFFERENT_JOB_WORDS or y in DIFFERENT_JOB_WORDS:
        return False
    return fuzz.ratio(x, y) >= TYPO_RATIO


def _pick_canonical(group):
    """Keep the oldest posting. If dates tie, keep the one with the longest description."""
    return sorted(group, key=lambda r: (r["posted_at"] or "9999", -len(r["description"] or ""), r["source"], r["source_id"]))[0]


def find_duplicates(rows):
    """rows: list of dicts with source, source_id, company, title, location, posted_at, description.
    Returns a list of (duplicate_row, kept_row, method) where method is 'exact' or 'fuzzy'."""
    # Step 1: exact match on the cleaned company, title and place.
    groups = defaultdict(list)
    for r in rows:
        groups[(norm_company(r["company"]), norm_title(r["title"]), norm_location(r["location"]))].append(r)

    duplicates, kept = [], []
    for (company, title, place), group in groups.items():
        keep = _pick_canonical(group)
        kept.append((company, place, title, keep))
        for r in group:
            if r is not keep:
                duplicates.append((r, keep, "exact"))

    # Step 2: near matches. Only compare titles inside the same company and place.
    buckets = defaultdict(list)
    for company, place, title, keep in kept:
        buckets[(company, place)].append((title, keep))
    for items in buckets.values():
        parent = list(range(len(items)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if _same_job(items[i][0], items[j][0]):
                    parent[find(i)] = find(j)
        merged = defaultdict(list)
        for i in range(len(items)):
            merged[find(i)].append(items[i][1])
        for members in merged.values():
            if len(members) > 1:
                keep = _pick_canonical(members)
                for r in members:
                    if r is not keep:
                        duplicates.append((r, keep, "fuzzy"))
    return duplicates


def run(con):
    """Rebuild the dedupe_map table and the jobs view. Returns a small report."""
    cols = ["source", "source_id", "company", "title", "location", "posted_at", "description"]
    rows = [dict(zip(cols, r)) for r in con.execute(f"SELECT {', '.join(cols)} FROM postings").fetchall()]
    dups = find_duplicates(rows)

    con.execute("DROP VIEW IF EXISTS jobs")
    con.execute("DROP TABLE IF EXISTS dedupe_map")
    con.execute(
        "CREATE TABLE dedupe_map (source VARCHAR, source_id VARCHAR, kept_source VARCHAR, kept_id VARCHAR, method VARCHAR)"
    )
    if dups:
        con.executemany(
            "INSERT INTO dedupe_map VALUES (?, ?, ?, ?, ?)",
            [[d["source"], d["source_id"], k["source"], k["source_id"], m] for d, k, m in dups],
        )
    con.execute(
        """CREATE VIEW jobs AS
           SELECT p.* FROM postings p
           LEFT JOIN dedupe_map d ON d.source = p.source AND d.source_id = p.source_id
           WHERE d.source_id IS NULL"""
    )
    total = len(rows)
    by_method = {m: sum(1 for _, _, x in dups if x == m) for m in ("exact", "fuzzy")}
    return {
        "total": total,
        "duplicates": len(dups),
        "unique": total - len(dups),
        "duplicate_rate": (len(dups) / total) if total else 0.0,
        "by_method": by_method,
        "fuzzy_samples": [(d, k) for d, k, m in dups if m == "fuzzy"][:10],
        "exact_samples": [
            (d, k) for d, k, m in dups
            if m == "exact" and (d["title"] != k["title"] or d["location"] != k["location"])
        ][:10],
    }


def main():
    ap = argparse.ArgumentParser(description="Mark duplicate postings.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    args = ap.parse_args()
    con = store.connect(args.db)
    rep = run(con)
    print(f"postings before: {rep['total']}")
    print(f"duplicates found: {rep['duplicates']} ({rep['duplicate_rate']:.1%})  exact {rep['by_method']['exact']}, fuzzy {rep['by_method']['fuzzy']}")
    print(f"unique jobs after: {rep['unique']}")
    if rep["exact_samples"]:
        print("\nSome exact matches where the raw text differed (check these by eye):")
        for d, k in rep["exact_samples"]:
            print(f"  [{d['company']}]  '{d['title']}' @ {d['location']}  ==  '{k['title']}' @ {k['location']}")
    if rep["fuzzy_samples"]:
        print("\nNear matches that were merged (one misspelled word):")
        for d, k in rep["fuzzy_samples"]:
            print(f"  [{d['company']} | {d['location']}]  '{d['title']}'  ==  '{k['title']}'")

if __name__ == "__main__":
    main()
