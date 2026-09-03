"""DAG 구조 검증 — 프로젝트 venv 에는 Airflow 가 없어 skip 되고, 격리 venv 에서만 돈다
(런북 docs/runbook/2026-05-27-airflow-dag-verification.md)."""
import pytest
pytest.importorskip("airflow.models")
from airflow.models import DagBag


def _dag():
    # Airflow 3.3.1 의 DagBag 은 include_examples 인자를 받지 않는다 (스캔 대상이
    # airflow/dags 뿐이라 예제 DAG 은 애초에 안 걸린다).
    bag = DagBag(dag_folder="airflow/dags")
    assert bag.import_errors == {}
    return bag.dags["bullet_in_cycle"]


def test_dag_has_eight_tasks_in_the_spec_order():
    dag = _dag()
    assert set(dag.task_ids) == {"advance", "collect", "enrich", "publish", "gate",
                                 "deploy_site", "judge", "warehouse_load"}
    chain = ["advance", "collect", "enrich", "publish", "gate", "deploy_site", "judge"]
    for up, down in zip(chain, chain[1:]):
        assert up in dag.get_task(down).upstream_task_ids
    assert dag.get_task("warehouse_load").upstream_task_ids == {"publish"}


def test_gate_skips_on_exit_code_3_and_has_no_airflow_retry():
    gate = _dag().get_task("gate")
    assert 3 in (gate.skip_on_exit_code if isinstance(gate.skip_on_exit_code, (list, tuple, set))
                 else [gate.skip_on_exit_code])
    assert gate.retries == 0


def test_collect_has_no_airflow_retry():
    """재시도는 사람이 태스크 클리어로 한다 — 재수집은 소스를 다시 훑는 일이라
    Airflow 자동 재시도로 조용히 두 번 돌면 안 된다 (deploy judge 가 전제하는 값)."""
    assert _dag().get_task("collect").retries == 0


def test_pipeline_tasks_use_all_success_trigger_rule():
    """다섯 태스크가 all_success 여야 앞이 실패했을 때 뒤가 skipped 가 아니라
    upstream_failed 로 뜬다 — deploy judge --from-airflow 가 gate == skipped 를
    급사 판정으로 보고 그 뒤에야 태스크 실패를 순회하므로, 이 트리거 규칙이 깨지면
    실패를 급사로 오판한다."""
    dag = _dag()
    for name in ("collect", "enrich", "publish", "gate", "deploy_site"):
        assert dag.get_task(name).trigger_rule == "all_success"


def test_judge_and_warehouse_load_run_regardless_of_upstream():
    dag = _dag()
    assert dag.get_task("judge").trigger_rule == "all_done"
    assert dag.get_task("warehouse_load").trigger_rule == "all_done"


def test_run_parameters_mirror_the_systemd_timer():
    dag = _dag()
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout.total_seconds() == 1800


def test_every_task_has_the_failure_callback():
    for t in _dag().tasks:
        assert t.on_failure_callback


def test_deploy_site_command_does_not_end_in_sh():
    # `.sh` 로 끝나면 BashOperator 가 bash_command 를 Jinja 템플릿 파일 경로로 읽으려
    # 든다 (template_ext) — 끝에 공백을 하나 남겨 피한다.
    assert _dag().get_task("deploy_site").bash_command.endswith(" ")
