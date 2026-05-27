from __future__ import annotations
import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

def _run():
    import asyncio
    from bullet_in.run import main
    asyncio.run(main(concurrency=8))

with DAG(
    dag_id="bullet_in_daily",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 5, 1, tz="UTC"),
    catchup=False,
    tags=["bullet-in"],
) as dag:
    PythonOperator(task_id="run_pipeline", python_callable=_run)
