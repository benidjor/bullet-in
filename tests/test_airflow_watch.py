"""오케스트레이터 생존 감시 (스펙 2026-09-04 §4.4) — 심박과 마지막 성공, 두 축."""
import json
from datetime import datetime, timedelta, timezone

from bullet_in.airflow_watch import evaluate, latest_success_age, should_alert

NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)


def test_evaluate_is_quiet_when_both_axes_are_fine():
    assert evaluate(True, 2.5) == []


def test_evaluate_names_each_broken_axis():
    p = evaluate(False, 7.0)
    assert any("심박" in x for x in p) and any("7.0" in x for x in p)
    assert evaluate(True, None) == ["bullet_in_cycle 의 성공 실행이 없다"]
    assert evaluate(True, 3.9) == []


def test_latest_success_age_reads_the_cli_list_and_picks_the_newest():
    runs = [{"dag_id": "bullet_in_cycle", "state": "success", "end_date": "2026-09-06T00:07:21+00:00"},
            {"dag_id": "bullet_in_cycle", "state": "success", "end_date": "2026-09-06T03:07:02+00:00"},
            {"dag_id": "bullet_in_cycle", "state": "failed", "end_date": "2026-09-06T05:50:00+00:00"}]
    age = latest_success_age(json.dumps(runs), NOW)
    assert round(age, 2) == round((NOW - datetime(2026, 9, 6, 3, 7, 2, tzinfo=timezone.utc)).total_seconds() / 3600, 2)
    assert latest_success_age("[]", NOW) is None


def test_should_alert_sends_once_then_waits_four_hours():
    ok, st = should_alert(["x"], {}, NOW)
    assert ok and st["last_alert_at"] == NOW.isoformat()
    ok2, st2 = should_alert(["x"], st, NOW + timedelta(hours=1))
    assert not ok2 and st2 == st
    ok3, _ = should_alert(["x"], st, NOW + timedelta(hours=4, minutes=1))
    assert ok3


def test_should_alert_resets_when_healthy():
    _, st = should_alert(["x"], {}, NOW)
    ok, st2 = should_alert([], st, NOW + timedelta(hours=1))
    assert not ok and st2 == {}
