# Airflow 2.9 → 3.0 마이그레이션

## 적용한 변경
- `PythonOperator`가 `airflow.providers.standard.operators.python`로 이동
  (3.0에서 코어 오퍼레이터가 `standard` provider로 분리됨).
- requirements에 `apache-airflow-providers-standard` 추가.
- `execution_date` 사용 없음 확인 (3.0에서 제거, `logical_date`로 대체).
- `catchup=False` 명시 (3.0 기본값도 False).

## 검증
- `tests/test_dag_import.py`가 2.9.3과 3.0.0 양쪽에서 통과 (DagBag 임포트, 에러 없음).

## 참고한 breaking-change 체크리스트
- 오퍼레이터 provider 분리, 스케줄러/UI 재작성, Task Execution API
  (태스크에서 커스텀 DB 접근 없음 — 태스크는 파이프라인 엔트리포인트만 호출).
