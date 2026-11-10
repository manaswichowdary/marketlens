"""Pull postings from one or both sources and load them. Run: python -m marketlens.ingest.run --help"""
import argparse
import os

from dotenv import load_dotenv

from .. import store
from . import adzuna, greenhouse, remotive

COMPANIES_FILE = os.path.join(os.path.dirname(__file__), "companies.txt")


def run_source(name, con, raw_dir, session=None, **opts):
    started = store.now_iso()
    stamp = started.replace(":", "").replace("-", "")
    note = ""  # extra detail saved in the runs table, such as boards we had to skip
    try:
        if name == "adzuna":
            raw = adzuna.fetch_raw(
                os.environ["ADZUNA_APP_ID"], os.environ["ADZUNA_APP_KEY"],
                what=opts["what"], where=opts.get("where", ""), pages=opts.get("pages", 2), session=session,
            )
            postings = adzuna.normalize(raw, started)
        elif name == "remotive":
            raw = remotive.fetch_raw(search=opts.get("what", ""), session=session)
            postings = remotive.normalize(raw, started)
        elif name == "greenhouse":
            boards = greenhouse.load_boards(opts.get("companies_file", COMPANIES_FILE))
            raw, skipped = greenhouse.fetch_raw(boards, session=session, pause=opts.get("pause", 0.5))
            postings = greenhouse.normalize(raw, started)
            if skipped:
                note = "skipped: " + ", ".join(f"{b} ({why})" for b, why in skipped)
                print(f"greenhouse {note}")
        else:
            raise ValueError(f"unknown source {name}")
        store.save_raw(raw, name, raw_dir, stamp)
        new_rows = store.upsert(con, postings)
        store.log_run(con, name, started, len(postings), new_rows, "ok", note)
        return len(postings), new_rows
    except Exception as e:  # log the failure so a failed run is visible, then re-raise
        store.log_run(con, name, started, 0, 0, "failed", str(e)[:500])
        raise


def main():
    ap = argparse.ArgumentParser(description="Collect job postings into DuckDB.")
    ap.add_argument("--source", choices=["greenhouse", "remotive", "adzuna", "all"], default="all",
                    help="all means greenhouse and remotive. adzuna needs a paid key, so it is opt in")
    ap.add_argument("--what", default="software engineer", help="search words")
    ap.add_argument("--where", default="", help="Adzuna only, for example 'Phoenix'")
    ap.add_argument("--pages", type=int, default=2, help="Adzuna pages of 50 postings")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    ap.add_argument("--raw-dir", default="data/raw")
    args = ap.parse_args()

    load_dotenv()
    con = store.connect(args.db)
    sources = ["greenhouse", "remotive"] if args.source == "all" else [args.source]
    for name in sources:
        fetched, new_rows = run_source(name, con, args.raw_dir, what=args.what, where=args.where, pages=args.pages)
        print(f"{name}: fetched {fetched}, new rows {new_rows}")
    total = con.execute("SELECT count(*) FROM postings").fetchone()[0]
    print(f"postings table now has {total} rows")


if __name__ == "__main__":
    main()
