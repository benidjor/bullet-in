# Airflow DAG 임포트 테스트가 skip되지 않고 에러

- **날짜**: 2026-05-27
- **영역**: airflow / test
- **심각도**: 중 (CI/로컬 테스트 그린을 막음)

## 증상
프로젝트 venv(Apache Airflow 미설치)에서 `uv run pytest`를 돌리면, `tests/test_dag_import.py`가 **skip되지 않고** collection 단계에서 실패한다.

```
ModuleNotFoundError: No module named 'airflow.models'
```

기대했던 동작은 "Airflow가 없으니 이 테스트만 조용히 skip"이었다. 테스트 코드는 다음과 같았다:

```python
import pytest
pytest.importorskip("airflow")          # ← 여기서 막아줄 거라 기대
from airflow.models import DagBag        # ← 실제로는 여기서 터짐
```

## 진단 과정 (왜 이렇게 판단했는가)
1. **기대 vs 실제 대조**: `importorskip("airflow")`는 "import 실패 시 skip"이다. 그런데 skip이 아니라 그 *다음 줄*에서 에러가 났다 → "`import airflow`는 성공했는데 `airflow.models`만 없다"는 뜻으로 좁혔다.
2. **가설**: 프로젝트 루트에 `airflow/`(DAG 디렉터리)가 있으니, 파이썬이 그걸 `airflow`라는 (네임스페이스) 패키지로 잡는 것 아닐까?
3. **확인**: 인터프리터에서 직접 확인했다.
   ```text
   $ uv run python -c "import airflow; print(airflow.__path__)"
   airflow.__path__ = ['/Users/.../bullet-in/airflow']   # 진짜 Airflow가 아니라 프로젝트 DAG 폴더
   $ uv run python -c "import importlib.util as u; print(u.find_spec('airflow.models') is not None)"
   False                                                  # 실제 모듈은 없음
   ```
   `import airflow`가 (프로젝트 폴더로) "성공"하므로 `importorskip("airflow")`가 통과해버리고, `airflow.models`는 없어 다음 줄에서 터진다.
   <!-- 스크린샷(선택): pytest의 collection 에러 → 수정 후 skip/pass 터미널 -->

4. **결론**: 디렉터리명이 패키지명을 섀도잉 → `importorskip("airflow")`는 의미가 없고, 실제로 필요한 건 `airflow.models`다.

## 원인
PEP 420 네임스페이스 패키지 규칙상, `airflow/`라는 디렉터리가 `sys.path`(프로젝트 루트)에 있으면 `import airflow`가 그 디렉터리로 해석된다. `importorskip("airflow")`는 이 "가짜 성공"에 속아 skip하지 않는다.

## 해결
importorskip 대상을 **실제로 사용할 서브모듈**로 바꾼다.

```python
pytest.importorskip("airflow.models")   # "airflow" 가 아니라 이것
from airflow.models import DagBag
```

- 프로젝트 venv: `airflow.models`가 없으므로 정상 skip.
- Airflow 설치된 격리 venv: 통과(2.9.3·3.0.0 양쪽 확인).

## 예방
- 패키지명과 동일한 이름의 디렉터리(`airflow/`, `dbt/` 등)가 리포 루트에 있으면, `importorskip`/`import` 가드는 항상 **실제 사용할 서브모듈**을 지정한다.
- DAG 검증은 프로젝트 venv가 아니라 격리 venv에서 수행한다 → `docs/runbook/airflow-dag-verification.md`.
