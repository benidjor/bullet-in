import pytest
pytest.importorskip("airflow.models")
from airflow.models import DagBag

def test_dag_imports_without_errors():
    bag = DagBag(dag_folder="airflow/dags", include_examples=False)
    assert bag.import_errors == {}
    assert "bullet_in_daily" in bag.dags

def test_failure_callback_attached():
    bag = DagBag(dag_folder="airflow/dags", include_examples=False)
    task = bag.dags["bullet_in_daily"].get_task("run_pipeline")
    assert task.on_failure_callback
