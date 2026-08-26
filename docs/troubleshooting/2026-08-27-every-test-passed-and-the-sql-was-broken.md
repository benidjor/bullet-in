# 테스트 1,274개가 전부 통과했는데 서빙 SQL 이 깨져 있었다 (2026-08-27)

링크 선수 배지를 걷어내며 `SERVING_SELECT_SQL` 의 마지막 컬럼을 뺐다.
앞 조각의 쉼표가 남아 문장이 이렇게 됐다.

```
... published_precision,fetched_at,FROM articles
```

**전체 테스트가 통과했다.**
운영 DB 에 붙어 본 실측에서야 문법 오류가 드러났고, 그 실측을 건너뛰었으면 배포까지 갔다.

## 1. 왜 안 잡혔나

### 1.1. 서빙 경로의 SQL 은 어디서도 실행되지 않았다

`SERVING_SELECT_SQL` 은 **문자열 상수**다.
그 문자열을 DB 에 넘기는 코드는 `run.py` 의 서빙 경로 하나뿐이고, 그 경로는 정기 회차에서만 돈다.

테스트는 두 갈래인데 둘 다 이 문자열을 안 건드린다.

- **렌더 테스트** — 파이썬 dict 를 직접 만들어 `render_index` · `facet_counts` 에 넘긴다.
SQL 이 무엇을 돌려주는지는 전제일 뿐 실행 대상이 아니다.
- **통합 테스트** — `MartStore` · `PlayerStore` 의 메서드는 실제 DB 를 쓰지만, 서빙 SELECT 는 그 메서드에 안 들어 있다.

### 1.2. 문자열이라 파이썬도 안 본다

컬럼을 지우는 것은 **문자열 조각을 지우는 것**이라 문법 검사에도 안 걸린다.
`import` 가 되고 상수가 만들어지는 데는 아무 문제가 없다.

## 2. 처방 — 「이 문자열이 SQL 로 성립하는가」 만 보는 검사

`tests/integration/test_serving_sql_executes.py` 를 신설했다.

- `SERVING_SELECT_SQL` 을 실제 DB 에서 실행한다.
- `LINKED_HASHES_SQL` 도 함께 실행한다.
- 렌더가 읽는 컬럼 이름이 결과에 나오는지 본다 (`LIMIT 0` 로 커서만 연다).

**행이 몇 건인지는 안 본다.**
파싱과 컬럼 이름 해석까지 가면 이 회귀는 잡힌다.

```python
def test_serving_select_sql_parses_and_runs(engine):
    with engine.connect() as c:
        rows = c.execute(text(SERVING_SELECT_SQL)).mappings().all()
    assert isinstance(rows, list)          # 빈 테이블이면 [] — 문법만 본다
```

### 2.1. 검사가 실제로 잡는지 확인했다

「없음을 확인하는 검사」 는 검사가 안 돌아도 통과한다 ([[verification-that-silently-passes]]).
그래서 **같은 오류를 일부러 넣고 돌렸다.**

```
2 failed, 1 passed  → 검사가 살아 있다
```

### 2.2. 남는 한계

통합 테스트는 로컬 MariaDB 가 없으면 `pytest.skip` 한다.
**DB 가 없는 환경에서는 이 검사도 안 돈다** — CI 를 붙일 때 그 환경에 DB 가 서 있는지 확인해야 한다.

## 3. 되짚어 얻은 규율

- **테스트가 다 통과했다는 것은 「그 코드가 돈다」 가 아니라 「테스트가 짚은 자리가 돈다」 이다.**
짚지 않은 자리는 몇 개가 통과하든 늘어나지 않는다.
- **문자열로 조립하는 것 (SQL · 템플릿 이름 · 경로) 은 실행해 봐야 검증된다.**
파이썬 문법 검사도 타입 검사도 문자열 안을 안 본다.
- **컬럼을 지울 때는 앞뒤 구분자를 함께 본다** — 이번엔 마지막 컬럼이라 쉼표가 남았다.
- **운영 실측이 마지막 그물이었다.**
「배포 전에 운영 데이터로 한 번 돌려 본다」 를 생략하지 않는 이유가 이런 자리다.

## 4. 관련

- 검증이 조용히 통과하는 다른 모양 — 세션 메모리 `verification-that-silently-passes`
- 문자열 테스트가 바깥 렌더러를 못 본 사례 — `docs/troubleshooting/2026-08-23-unit-tests-passed-but-discord-flattened-the-alert.md`
- 재생성 스니펫이 코드와 어긋난 사례 — `docs/troubleshooting/2026-07-19-runbook-snippet-logic-drift.md`
