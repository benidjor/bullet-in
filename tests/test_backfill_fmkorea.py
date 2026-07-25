import pytest
from sqlalchemy import create_engine, text
from bullet_in.backfill_fmkorea import check_page_placeholder, existing_titles


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
