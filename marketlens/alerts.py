"""Health check for the pipeline. Reads the runs table and reports problems, and can post them to Slack.

Run: python -m marketlens.alerts            (prints the result, sends to Slack if SLACK_WEBHOOK_URL is set)
     python -m marketlens.alerts --test     (sends one test message so you can see the Slack setup works)
Exit code is 1 when there is a problem, so a scheduler can also mark the run as failed.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from . import store

EXPECTED_SOURCES = ("greenhouse",)   # a missing run for these is a problem. Remotive and Adzuna are optional.


def _parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def check_health(con, now=None, drop_ratio=0.5, max_age_hours=36, max_skipped_boards=5, expected=EXPECTED_SOURCES):
    """Return a list of plain sentences, one per problem. An empty list means healthy."""
    now = now or datetime.now(timezone.utc)
    problems = []
    runs = con.execute("SELECT source, started_at, fetched, new_rows, status, error FROM runs ORDER BY started_at").fetchall()
    by_source = {}
    for source, started_at, fetched, new_rows, status, error in runs:
        by_source.setdefault(source, []).append((started_at, fetched, status, error or ""))

    for source in expected:
        if source not in by_source:
            problems.append(f"{source}: no run has ever been recorded.")

    for source, rows in by_source.items():
        latest = rows[-1]
        if latest[2] == "failed":
            problems.append(f"{source}: the latest run failed ({latest[3][:150] or 'no error text'}).")

        ok = [r for r in rows if r[2] == "ok"]
        if source in expected:
            if not ok:
                problems.append(f"{source}: there is no successful run yet.")
                continue
            age = now - _parse(ok[-1][0])
            if age > timedelta(hours=max_age_hours):
                problems.append(f"{source}: the last successful run was {age.total_seconds() / 3600:.0f} hours ago "
                                f"(limit {max_age_hours}).")
        if len(ok) >= 2 and ok[-2][1] > 0 and ok[-1][1] < drop_ratio * ok[-2][1]:
            problems.append(f"{source}: the latest run fetched {ok[-1][1]} postings, but the run before fetched "
                            f"{ok[-2][1]}. A drop this large usually means a blocked request or a changed source.")
        if ok and ok[-1][3].startswith("skipped:"):
            skipped = ok[-1][3][len("skipped:"):].split("),")
            if len(skipped) > max_skipped_boards:
                problems.append(f"{source}: {len(skipped)} company boards were skipped in the latest run.")
    return problems


def format_message(problems):
    return "MarketLens needs attention:\n" + "\n".join(f"- {p}" for p in problems)


def send_slack(webhook_url, text, session=None):
    """Post a message to a Slack incoming webhook. Raises if Slack does not accept it."""
    resp = (session or requests).post(webhook_url, json={"text": text}, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Slack answered {resp.status_code}: {resp.text[:100]}")


def main():
    ap = argparse.ArgumentParser(description="Check the pipeline and alert if something is wrong.")
    ap.add_argument("--db", default="data/marketlens.duckdb")
    ap.add_argument("--test", action="store_true", help="send one test message to Slack and stop")
    args = ap.parse_args()
    load_dotenv()
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")

    if args.test:
        if not webhook:
            sys.exit("SLACK_WEBHOOK_URL is not set in your .env file.")
        send_slack(webhook, "MarketLens test message. If you can read this, alerts work.")
        print("Test message sent.")
        return

    con = store.connect(args.db)
    problems = check_health(con)
    if not problems:
        print("healthy: latest runs are recent, successful and not suspiciously small.")
        return
    message = format_message(problems)
    print(message)
    if webhook:
        try:
            send_slack(webhook, message)
            print("(sent to Slack)")
        except Exception as e:
            print(f"(could not send to Slack: {e})")
    else:
        print("(SLACK_WEBHOOK_URL is not set, so nothing was sent to Slack)")
    sys.exit(1)


if __name__ == "__main__":
    main()
