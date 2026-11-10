"""The daily run on AWS Lambda.

Lambda starts empty every time, so the DuckDB file lives in S3: download it, run the pipeline, check that the run
looks healthy, tell Slack if it does not, and upload the file again. Raw JSON from each run is also kept in S3.

Settings come from environment variables (set by the deploy script):
  MARKETLENS_BUCKET   the S3 bucket that holds the database and the raw files
  SLACK_WEBHOOK_URL   optional, where problems are posted
"""
import glob
import os

import boto3
from botocore.exceptions import ClientError

from . import alerts, dedupe, extract, store, trends
from .ingest import run as ingest

DB_KEY = "db/marketlens.duckdb"
RAW_PREFIX = "raw/"
WORK_DIR = "/tmp/marketlens"


def download_db(s3, bucket, path):
    """Fetch yesterday's database. Returns False when there is none yet (the very first run)."""
    try:
        s3.download_file(bucket, DB_KEY, path)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def upload_run_files(s3, bucket, db_path, raw_dir):
    s3.upload_file(db_path, bucket, DB_KEY)
    for path in glob.glob(os.path.join(raw_dir, "*", "*.json")):
        source = os.path.basename(os.path.dirname(path))
        s3.upload_file(path, bucket, f"{RAW_PREFIX}{source}/{os.path.basename(path)}")


def run_pipeline(con, raw_dir, session=None):
    """Ingest, then rebuild the tables that depend on it. If Greenhouse (the main source) failed, the later steps
    would only repeat yesterday's work, so they are skipped. Returns a small summary dict."""
    summary = {"ingest": {}}
    for name in ("greenhouse", "remotive"):
        try:
            fetched, new_rows = ingest.run_source(name, con, raw_dir, session=session)
            summary["ingest"][name] = {"fetched": fetched, "new_rows": new_rows}
        except Exception as e:  # run_source already logged the failure in the runs table
            summary["ingest"][name] = {"error": str(e)[:200]}
    if "error" in summary["ingest"]["greenhouse"]:
        summary["skipped_transforms"] = True
        return summary
    summary["dedupe"] = {k: v for k, v in dedupe.run(con).items() if k in ("total", "duplicates", "unique")}
    per_job = extract.run(con)
    summary["jobs_with_skill"] = sum(1 for _, _, found in per_job.values() if found)
    trends.build(con)
    return summary


def handler(event, context, s3=None, session=None):
    bucket = os.environ["MARKETLENS_BUCKET"]
    os.environ.setdefault("HOME", "/tmp")
    s3 = s3 or boto3.client("s3")
    os.makedirs(WORK_DIR, exist_ok=True)
    db_path = os.path.join(WORK_DIR, "marketlens.duckdb")
    raw_dir = os.path.join(WORK_DIR, "raw")
    for old in glob.glob(os.path.join(raw_dir, "*", "*.json")):   # a warm Lambda can reuse /tmp, so start clean
        os.remove(old)

    had_db = download_db(s3, bucket, db_path)
    con = store.connect(db_path)
    try:
        summary = run_pipeline(con, raw_dir, session=session)
        problems = alerts.check_health(con)
    finally:
        con.close()
    upload_run_files(s3, bucket, db_path, raw_dir)    # upload even after a failure, so the failed run is logged

    summary["started_from_existing_db"] = had_db
    summary["problems"] = problems
    print(summary)
    if problems:
        webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
        if webhook:
            try:
                alerts.send_slack(webhook, alerts.format_message(problems))
            except Exception as e:
                print(f"could not send to Slack: {e}")
        raise RuntimeError("; ".join(problems))     # makes Lambda count this run as an error
    return summary
