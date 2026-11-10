from datetime import datetime, timezone

import pytest

from marketlens import alerts, store

NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)


def con_with(runs):
    con = store.connect(":memory:")
    for source, started, fetched, status, error in runs:
        store.log_run(con, source, started, fetched, 0, status, error)
    return con


def test_healthy():
    con = con_with([("greenhouse", "2026-11-09T12:00:00Z", 8000, "ok", ""),
                    ("greenhouse", "2026-11-10T08:00:00Z", 8100, "ok", "")])
    assert alerts.check_health(con, now=NOW) == []


def test_no_runs_at_all():
    assert "no run has ever been recorded" in alerts.check_health(store.connect(":memory:"), now=NOW)[0]


def test_latest_run_failed():
    con = con_with([("greenhouse", "2026-11-10T06:00:00Z", 8000, "ok", ""),
                    ("greenhouse", "2026-11-10T09:00:00Z", 0, "failed", "HTTP 500")])
    problems = alerts.check_health(con, now=NOW)
    assert any("latest run failed" in p and "HTTP 500" in p for p in problems)


def test_a_failure_that_was_later_fixed_is_not_reported():
    con = con_with([("greenhouse", "2026-11-10T06:00:00Z", 0, "failed", "HTTP 500"),
                    ("greenhouse", "2026-11-10T09:00:00Z", 8000, "ok", "")])
    assert alerts.check_health(con, now=NOW) == []


def test_row_count_collapse():
    con = con_with([("greenhouse", "2026-11-09T06:00:00Z", 8000, "ok", ""),
                    ("greenhouse", "2026-11-10T09:00:00Z", 3000, "ok", "")])
    assert any("fetched 3000" in p for p in alerts.check_health(con, now=NOW))


def test_small_drop_is_fine():
    con = con_with([("greenhouse", "2026-11-09T06:00:00Z", 8000, "ok", ""),
                    ("greenhouse", "2026-11-10T09:00:00Z", 6000, "ok", "")])
    assert alerts.check_health(con, now=NOW) == []


def test_stale_data():
    con = con_with([("greenhouse", "2026-11-07T06:00:00Z", 8000, "ok", "")])
    assert any("hours ago" in p for p in alerts.check_health(con, now=NOW))


def test_many_skipped_boards():
    note = "skipped: " + ", ".join(f"b{i} (HTTP 404)" for i in range(8))
    con = con_with([("greenhouse", "2026-11-10T09:00:00Z", 8000, "ok", note)])
    assert any("8 company boards were skipped" in p for p in alerts.check_health(con, now=NOW))


def test_few_skipped_boards_are_fine():
    con = con_with([("greenhouse", "2026-11-10T09:00:00Z", 8000, "ok", "skipped: b1 (HTTP 404)")])
    assert alerts.check_health(con, now=NOW) == []


def test_optional_source_failure_is_still_reported_but_missing_is_not():
    con = con_with([("greenhouse", "2026-11-10T09:00:00Z", 8000, "ok", ""),
                    ("remotive", "2026-11-10T09:00:00Z", 0, "failed", "timeout")])
    problems = alerts.check_health(con, now=NOW)
    assert len(problems) == 1 and problems[0].startswith("remotive")


class FakeSession:
    def __init__(self, status=200):
        self.status, self.sent = status, []

    def post(self, url, json, timeout):
        self.sent.append((url, json))
        return type("R", (), {"status_code": self.status, "text": "nope"})()


def test_send_slack_posts_text():
    s = FakeSession()
    alerts.send_slack("https://hooks.example/x", "hello", session=s)
    assert s.sent == [("https://hooks.example/x", {"text": "hello"})]


def test_send_slack_raises_when_slack_refuses():
    with pytest.raises(RuntimeError, match="403"):
        alerts.send_slack("https://hooks.example/x", "hello", session=FakeSession(403))


def test_message_lists_each_problem():
    msg = alerts.format_message(["a is broken", "b is broken"])
    assert "- a is broken" in msg and "- b is broken" in msg
