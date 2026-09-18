"""오케스트레이터 생존 감시 (스펙 2026-09-04 §4.4) — 심박과 마지막 성공, 두 축."""
import json
import subprocess
from datetime import datetime, timedelta, timezone

from bullet_in import airflow_watch, notify
from bullet_in.airflow_watch import (airflow_counts, completion, evaluate, gate_signal_deaths,
                                     journal_counts, latest_success_age, should_alert)

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


def test_latest_success_age_skips_leading_structlog_warning_lines():
    warning = (
        '2026-09-04T06:24:26.841666Z [warning  ] Could not import graphviz. '
        'Rendering graph to the graphical format will not be possible. \n'
        '2026-09-04T06:24:26.841666Z [warning  ] Could not import graphviz. '
        'Rendering graph to the graphical format will not be possible. \n'
        '2026-09-04T06:24:26.841666Z [warning  ] Could not import graphviz. '
        'Rendering graph to the graphical format will not be possible. \n'
    )
    runs = [{"dag_id": "bullet_in_cycle", "state": "success", "end_date": "2026-09-06T03:07:02+00:00"}]
    age = latest_success_age(warning + json.dumps(runs), NOW)
    assert round(age, 2) == round((NOW - datetime(2026, 9, 6, 3, 7, 2, tzinfo=timezone.utc)).total_seconds() / 3600, 2)


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
        ("jobs", "check", "--job-type", "SchedulerJob"),
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


# ── 완주율 (스펙 2026-09-18 completion-rate-tile §1 · §2) ─────────────────────

JOURNAL = """2026-07-20T09:01:44+09:00 host systemd[1]: Starting bullet-in.service - bullet-in pipeline cycle...
2026-07-20T09:05:01+09:00 host systemd[1]: Finished bullet-in.service - bullet-in pipeline cycle.
2026-07-20T12:01:44+09:00 host systemd[1]: Starting bullet-in.service - bullet-in pipeline cycle...
2026-07-20T12:04:00+09:00 host systemd[1]: bullet-in.service: Failed with result 'exit-code'.
2026-07-20T15:01:44+09:00 host systemd[1]: Starting bullet-in.service - bullet-in pipeline cycle...
2026-07-20T15:05:01+09:00 host systemd[1]: Finished bullet-in.service - bullet-in pipeline cycle.
"""
RUNS = [
    {"run_id": "scheduled__2026-09-04T09:00:00+00:00", "state": "success",
     "start_date": "2026-09-04T09:00:01+00:00", "end_date": "2026-09-04T09:04:00+00:00"},
    {"run_id": "manual__2026-09-04T12:00:00+00:00", "state": "success",
     "start_date": "2026-09-04T12:00:01+00:00", "end_date": "2026-09-04T12:05:00+00:00"},
    {"run_id": "scheduled__2026-09-04T15:00:00+00:00", "state": "failed",
     "start_date": "2026-09-04T15:00:01+00:00", "end_date": "2026-09-04T15:02:00+00:00"},
    {"run_id": "scheduled__2026-09-04T18:00:00+00:00", "state": "running",
     "start_date": "2026-09-04T18:00:01+00:00", "end_date": None},
]


def test_journal_counts_reads_starting_finished_and_failed_lines():
    assert journal_counts(JOURNAL) == {"started": 3, "finished": 2, "failed": 1}


def test_airflow_counts_excludes_in_progress_and_counts_manual_and_failed():
    assert airflow_counts(json.dumps(RUNS)) == {
        "started": 3, "success": 2, "failed": 1, "in_progress": 1,
        "first_start": "2026-09-04T09:00:01+00:00", "last_end": "2026-09-04T15:02:00+00:00"}


def test_airflow_counts_skips_leading_structlog_warning_lines():
    text = "2026-09-18 [warning] structlog says hi\n" + json.dumps(RUNS[:1])
    assert airflow_counts(text)["success"] == 1


def test_airflow_counts_of_an_empty_list():
    assert airflow_counts("[]") == {"started": 0, "success": 0, "failed": 0, "in_progress": 0,
                                    "first_start": None, "last_end": None}


def test_completion_adds_journal_and_airflow():
    journal = {"started": 358, "finished": 354, "failed": 4}
    airflow = {"started": 118, "success": 118, "failed": 0, "in_progress": 0}
    assert completion(journal, airflow) == (472, 476)          # 354 + 118 · 358 + 118


