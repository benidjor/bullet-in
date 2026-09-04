"""Airflow 태스크 실패 알림 — DAG 는 프로젝트를 import 하지 않으므로 JSON 으로 건넨다."""
import io
import json

from bullet_in import notify


def _payload(**over):
    p = {"dag_id": "bullet_in_cycle", "task_id": "enrich", "run_id": "scheduled__2026-09-05T00:00:00+00:00",
         "try_number": 1, "duration": 83.2, "hostname": "seoulnow-receiver",
         "log_url": "http://127.0.0.1:8080/dags/bullet_in_cycle/runs/x/tasks/enrich",
         "exception": "RuntimeError: 429"}
    p.update(over)
    return p


def test_task_failure_alert_names_the_task_and_carries_six_fields():
    a = notify.build_task_failure_alert(_payload())
    assert a["title"] == "❌ 파이프라인 실패 — enrich"
    assert a["channel"] == notify.CHANNEL_INCIDENT
    names = [f["name"] for f in a["fields"]]
    assert names == ["DAG / Task", "Run", "Try", "Duration", "Host", "로그"]
    assert "RuntimeError: 429" in a["description"]


def test_task_failure_alert_tolerates_missing_duration_and_log():
    a = notify.build_task_failure_alert(_payload(duration=None, log_url=None, exception=None))
    values = {f["name"]: f["value"] for f in a["fields"]}
    assert values["Duration"] == "-" and values["로그"] == "-"


def test_cli_task_failure_reads_stdin_and_sends(monkeypatch):
    sent = []
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: sent.append(kw))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(task_id="gate"))))
    assert notify.main(["task-failure"]) == 0
    assert sent and sent[0]["title"].endswith("gate")
