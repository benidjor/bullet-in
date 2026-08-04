"""발행일 복구 — 판정 규칙과 대상 선정."""
from datetime import datetime
from bullet_in.backfill_published_at import decide, target_source_ids

_FETCHED = datetime(2026, 7, 18, 21, 56, 51)


def _ld(iso: str) -> str:
    return ('<html><head><script type="application/ld+json">'
            f'{{"@type":"NewsArticle","datePublished":"{iso}"}}'
            '</script></head><body></body></html>')


def test_extracted_date_is_adopted():
    got = decide(_ld("2026-07-14T14:11:47.899Z"), _FETCHED)
    assert got is not None
    assert got[0] == datetime(2026, 7, 14, 14, 11, 47, 899000)
    assert got[1] == "time"


def test_no_date_in_html_is_skipped():
    # 추출 실패는 무변경 — 기존 값을 더 나쁜 값으로 덮지 않는다.
    assert decide("<html><head></head><body>no date</body></html>", _FETCHED) is None


def test_future_date_is_rejected():
    # 수집 시각 + 1시간을 넘는 값은 오파싱으로 본다 (pipeline._published 와 같은 가드).
    assert decide(_ld("2026-07-19T09:00:00Z"), _FETCHED) is None


def test_date_just_inside_the_guard_is_accepted():
    got = decide(_ld("2026-07-18T22:30:00Z"), _FETCHED)
    assert got is not None
    assert got[0] == datetime(2026, 7, 18, 22, 30)


def test_target_sources_exclude_tweets():
    sources = {"bbc_sport": {"adapter": "html"},
               "fmkorea": {"adapter": "fmkorea"},
               "x_afcstuff": {"adapter": "x_playwright"},
               "x_ornstein": {"adapter": "x_playwright"}}
    assert target_source_ids(sources) == ["bbc_sport", "fmkorea"]
