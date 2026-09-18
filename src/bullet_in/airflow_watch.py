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
from bullet_in.deploy import cli_json

log = logging.getLogger(__name__)

AIRFLOW_BIN = os.environ.get("AIRFLOW_BIN", "/home/ubuntu/airflow-venv/bin/airflow")
DAG_ID = "bullet_in_cycle"
STATE_PATH = Path("state/airflow_watch.json")
COMPLETION_PATH = Path("state/completion.json")
UNIT = "bullet-in.service"
AIRFLOW_LOG_ROOT = Path(os.environ.get("AIRFLOW_HOME", "/home/ubuntu/airflow")) / "logs"
SIGNAL_DEATH_MARK = "신호로 죽었다"          # dbt_gate.run_gate 의 경고 문구


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
    """`airflow dags list-runs bullet_in_cycle -o json` 의 목록에서 최신 성공까지의 시간."""
    ends = []
    for r in cli_json(list_runs_json or "[]"):
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


# ── 완주율 (스펙 2026-09-18 completion-rate-tile) ──────────────────────────────
# 「파이프라인이 끝까지 갔는가」 는 파이프라인 밖의 기록에만 남는다 — systemd 시절은 저널,
# Airflow 시절은 실행 목록. 이 타이머는 둘 다 읽을 수 있는 자리라 여기서 세어 파일로 떨어뜨리고,
# publish 태스크는 파일만 읽는다 (태스크 셸은 메타 DB 접근이 막혀 있다).

def journal_counts(text: str) -> dict:
    """`journalctl -u bullet-in.service` 출력에서 시작 · 완주 · 실패 줄 수 (2026-07-20 부터 09-04 까지 · 그 뒤 상수)."""
    return {"started": text.count(f"Starting {UNIT}"),
            "finished": text.count(f"Finished {UNIT}"),
            "failed": text.count("Failed with result")}


def airflow_counts(list_runs_json: str) -> dict:
    """`dags list-runs -o json` 목록에서 완주 · 실패 · 진행 중. 시작 = 완주 + 실패 (진행 중은 아직 답이 없다)."""
    runs = cli_json(list_runs_json or "[]")
    success = sum(1 for r in runs if r.get("state") == "success")
    failed = sum(1 for r in runs if r.get("state") == "failed")
    in_progress = sum(1 for r in runs if r.get("state") in ("running", "queued"))
    starts = sorted(str(r["start_date"]) for r in runs if r.get("start_date"))
    ends = sorted(str(r["end_date"]) for r in runs if r.get("end_date"))
    return {"started": success + failed, "success": success, "failed": failed, "in_progress": in_progress,
            "first_start": starts[0] if starts else None, "last_end": ends[-1] if ends else None}


def completion(journal: dict, airflow: dict) -> tuple[int, int]:
    """(완주, 시작) — 저널과 Airflow 를 합친 셈 (트러블슈팅 2026-09-11 §2)."""
    return (journal.get("finished", 0) + airflow.get("success", 0),
            journal.get("started", 0) + airflow.get("started", 0))


def gate_signal_deaths(log_root: Path) -> dict:
    """gate 태스크 로그에서 「신호로 죽었다」 가 있는 실행 수 (안건 2ν · 재시도가 성공으로 바꾼 급사).

    분모는 gate 태스크 디렉터리 수 (실행 수) 다 — 시도가 둘이어도 실행은 하나로 센다.
    """
    runs = sorted(log_root.glob(f"dag_id={DAG_ID}/run_id=*/task_id=gate"))
    deaths, last_at, last_run = 0, None, None
    for d in runs:
        hit = None
        for f in sorted(d.glob("attempt=*.log")):
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if SIGNAL_DEATH_MARK in line:
                    try:
                        hit = json.loads(line).get("timestamp") or hit
                    except ValueError:
                        hit = hit or ""
        if hit is not None:
            deaths += 1
            last_run = d.parent.name.removeprefix("run_id=")
            if hit and (last_at is None or hit > last_at):
                last_at = hit
    return {"gate_runs": len(runs), "signal_deaths": deaths, "last_at": last_at, "last_run_id": last_run}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _journal() -> subprocess.CompletedProcess:
    # journalctl 이 없는 기계 (맥 · CI) 나 시간 초과는 rc ≠ 0 로 돌려 write_completion 이 경고를 남기게 한다.
    cmd = ["journalctl", "-u", UNIT, "--no-pager", "-q", "-o", "short-iso"]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args=cmd, returncode=127, stdout="", stderr=str(e))


