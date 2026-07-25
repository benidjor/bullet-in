import pytest
from sqlalchemy import create_engine, text
from bullet_in.backfill_fmkorea import check_page_placeholder, existing_titles, resolve_keywords

_CFG_KW = [{"keyword": "아스날", "target": "title"},
           {"keyword": "온스테인", "target": "title_content"}]


def test_page_placeholder_ok_when_present():
    check_page_placeholder("https://fm.test/s?kw={keyword}&page={page}", 3)  # 예외 없음


def test_page_placeholder_ok_when_single_page():
    check_page_placeholder("https://fm.test/s?kw={keyword}", 1)              # 예외 없음


def test_page_placeholder_rejects_multipage_without_placeholder():
    with pytest.raises(SystemExit):
        check_page_placeholder("https://fm.test/s?kw={keyword}", 3)


def test_existing_titles_returns_only_fmkorea_and_skips_null():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE articles (source_id TEXT, title_original TEXT)"))
        c.execute(text("INSERT INTO articles VALUES ('fmkorea', '[BBC] 아스날 1')"))
        c.execute(text("INSERT INTO articles VALUES ('fmkorea', NULL)"))
        c.execute(text("INSERT INTO articles VALUES ('bbc_sport', '[BBC] 다른 소스')"))
    assert existing_titles(engine) == {"[BBC] 아스날 1"}


def test_resolve_keywords_defaults_to_config():
    assert resolve_keywords(_CFG_KW, None, "title") == _CFG_KW


def test_resolve_keywords_empty_list_falls_back_to_config():
    assert resolve_keywords(_CFG_KW, [], "title") == _CFG_KW


def test_resolve_keywords_adhoc_overrides_config():
    out = resolve_keywords(_CFG_KW, ["디오망데", "알바레스"], "title")
    assert out == [{"keyword": "디오망데", "target": "title"},
                   {"keyword": "알바레스", "target": "title"}]
