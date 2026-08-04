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


def test_date_at_the_guard_boundary_is_accepted():
    # 수집 시각 + 정확히 1시간: 채택돼야 함 (경계 정각).
    got = decide(_ld("2026-07-18T22:56:51Z"), _FETCHED)
    assert got is not None
    assert got[0] == datetime(2026, 7, 18, 22, 56, 51)


def test_date_just_beyond_the_guard_is_rejected():
    # 수집 시각 + 1시간 + 1초: 폐기돼야 함 (경계 1초 뒤).
    assert decide(_ld("2026-07-18T22:56:52Z"), _FETCHED) is None


def test_target_sources_exclude_tweets():
    sources = {"bbc_sport": {"adapter": "html"},
               "fmkorea": {"adapter": "fmkorea"},
               "x_afcstuff": {"adapter": "x_playwright"},
               "x_ornstein": {"adapter": "x_playwright"}}
    assert target_source_ids(sources) == ["bbc_sport", "fmkorea"]


def test_cli_accepts_source_and_dry_run_flags():
    # 스펙 §4.4 — 언론사와 fmkorea 를 따로 돌리려면 소스 지정이 필요하다.
    import bullet_in.backfill_published_at as m
    ap = m._parser()
    args = ap.parse_args(["--source-id", "fmkorea", "--dry-run", "--limit", "5"])
    assert args.source_id == "fmkorea"
    assert args.dry_run is True
    assert args.limit == 5


def test_cli_defaults_are_all_sources_and_write_mode():
    import bullet_in.backfill_published_at as m
    args = m._parser().parse_args([])
    assert args.source_id is None
    assert args.dry_run is False
    assert args.limit is None
