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
    schedule="0 */6 * * *",  # 하루 4회(6시간마다): 무료티어 15RPM 안에서 신규만 멱등 누적
    start_date=pendulum.datetime(2026, 5, 1, tz="UTC"),
    catchup=False,
    tags=["bullet-in"],
) as dag:
    PythonOperator(task_id="run_pipeline", python_callable=_run,
                   on_failure_callback=_notify_failure)
