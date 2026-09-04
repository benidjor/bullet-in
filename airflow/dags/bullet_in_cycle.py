"""bullet-in 회차 DAG — 태스크 여덟 · 전부 셸 호출 (스펙 2026-09-04 §4.3).

이 파일은 Airflow venv 에서 파싱되므로 bullet_in 을 import 하지 않는다.
단계는 프로젝트 venv 의 `uv run python -m bullet_in.run --stage …` 로 돌고,
전진 · 판정 · 롤백 (스펙 2026-09-03) 은 첫 · 끝 태스크가 같은 명령을 부른다.
"""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO = "/home/ubuntu/bullet-in"
UV = "/home/ubuntu/.local/bin/uv"
AIRFLOW_BIN = "/home/ubuntu/airflow-venv/bin/airflow"
AIRFLOW_ENV = "/home/ubuntu/airflow/airflow.env"
# 프로젝트의 .env 는 Airflow 프로세스가 아니라 태스크 셸이 읽는다 (스펙 §4.2).
PRELUDE = f"cd {REPO} && set -a && . ./.env && set +a && "
# 변경 이력 적재만 전용 서비스 계정 — 유닛 주석과 같은 사정 (bullet-in-warehouse.service).
LAKEHOUSE_KEY = "/home/ubuntu/.bullet-in-lakehouse.json"


def _stage(name: str) -> str:
    return f"{PRELUDE}{UV} run python -m bullet_in.run --stage {name} --run-id '{{{{ run_id }}}}'"


def _send_failure(payload: dict) -> None:
    subprocess.run(["bash", "-c", f"{PRELUDE}{UV} run python -m bullet_in.notify task-failure"],
                   input=json.dumps(payload, default=str), text=True, timeout=60, check=False)


def _task_failure(context) -> None:
    """실패 콜백 — 컨텍스트에서 값 여덟을 뽑아 프로젝트의 알림 CLI 에 JSON 으로 건넨다."""
    ti = context["task_instance"]
    payload = {
        "dag_id": ti.dag_id, "task_id": ti.task_id, "run_id": context.get("run_id"),
        "try_number": ti.try_number, "duration": getattr(ti, "duration", None),
        "hostname": getattr(ti, "hostname", None), "log_url": getattr(ti, "log_url", None),
        "exception": str(context.get("exception") or "")[:400] or None,
    }
    _send_failure(payload)


def _dag_failure(context) -> None:
    """DAG 레벨 실패 콜백 — `dagrun_timeout` 만료는 스케줄러가 실행을 실패로,
    안 끝난 태스크를 SKIPPED 로 바꿀 뿐이라 태스크 콜백이 하나도 안 불린다.
    이 콜백이 없으면 judge 가 안 도는 회차가 조용히 사라진다."""
    dag = context.get("dag")
    payload = {
        "dag_id": getattr(dag, "dag_id", None), "task_id": "dag_run", "run_id": context.get("run_id"),
        "try_number": None, "duration": None, "hostname": None, "log_url": None,
        "exception": (f"DAG 실행 실패 — {context.get('reason') or '?'} · "
                     f"시간 초과면 judge 가 안 돌아 판정이 없다 · 다음 회차가 잇는다")[:400],
    }
    _send_failure(payload)


with DAG(
    dag_id="bullet_in_cycle",
    schedule="0 */3 * * *",                       # bullet-in.timer 와 같은 값 (UTC)
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,                                # 밀린 회차 보정 = 최근 구간 한 번 (Persistent=true 대응)
    max_active_runs=1,                            # 이중 실행 금지
    dagrun_timeout=timedelta(minutes=30),         # TimeoutStartSec=1800 대응
    default_args={"on_failure_callback": _task_failure, "retries": 0},
    # 시간 초과는 태스크를 건너뜀으로 바꿔 태스크 콜백이 안 불린다 — DAG 레벨 콜백으로 잇는다.
    on_failure_callback=_dag_failure,
    tags=["bullet-in"],
) as dag:
    # 전진 실패로 회차를 잃지 않는다 — ExecStartPre=- 와 같은 뜻으로 종료 코드를 0 으로 만든다.
    advance = BashOperator(task_id="advance",
                           bash_command=f"{PRELUDE}{UV} run python -m bullet_in.deploy advance || true")
    collect = BashOperator(task_id="collect", bash_command=_stage("collect"))
    enrich = BashOperator(task_id="enrich", bash_command=_stage("enrich"))
    publish = BashOperator(task_id="publish", bash_command=_stage("publish"), retries=1)
    # 급사 (종료 코드 3) 는 실패가 아니라 건너뜀 — 뒤의 deploy_site 가 기본 규칙으로 함께 건너뛰고
    # judge 가 「보류」 를 낸다. 급사 재시도는 게이트 안에서 이미 한 번 했다 (dbt_gate.run_gate).
    gate = BashOperator(task_id="gate", bash_command=_stage("gate"), skip_on_exit_code=3)
    # 끝 공백 — `.sh` 로 끝나면 BashOperator 가 Jinja 템플릿 파일로 읽으려 든다
    deploy_site = BashOperator(task_id="deploy_site",
                               bash_command=f"{PRELUDE}infra/deploy-site.sh ", retries=1)
    # 앞이 어떻게 끝났든 돈다 (ExecStopPost 대응) — 상태를 CLI 로 받아 판정기에 넘긴다.
    # 태스크 프로세스는 Task SDK 가 DB 접근을 막아 두므로 (`airflow-db-not-allowed:///` 로
    # 덮어쓴다) CLI 를 부르기 전에 airflow.env 를 다시 읽어 접속 문자열을 되살린다.
    judge = BashOperator(
        task_id="judge", trigger_rule="all_done",
        bash_command=(f"{PRELUDE}mkdir -p state && "
                      f"set -a && . {AIRFLOW_ENV} && set +a && "
                      f"{AIRFLOW_BIN} tasks states-for-dag-run bullet_in_cycle '{{{{ run_id }}}}' -o json "
                      f"> state/airflow_states.json && "
                      f"{UV} run python -m bullet_in.deploy judge --from-airflow state/airflow_states.json"))
    # 「회차 20분 뒤」 시계 어긋내기 대신 의존 — 회차 결과와 무관하게 돈다 (타이머와 같은 성질).
    warehouse_load = BashOperator(
        task_id="warehouse_load", trigger_rule="all_done",
        bash_command=(f"{PRELUDE}env GOOGLE_APPLICATION_CREDENTIALS={LAKEHOUSE_KEY} "
                      f"{UV} run python -m bullet_in.warehouse load"))

    advance >> collect >> enrich >> publish >> gate >> deploy_site >> judge
    publish >> warehouse_load
