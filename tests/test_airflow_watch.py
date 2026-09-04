"""오케스트레이터 생존 감시 (스펙 2026-09-04 §4.4) — 심박과 마지막 성공, 두 축."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

from bullet_in import airflow_watch, notify
from bullet_in.airflow_watch import evaluate, latest_success_age, should_alert

NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)


def _cp(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


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


def test_main_calls_the_positional_dag_id_and_stays_quiet_when_healthy(monkeypatch, tmp_path):
    # 최종 리뷰 Fix 2 — `-d` 플래그가 3.3.1 에 없어 dag_id 는 위치 인자여야 한다.
    calls = []

    def fake_cli(*args):
        calls.append(args)
        if args[0] == "jobs":
            return _cp(0)
        one_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        runs = [{"dag_id": "bullet_in_cycle", "state": "success", "end_date": one_hour_ago}]
        return _cp(0, stdout=json.dumps(runs))

    monkeypatch.setattr(airflow_watch, "_cli", fake_cli)
    sent = []
    monkeypatch.setattr(notify, "send_alert",
                        lambda title, description, **kw: sent.append({"title": title, "description": description, **kw}))
    monkeypatch.chdir(tmp_path)

    assert airflow_watch.main() == 0
    assert calls == [
        ("jobs", "check", "--job-type", "SchedulerJob", "--allow-multiple"),
        ("dags", "list-runs", "bullet_in_cycle", "-o", "json"),
    ]
    assert sent == []


def test_main_alerts_and_logs_a_warning_when_list_runs_fails(monkeypatch, tmp_path, caplog):
    def fake_cli(*args):
        if args[0] == "jobs":
            return _cp(0)
        return _cp(2, stderr="boom")

    monkeypatch.setattr(airflow_watch, "_cli", fake_cli)
    sent = []
    monkeypatch.setattr(notify, "send_alert",
                        lambda title, description, **kw: sent.append({"title": title, "description": description, **kw}))
    monkeypatch.chdir(tmp_path)

    with caplog.at_level("WARNING"):
        assert airflow_watch.main() == 0

    assert sent and "성공 실행이 없다" in sent[0]["description"]
    assert any(r.levelname == "WARNING" for r in caplog.records)
