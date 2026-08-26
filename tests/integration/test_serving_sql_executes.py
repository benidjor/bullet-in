"""서빙 SELECT 가 실제 DB 에서 도는지 — 문법 회귀 가드.

2026-08-27 에 `SERVING_SELECT_SQL` 의 마지막 컬럼 (linked_players) 을 빼면서
앞 조각의 쉼표가 남아 `... fetched_at,FROM articles` 가 됐다.
**단위 테스트 1,274개가 전부 통과했다** — 서빙 경로의 SQL 은 어디서도 실행되지
않고 렌더 테스트는 파이썬 dict 를 직접 넘기기 때문이다.
운영 DB 에 붙어 본 실측에서야 문법 오류가 드러났다.

그래서 "이 문자열이 SQL 로 성립하는가" 만 보는 검사를 둔다.
행이 없어도 된다 — 파싱과 컬럼 이름 해석까지 가면 이 회귀는 잡힌다.
"""
from sqlalchemy import text

from bullet_in.run import SERVING_SELECT_SQL, LINKED_HASHES_SQL


def test_serving_select_sql_parses_and_runs(engine):
    with engine.connect() as c:
        rows = c.execute(text(SERVING_SELECT_SQL)).mappings().all()
    assert isinstance(rows, list)          # 빈 테이블이면 [] — 문법만 본다


def test_linked_hashes_sql_parses_and_runs(engine):
    with engine.connect() as c:
        hashes = c.execute(text(LINKED_HASHES_SQL)).scalars().all()
    assert isinstance(hashes, list)


def test_serving_select_returns_the_columns_render_reads(engine):
    """렌더가 읽는 컬럼이 실제로 나오는지 — 이름을 지우면 여기서 걸린다."""
    with engine.connect() as c:
        cur = c.execute(text(SERVING_SELECT_SQL + " LIMIT 0"))
        cols = set(cur.keys())
    for name in ("content_hash", "url", "source_id", "title_ko", "summary_ko",
                 "transfer_stage", "transfer_direction", "tier",
                 "published_at", "fetched_at"):
        assert name in cols, f"서빙 SELECT 에 {name} 이 없다"
