# Airflow 2.9 → 3.0 마이그레이션

## 적용한 변경
- `PythonOperator`가 `airflow.providers.standard.operators.python`로 이동
  (3.0에서 코어 오퍼레이터가 `standard` provider로 분리됨).
- requirements에 `apache-airflow-providers-standard` 추가.
- `execution_date` 사용 없음 확인 (3.0에서 제거, `logical_date`로 대체).
- `catchup=False` 명시 (3.0 기본값도 False).

## 검증
- 마이그레이션 시점 기준으로, `tests/test_dag_import.py`가 **각 버전의 코드 상태에서** 통과:
  - 마이그레이션 직전 커밋의 DAG(2.9 import)를 2.9.3 환경에서 → PASS
  - 마이그레이션 후 DAG(3.0 import)를 3.0.0 환경에서 → PASS
- 같은 코드가 두 버전에서 동시에 통과한다는 의미가 아님 — 마이그레이션은 코드를 3.0 전용 import 경로로 옮기는 작업이라, post-migration DAG는 2.9에서 의도적으로 실패(=마이그레이션이 적용됐다는 증거).
- 사후 재현 절차: `docs/runbook/airflow-dag-verification.md`의 "마이그레이션 검증" 절 참고.

## 참고한 breaking-change 체크리스트
- 오퍼레이터 provider 분리, 스케줄러/UI 재작성, Task Execution API
  (태스크에서 커스텀 DB 접근 없음 — 태스크는 파이프라인 엔트리포인트만 호출).