def _healthy_cli(*args):
    if args[0] == "jobs":
        return _cp(0)
    recent = dict(RUNS[0], end_date=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
    return _cp(0, stdout=json.dumps([recent, *RUNS[1:]]))


def test_main_writes_the_completion_file(monkeypatch, tmp_path):
    monkeypatch.setattr(airflow_watch, "_cli", _healthy_cli)
    monkeypatch.setattr(airflow_watch, "_journal", lambda: _cp(0, stdout=JOURNAL))
    monkeypatch.setattr(notify, "send_alert", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)

    assert airflow_watch.main() == 0

    data = json.loads((tmp_path / "state" / "completion.json").read_text())
    assert data["journal"] == {"started": 3, "finished": 2, "failed": 1}
    assert data["airflow"]["success"] == 2 and data["airflow"]["in_progress"] == 1
    assert data["computed_at"]


def test_main_keeps_the_previous_journal_block_when_journalctl_fails(monkeypatch, tmp_path, caplog):
    state = tmp_path / "state"; state.mkdir()
    (state / "completion.json").write_text(json.dumps(
        {"computed_at": "old", "journal": {"started": 358, "finished": 354, "failed": 4}, "airflow": {}}))
    monkeypatch.setattr(airflow_watch, "_cli", _healthy_cli)
    monkeypatch.setattr(airflow_watch, "_journal", lambda: _cp(1, stderr="no journal"))
    monkeypatch.setattr(notify, "send_alert", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)

    with caplog.at_level("WARNING"):
        assert airflow_watch.main() == 0

    data = json.loads((state / "completion.json").read_text())
    assert data["journal"] == {"started": 358, "finished": 354, "failed": 4}
    assert data["airflow"]["success"] == 2 and data["computed_at"] != "old"
    assert any("journalctl" in r.getMessage() for r in caplog.records if r.levelname == "WARNING")


def test_main_leaves_the_completion_file_alone_when_list_runs_fails(monkeypatch, tmp_path):
    state = tmp_path / "state"; state.mkdir()
    before = json.dumps({"computed_at": "old", "journal": {"started": 1, "finished": 1, "failed": 0}, "airflow": {}})
    (state / "completion.json").write_text(before)
    monkeypatch.setattr(airflow_watch, "_cli", lambda *a: _cp(0) if a[0] == "jobs" else _cp(2, stderr="boom"))
    monkeypatch.setattr(airflow_watch, "_journal", lambda: _cp(0, stdout=JOURNAL))
    monkeypatch.setattr(notify, "send_alert", lambda *a, **k: None)
    monkeypatch.chdir(tmp_path)

    assert airflow_watch.main() == 0
    assert (state / "completion.json").read_text() == before


# ── 게이트 급사 계수기 (안건 2ν · 트러블슈팅 2026-09-18 재시도가 가린 코어 덤프) ────────

DEATH_LINE = ('{"timestamp":"2026-09-17T09:01:50.385438Z","level":"info",'
              '"event":"WARNING dbt 가 신호로 죽었다 (종료코드 -11 · 시도 1/2)","task_id":"gate",'
              '"run_id":"scheduled__2026-09-17T09:00:00+00:00"}\n')


def _gate_logs(root, runs):
    """runs = {run_id: [attempt 텍스트, ...]} 로 Airflow 로그 트리를 흉내 낸다."""
    for rid, attempts in runs.items():
        d = root / "dag_id=bullet_in_cycle" / f"run_id={rid}" / "task_id=gate"
        d.mkdir(parents=True)
        for i, text in enumerate(attempts, 1):
            (d / f"attempt={i}.log").write_text(text)
    return root


def test_gate_signal_deaths_counts_runs_whose_gate_log_has_the_warning(tmp_path):
    root = _gate_logs(tmp_path, {
        "scheduled__2026-09-16T09:00:00+00:00": ['{"event":"dbt 게이트 통과"}\n'],
        "scheduled__2026-09-17T09:00:00+00:00": [DEATH_LINE + '{"event":"dbt 게이트 통과"}\n'],
        "scheduled__2026-09-17T12:00:00+00:00": ['{"event":"dbt 게이트 통과"}\n', DEATH_LINE],   # 시도 둘 · 한 실행
    })
    assert gate_signal_deaths(root) == {
        "gate_runs": 3, "signal_deaths": 2,
        "last_at": "2026-09-17T09:01:50.385438Z", "last_run_id": "scheduled__2026-09-17T12:00:00+00:00"}


def test_gate_signal_deaths_of_a_missing_log_root(tmp_path):
    assert gate_signal_deaths(tmp_path / "nowhere") == {
        "gate_runs": 0, "signal_deaths": 0, "last_at": None, "last_run_id": None}


def test_main_notifies_the_review_channel_when_a_signal_death_is_new(monkeypatch, tmp_path):
    state = tmp_path / "state"; state.mkdir()
    (state / "completion.json").write_text(json.dumps(
        {"computed_at": "old", "journal": {}, "airflow": {}, "gate": {"gate_runs": 2, "signal_deaths": 1}}))
    root = _gate_logs(tmp_path / "logs", {
        "r1": [DEATH_LINE], "r2": [DEATH_LINE], "r3": ['{"event":"ok"}\n']})
    monkeypatch.setattr(airflow_watch, "_cli", _healthy_cli)
    monkeypatch.setattr(airflow_watch, "_journal", lambda: _cp(0, stdout=JOURNAL))
    monkeypatch.setattr(airflow_watch, "AIRFLOW_LOG_ROOT", root)
    sent = []
    monkeypatch.setattr(notify, "send_alert",
                        lambda title, description, **kw: sent.append({"title": title, "description": description, **kw}))
    monkeypatch.chdir(tmp_path)

    assert airflow_watch.main() == 0

    data = json.loads((state / "completion.json").read_text())
    assert data["gate"]["signal_deaths"] == 2 and data["gate"]["gate_runs"] == 3
    assert len(sent) == 1 and sent[0]["channel"] == notify.CHANNEL_REVIEW
    assert "2번째" in sent[0]["title"] and "coredumpctl" in sent[0]["description"]


def test_main_stays_quiet_when_the_signal_death_count_is_unchanged(monkeypatch, tmp_path):
    state = tmp_path / "state"; state.mkdir()
    (state / "completion.json").write_text(json.dumps(
        {"computed_at": "old", "journal": {}, "airflow": {}, "gate": {"gate_runs": 1, "signal_deaths": 1}}))
    root = _gate_logs(tmp_path / "logs", {"r1": [DEATH_LINE], "r2": ['{"event":"ok"}\n']})
    monkeypatch.setattr(airflow_watch, "_cli", _healthy_cli)
    monkeypatch.setattr(airflow_watch, "_journal", lambda: _cp(0, stdout=JOURNAL))
    monkeypatch.setattr(airflow_watch, "AIRFLOW_LOG_ROOT", root)
    sent = []
    monkeypatch.setattr(notify, "send_alert", lambda *a, **k: sent.append(1))
    monkeypatch.chdir(tmp_path)

    assert airflow_watch.main() == 0
    assert sent == []
