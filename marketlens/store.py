"""DuckDB storage: raw JSON files on disk, one cleaned table, and a log of every run."""
import json
import os
from datetime import datetime, timezone

import duckdb

CREATE_POSTINGS = """
CREATE TABLE IF NOT EXISTS postings (
    source VARCHAR, source_id VARCHAR, title VARCHAR, company VARCHAR, location VARCHAR,
    description VARCHAR, posted_at VARCHAR, url VARCHAR, category VARCHAR,
    salary_min DOUBLE, salary_max DOUBLE, fetched_at VARCHAR,
    PRIMARY KEY (source, source_id)
)
"""
CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    source VARCHAR, started_at VARCHAR, fetched INTEGER, new_rows INTEGER, status VARCHAR, error VARCHAR
)
"""
COLUMNS = ["source", "source_id", "title", "company", "location", "description", "posted_at",
           "url", "category", "salary_min", "salary_max", "fetched_at"]


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = duckdb.connect(path)
    con.execute(CREATE_POSTINGS)
    con.execute(CREATE_RUNS)
    return con


def save_raw(raw, source, raw_dir, stamp):
    """Keep exactly what the source sent, so a bug in our cleaning can be fixed by replaying it."""
    folder = os.path.join(raw_dir, source)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{stamp}.json")
    with open(path, "w") as f:
        json.dump(raw, f)
    return path


def upsert(con, postings):
    """Insert postings we have not seen. A posting we already have (same source and id) is skipped, so
    running the pipeline twice never creates duplicates. Returns how many were new."""
    have = {(a, b) for a, b in con.execute("SELECT source, source_id FROM postings").fetchall()}
    rows = []
    for p in postings:
        key = (p.source, p.source_id)
        if key in have:
            continue
        have.add(key)  # also protects against the same id appearing twice inside one batch
        row = p.as_dict()
        rows.append([row[c] for c in COLUMNS])
    if rows:
        con.executemany(
            f"INSERT INTO postings ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", rows
        )
    return len(rows)


def log_run(con, source, started_at, fetched, new_rows, status, error=""):
    con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", [source, started_at, fetched, new_rows, status, error])
