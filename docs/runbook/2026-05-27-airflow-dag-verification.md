# 런북 — Airflow DAG 검증 (프로젝트 venv 오염 없이)

DAG 파싱 (DagBag 임포트)을 프로젝트 환경과 **분리된 일회용 venv**에서 검증한다. Airflow는 의존성이 무겁고 핀이 빡빡해 프로젝트 deps (pydantic · httpx · playwright 등)와 충돌할 수 있으므로, 프로젝트 venv에는 설치하지 않는다.

## 왜 격리하나
- 프로젝트 venv엔 Airflow가 없어, `tests/test_dag_import.py`는 거기서 **정상 skip**된다 (`importorskip("airflow.models")`). 이는 결함이 아니라 의도된 동작.
- 실제 검증은 Airflow만 설치한 격리 venv에서 한다. (프로젝트 deps와 한 환경에 섞으면 의존성 해석이 깨지기 쉽다.)
- 현재 DAG (`airflow/dags/bullet_in_cycle.py`) 는 파싱 시 `bullet_in` 을 아예 import하지 않는다 (오퍼레이터가 전부 `BashOperator`, 스펙 2026-09-04 §3.4).
  DagBag 파싱에는 Airflow + pendulum만 있으면 된다 (프로젝트 설치 불필요).
  단, 저장소 루트의 `conftest.py` 는 `bullet_in` 을 import하므로, 격리 venv 로 pytest 를 돌릴 때는 `--noconftest` 로 그것을 건너뛴다.

## 절차 (3.3.1 · 격리 venv)

```bash
uv venv --python 3.11 /tmp/af331
uv pip install --python /tmp/af331/bin/python --quiet \
  "apache-airflow==3.3.1" "apache-airflow-providers-standard" pytest pendulum \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt"
AIRFLOW_HOME=/tmp/af331/home /tmp/af331/bin/python -m pytest tests/test_dag_import.py -q -p no:cacheprovider --noconftest
```

기대: `10 passed`.
`tests/test_dag_import.py` 의 `DagBag(dag_folder="airflow/dags")` 는 3.3.1 기준이다.
Airflow 3.3.1 의 `DagBag` 생성자는 `include_examples` 인자를 받지 않는다 (스캔 대상이 `airflow/dags` 뿐이라 예제 DAG 은 애초에 안 걸린다).
`-p no:cacheprovider` 는 격리 venv 밖 (프로젝트 트리) 에 pytest 캐시 디렉터리를 안 남기기 위해서다.

## 정리
```bash
rm -rf /tmp/af331   # 일회용 venv 제거
```

## 이력 — 2.9 → 3.0 마이그레이션 검증 (2026-05-27)

당시 절차는 `airflow/dags/bullet_in_daily.py` 를 2.9.3 venv 와 3.0.0 venv 양쪽에서 통과시켜 마이그레이션 전후를 대조하는 것이었다.
그 파일은 2026-09-04 회차 전환 (안건 2ε) 에서 `airflow/dags/bullet_in_cycle.py` 로 대체되며 삭제됐고, 지금 저장소에는 재현할 대상이 남아 있지 않다.
2.9 → 3.0 이관 자체에서 적용한 변경은 `docs/MIGRATION.md` 에 있다.

## 비고 / 함정
- **공식 constraints 파일**을 반드시 쓴다. 안 쓰면 무거운 Airflow 의존성이 충돌 · 미해결로 설치 실패하기 쉽다.
- 3.0에서 `PythonOperator`는 `airflow.providers.standard.operators.python`로 이동했다 → `docs/MIGRATION.md`.
- 루트의 `airflow/` 디렉터리가 네임스페이스 패키지로 잡혀 importorskip이 오작동하는 함정은 `docs/troubleshooting/2026-05-27-airflow-namespace-shadowing.md` 참고.
