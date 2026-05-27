import pytest
pytest.importorskip("airflow.models")
from airflow.models import DagBag

def test_dag_imports_without_errors():
    bag = DagBag(dag_folder="airflow/dags", include_examples=False)
    assert bag.import_errors == {}
    assert "bullet_in_daily" in bag.dags
