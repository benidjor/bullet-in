# 런북 — Airflow DAG 검증 (프로젝트 venv 오염 없이)

DAG 파싱(DagBag 임포트)을 프로젝트 환경과 **분리된 일회용 venv**에서 검증한다. Airflow는 의존성이 무겁고 핀이 빡빡해 프로젝트 deps(pydantic·httpx·playwright 등)와 충돌할 수 있으므로, 프로젝트 venv에는 설치하지 않는다.

## 왜 격리하나
- 프로젝트 venv엔 Airflow가 없어, `tests/test_dag_import.py`는 거기서 **정상 skip**된다(`importorskip("airflow.models")`). 이는 결함이 아니라 의도된 동작.
- 실제 검증은 Airflow만 설치한 격리 venv에서 한다. (프로젝트 deps와 한 환경에 섞으면 의존성 해석이 깨지기 쉽다.)
- DAG 파일은 `from bullet_in.run import main`을 **함수 안에서** import(지연)하므로, DagBag 파싱에는 Airflow + pendulum만 있으면 된다(프로젝트 설치 불필요).

## 절차 (2.9.3 / 3.0.0 각각)
```bash
# Airflow 2.9.3
uv venv /tmp/af29 --python 3.11
/tmp/af29/bin/python -m pip install --quiet "apache-airflow==2.9.3" pytest pendulum \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.3/constraints-3.11.txt"
/tmp/af29/bin/python -m pytest tests/test_dag_import.py -v

# Airflow 3.0.0
uv venv /tmp/af30 --python 3.11
/tmp/af30/bin/python -m pip install --quiet "apache-airflow==3.0.0" "apache-airflow-providers-standard" pytest pendulum \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.0.0/constraints-3.11.txt"
/tmp/af30/bin/python -m pytest tests/test_dag_import.py -v
```
기대: 두 버전 모두 `test_dag_imports_without_errors` PASS (DagBag 임포트 에러 0, `bullet_in_daily` DAG 존재).

<!-- 터미널 캡처 → docs/assets/airflow-dag-import.png 저장 후 아래 주석 해제 -->
<!-- ![DagBag 임포트 통과(2.9/3.0)](../assets/airflow-dag-import.png) -->
<!-- (라이브) Airflow UI 캡처 → docs/assets/airflow-ui-dag-graph.png 저장 후 아래 주석 해제 -->
<!-- ![Airflow UI — bullet_in_daily DAG 그래프](../assets/airflow-ui-dag-graph.png) -->

## 정리
```bash
rm -rf /tmp/af29 /tmp/af30   # 일회용 venv 제거
```

## 비고 / 함정
- **공식 constraints 파일**을 반드시 쓴다. 안 쓰면 무거운 Airflow 의존성이 충돌·미해결로 설치 실패하기 쉽다.
- 3.0에서 `PythonOperator`는 `airflow.providers.standard.operators.python`로 이동했다 → `docs/MIGRATION.md`.
- 루트의 `airflow/` 디렉터리가 네임스페이스 패키지로 잡혀 importorskip이 오작동하는 함정은 `docs/troubleshooting/2026-05-27-airflow-namespace-shadowing.md` 참고.