def write_completion(list_runs_json: str, journal: subprocess.CompletedProcess, now: datetime,
                     path: Path = COMPLETION_PATH, log_root: Path | None = None) -> dict:
    """저널이 안 읽히면 직전 파일의 저널 블록을 쓴다 — 09-04 이후 그 값은 상수라 낡지 않는다."""
    previous = _read_json(path)
    if journal.returncode == 0:
        counts = journal_counts(journal.stdout)
    else:
        counts = previous.get("journal") or {"started": 0, "finished": 0, "failed": 0}
        log.warning("journalctl 실패 (rc=%d) — 이전 저널 값을 쓴다: %s", journal.returncode, journal.stderr[:300])
    data = {"computed_at": now.isoformat(), "journal": counts, "airflow": airflow_counts(list_runs_json),
            "gate": gate_signal_deaths(log_root if log_root is not None else AIRFLOW_LOG_ROOT)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def _cli(*args: str) -> subprocess.CompletedProcess:
    # structlog 경고가 stdout 에 섞이지 않도록 안전장치를 하나 더 둔다 (파서도 앞줄을 건너뛴다).
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    return subprocess.run([AIRFLOW_BIN, *args], capture_output=True, text=True, timeout=120, env=env)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    hb = _cli("jobs", "check", "--job-type", "SchedulerJob")
    if hb.returncode != 0:
        log.warning("%s 실패 (rc=%d) — %s", "jobs check", hb.returncode, hb.stderr[:300])
    runs = _cli("dags", "list-runs", DAG_ID, "-o", "json")
    if runs.returncode != 0:
        log.warning("%s 실패 (rc=%d) — %s", "dags list-runs", runs.returncode, runs.stderr[:300])
    age = latest_success_age(runs.stdout, now) if runs.returncode == 0 else None
    if runs.returncode == 0:
        before = (_read_json(COMPLETION_PATH).get("gate") or {}).get("signal_deaths", 0)
        gate = write_completion(runs.stdout, _journal(), now)["gate"]
        if gate["signal_deaths"] > before:
            # 재시도가 성공으로 바꾼 급사는 실패로 안 드러난다 — 흡수 장치에는 계수기를 붙인다 (트러블슈팅 2026-09-18).
            notify.send_alert(f"⚠️ dbt 게이트가 신호로 죽고 재시도로 지나갔다 ({gate['signal_deaths']}번째)",
                              f"- 실행 `{gate['last_run_id']}` · {gate['last_at']}\n"
                              f"- 09-04 이후 게이트 {gate['gate_runs']}회 중 {gate['signal_deaths']}회 · 배포는 정상\n"
                              "- `coredumpctl info -1` 로 덤프를 본다 · 안건 2ν (`mysql_scanner` 확장)",
                              color=notify.COLOR_ANOMALY, channel=notify.CHANNEL_REVIEW)
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
                          "`systemctl status airflow-scheduler airflow-dag-processor airflow-api-server` · "
                          "`airflow dags state bullet_in_cycle` · 되돌리려면 런북 (Airflow 아래에서 회차 돌리기) §5",
                          color=notify.COLOR_FAILURE, channel=notify.CHANNEL_INCIDENT)
    log.info("airflow watch — 심박 %s · 마지막 성공 %s시간 전 · 문제 %d · 발송 %s",
             "OK" if hb.returncode == 0 else "없음", f"{age:.1f}" if age is not None else "?",
             len(problems), send)
    return 0


if __name__ == "__main__":
    sys.exit(main())
