import asyncio

import httpx
import respx

from bullet_in.backfill_author_refetch import (append_state, fetch_authors,
                                               load_state, _SELECT_SQL, _UPDATE_SQL)

LD = ('<html><head><script type="application/ld+json">'
      '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Sami Mokbel"},'
      '{"@type":"Person","name":"Owynn Palmer-Atkin"}]}</script></head>'
      '<body><p>기사 본문</p></body></html>')
NO_AUTHOR = "<html><body><p>기사 본문</p></body></html>"


def _ld_authors(n: int) -> str:
    people = ",".join('{"@type":"Person","name":"Writer %d"}' % i for i in range(n))
    return ('<html><head><script type="application/ld+json">'
            '{"@type":"NewsArticle","author":[' + people + ']}</script></head>'
            '<body><p>기사 본문</p></body></html>')


def _fetch(url: str):
    async def go():
        async with httpx.AsyncClient() as c:
            return await fetch_authors(c, url)
    return asyncio.run(go())


@respx.mock
def test_structured_authors_are_recovered_from_the_origin_page():
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=LD))
    assert _fetch("https://ex.test/a") == (["Sami Mokbel", "Owynn Palmer-Atkin"], "회수")


@respx.mock
def test_page_without_an_author_is_reported_not_treated_as_a_failure():
    # 「원본에 없다」 와 「못 붙었다」 를 갈라 적어야 다음 사람이 같은 조사를 다시 안 한다
    respx.get("https://ex.test/b").mock(return_value=httpx.Response(200, text=NO_AUTHOR))
    assert _fetch("https://ex.test/b") == ([], "저자 없음")


@respx.mock
def test_blocked_origin_keeps_the_batch_going_with_its_status():
    respx.get("https://ex.test/c").mock(return_value=httpx.Response(406))
    assert _fetch("https://ex.test/c") == ([], "http 406")


@respx.mock
def test_connection_error_is_labelled_not_raised():
    respx.get("https://ex.test/d").mock(side_effect=httpx.ConnectError("boom"))
    assert _fetch("https://ex.test/d") == ([], "error ConnectError")


@respx.mock
def test_a_contributor_roster_is_not_taken_as_a_byline():
    # 라이브 블로그는 그날 글을 쓴 사람 전원을 구조화 정보에 싣는다 — 우리가 받은 글의
    # 바이라인이 아니다. 그대로 넣으면 그 글을 안 쓴 기자 열대여섯이 한 기사에 붙는다
    # (실측 2건 · The Athletic transfer-latest 페이지 · 15명 · 16명).
    respx.get("https://ex.test/e").mock(return_value=httpx.Response(200, text=_ld_authors(7)))
    names, label = _fetch("https://ex.test/e")
    assert names == []
    assert label.startswith("명단 과다")


@respx.mock
def test_a_real_coauthor_byline_is_still_taken():
    # 실측에서 정상 바이라인의 최대는 4명이었다 — 공저 회수가 이 가드에 걸리면 안 된다
    respx.get("https://ex.test/f").mock(return_value=httpx.Response(200, text=_ld_authors(4)))
    names, label = _fetch("https://ex.test/f")
    assert len(names) == 4
    assert label == "회수"


def test_update_touches_only_the_authors_column():
    # 저자를 얻으려다 본문까지 갈아 끼우면 body_level 이 흔들려 화면이 바뀐다
    sql = str(_UPDATE_SQL)
    assert "authors_json" in sql
    assert "body_source" not in sql and "body_level" not in sql
    assert "journalist" not in sql


def test_targets_are_fmkorea_rows_without_authors():
    # 직수집 소스는 표본 10건 전건에서 원문에도 저자가 없어 대상이 아니다
    sql = str(_SELECT_SQL)
    assert "authors_json IS NULL" in sql
    assert "source_id = 'fmkorea'" in sql


def test_targets_include_rows_a_korean_fallback_already_filled():
    # 안건 λ — 「비어 있다」 로 잡으면 게시자가 옮긴 한글 이름이 든 행이 통째로 빠진다
    sql = str(_SELECT_SQL)
    assert "[가-힣]" in sql
    assert "NOT REGEXP '[A-Za-z]'" in sql


def test_rows_that_already_carry_a_latin_form_are_not_targets():
    # 영문 표기를 이미 가진 행은 재접속으로 얻을 것이 없다 (51행 중 7행)
    sql = str(_SELECT_SQL)
    assert sql.index("NOT REGEXP '[A-Za-z]'") > sql.index("REGEXP '[가-힣]'")


def test_each_target_carries_why_it_was_selected():
    # 두 갈래를 갈라 세어야 「무엇이 대상에서 빠졌나」 를 다음 회차가 읽는다
    sql = str(_SELECT_SQL)
    assert "AS kind" in sql


def test_state_file_round_trips_and_skips_what_was_already_tried(tmp_path):
    p = tmp_path / "state.txt"
    assert load_state(str(p)) == set()
    append_state(str(p), "a" * 64)
    append_state(str(p), "b" * 64)
    assert load_state(str(p)) == {"a" * 64, "b" * 64}


def test_state_path_of_none_is_a_no_op():
    append_state(None, "a" * 64)
    assert load_state(None) == set()
