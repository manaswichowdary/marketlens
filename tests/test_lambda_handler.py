import os

import boto3
import duckdb
import pytest
from moto import mock_aws

from marketlens import lambda_handler as lh
from marketlens import store

BUCKET = "marketlens-test"


@pytest.fixture
def s3(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETLENS_BUCKET", BUCKET)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(lh, "WORK_DIR", str(tmp_path / "work"))
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def fake_ingest(fetched=100, fail=()):
    """Stands in for the network: logs a run the way the real run_source does, and writes one raw file."""
    def run_source(name, con, raw_dir, session=None, **opts):
        started = store.now_iso()
        if name in fail:
            store.log_run(con, name, started, 0, 0, "failed", "HTTP 500")
            raise RuntimeError("HTTP 500")
        store.save_raw({"n": fetched}, name, raw_dir, started.replace(":", "").replace("-", ""))
        store.log_run(con, name, started, fetched, 0, "ok", "")
        return fetched, 0
    return run_source


def stub_transforms(monkeypatch):
    monkeypatch.setattr(lh.dedupe, "run", lambda con: {"total": 1, "duplicates": 0, "unique": 1})
    monkeypatch.setattr(lh.extract, "run", lambda con: {})
    monkeypatch.setattr(lh.trends, "build", lambda con: None)


def db_runs(s3, tmp_path):
    local = str(tmp_path / "check.duckdb")
    s3.download_file(BUCKET, lh.DB_KEY, local)
    con = duckdb.connect(local, read_only=True)
    try:
        return con.execute("SELECT source, status FROM runs ORDER BY started_at").fetchall()
    finally:
        con.close()


def test_first_run_creates_the_database_and_keeps_raw_files(s3, monkeypatch, tmp_path):
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest())
    stub_transforms(monkeypatch)
    out = lh.handler({}, None, s3=s3)
    assert out["started_from_existing_db"] is False and out["problems"] == []
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
    assert lh.DB_KEY in keys
    assert any(k.startswith("raw/greenhouse/") for k in keys) and any(k.startswith("raw/remotive/") for k in keys)
    assert ("greenhouse", "ok") in db_runs(s3, tmp_path)


def test_second_run_builds_on_the_stored_database(s3, monkeypatch, tmp_path):
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest())
    stub_transforms(monkeypatch)
    lh.handler({}, None, s3=s3)
    out = lh.handler({}, None, s3=s3)
    assert out["started_from_existing_db"] is True
    assert [r for r in db_runs(s3, tmp_path) if r[0] == "greenhouse"] == [("greenhouse", "ok")] * 2


def test_failed_greenhouse_alerts_skips_transforms_and_still_saves_the_log(s3, monkeypatch, tmp_path):
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest(fail=("greenhouse",)))
    monkeypatch.setattr(lh.dedupe, "run", lambda con: pytest.fail("transforms must be skipped"))
    sent = []
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setattr(lh.alerts, "send_slack", lambda url, text, session=None: sent.append(text))
    with pytest.raises(RuntimeError, match="latest run failed"):
        lh.handler({}, None, s3=s3)
    assert sent and "greenhouse" in sent[0]
    assert ("greenhouse", "failed") in db_runs(s3, tmp_path)


def test_a_big_drop_in_postings_raises_and_alerts(s3, monkeypatch, tmp_path):
    stub_transforms(monkeypatch)
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest(fetched=8000))
    lh.handler({}, None, s3=s3)
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest(fetched=2000))
    with pytest.raises(RuntimeError, match="fetched 2000"):
        lh.handler({}, None, s3=s3)


def test_slack_being_down_does_not_hide_the_real_error(s3, monkeypatch):
    monkeypatch.setattr(lh.ingest, "run_source", fake_ingest(fail=("greenhouse",)))
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example/x")

    def broken(url, text, session=None):
        raise RuntimeError("Slack answered 500")
    monkeypatch.setattr(lh.alerts, "send_slack", broken)
    with pytest.raises(RuntimeError, match="latest run failed"):
        lh.handler({}, None, s3=s3)


def test_full_pipeline_with_real_transforms(monkeypatch):
    """Ingest is faked, but dedupe, skills and trends run for real on a small database."""
    from marketlens.ingest.schema import Posting
    con = store.connect(":memory:")

    def run_source(name, con, raw_dir, session=None, **opts):
        started = store.now_iso()
        posts = []
        if name == "greenhouse":
            posts = [Posting(source="greenhouse", source_id=f"a:{i}", title=f"Engineer {i}", company="Acme",
                             location="Remote", description=f"We need Python and SQL for project {i}.",
                             posted_at="2026-11-01", url="u", category="", salary_min=None, salary_max=None,
                             fetched_at=started) for i in range(5)]
        new = store.upsert(con, posts)
        store.log_run(con, name, started, len(posts), new, "ok", "")
        return len(posts), new
    monkeypatch.setattr(lh.ingest, "run_source", run_source)
    out = lh.run_pipeline(con, "unused")
    assert out["dedupe"]["unique"] == 5
    assert out["jobs_with_skill"] == 5
    assert con.execute("SELECT count(*) FROM skill_snapshots").fetchone()[0] > 0
