from __future__ import annotations
import pendulum
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from bullet_in import notify

def _run():
    import asyncio
    from bullet_in.run import main
    asyncio.run(main(concurrency=8))

def _notify_failure(context) -> None:
    notify.send_alert(**notify.build_failure_alert(context))

with DAG(
    dag_id="bullet_in_daily",
    # 운영 스케줄러는 VM systemd timer 이고 이 DAG 는 확장용 보존 자산이다 (spec 2026-07-20 §2.2).
    # 되살릴 때 바로 맞도록 실제 운영 주기와 같은 값을 둔다 — 하루 8회(3시간마다) · 신규만 멱등 누적.
    schedule="0 */3 * * *",
    start_date=pendulum.datetime(2026, 5, 1, tz="UTC"),
    catchup=False,
    tags=["bullet-in"],
) as dag:
    PythonOperator(task_id="run_pipeline", python_callable=_run,
                   on_failure_callback=_notify_failure)
