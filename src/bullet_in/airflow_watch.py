"""오케스트레이터 생존 감시 — 매시 두 축을 잰다 (스펙 2026-09-04 §4.4).

스케줄러가 살아 있어도 DAG 가 일시정지됐거나 파싱이 깨지면 회차가 조용히 안 돈다.
심박만 보면 그 경우를 못 잡고, 마지막 성공만 보면 원인이 안 갈린다 — 그래서 둘 다.
systemd 의 OnFailure 가 덮던 「유닛 자체가 죽은 경우」 를 이 타이머가 잇는다.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bullet_in import notify

log = logging.getLogger(__name__)

AIRFLOW_BIN = os.environ.get("AIRFLOW_BIN", "/home/ubuntu/airflow-venv/bin/airflow")
DAG_ID = "bullet_in_cycle"
STATE_PATH = Path("state/airflow_watch.json")


def evaluate(heartbeat_ok: bool, last_success_age_hours: float | None, *,
             threshold_hours: float = 4.0) -> list[str]:
    problems = []
    if not heartbeat_ok:
        problems.append("스케줄러 심박 없음 (airflow jobs check 실패)")
    if last_success_age_hours is None:
        problems.append(f"{DAG_ID} 의 성공 실행이 없다")
    elif last_success_age_hours > threshold_hours:
        problems.append(f"{DAG_ID} 의 마지막 성공이 {last_success_age_hours:.1f}시간 전 (문턱 {threshold_hours:g}시간)")
    return problems


def latest_success_age(list_runs_json: str, now: datetime) -> float | None:
    """`airflow dags list-runs -d bullet_in_cycle -o json` 의 목록에서 최신 성공까지의 시간."""
    ends = []
    for r in json.loads(list_runs_json or "[]"):
        if r.get("state") == "success" and r.get("end_date"):
            ends.append(datetime.fromisoformat(str(r["end_date"]).replace("Z", "+00:00")))
    if not ends:
        return None
    return (now - max(ends)).total_seconds() / 3600


def should_alert(problems: list[str], state: dict, now: datetime, *,
                 every_hours: float = 4.0) -> tuple[bool, dict]:
    """같은 상태가 이어지는 동안 every_hours 마다 한 번만 (신선도 재알림 규칙과 같은 방식)."""
    if not problems:
        return False, {}
    last = state.get("last_alert_at")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < every_hours * 3600:
        return False, state
    return True, {"last_alert_at": now.isoformat()}


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([AIRFLOW_BIN, *args], capture_output=True, text=True, timeout=120)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    hb = _cli("jobs", "check", "--job-type", "SchedulerJob", "--allow-multiple")
    runs = _cli("dags", "list-runs", "-d", DAG_ID, "-o", "json")
    age = latest_success_age(runs.stdout, now) if runs.returncode == 0 else None
    problems = evaluate(hb.returncode == 0, age)
    state = {}
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        pass
    send, new_state = should_alert(problems, state, now)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(new_state))
    if send:
        notify.send_alert("🚨 Airflow 가 회차를 안 돌리고 있다",
                          "\n".join(f"- {p}" for p in problems) + "\n"
                          "`systemctl status airflow-scheduler airflow-dag-processor` · "
                          "`airflow dags state bullet_in_cycle` · 되돌리려면 런북 (Airflow 아래에서 회차 돌리기) §5",
                          color=notify.COLOR_FAILURE, channel=notify.CHANNEL_INCIDENT)
    log.info("airflow watch — 심박 %s · 마지막 성공 %s시간 전 · 문제 %d · 발송 %s",
             "OK" if hb.returncode == 0 else "없음", f"{age:.1f}" if age is not None else "?",
             len(problems), send)
    return 0


if __name__ == "__main__":
    sys.exit(main())
