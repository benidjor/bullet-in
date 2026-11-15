"""Arsenal.com 늦게 들어온 옛 글 서빙 제외 (계획 2026-11-15-arsenal-late-republished · Task 2)."""
from datetime import datetime, timedelta
from bullet_in.run import drop_late_official

T = datetime(2026, 11, 3, 0, 2, 9)


def _r(sid, pub, fetched=T, h="h"):
    return {"source_id": sid, "published_at": pub, "fetched_at": fetched, "content_hash": h}


def test_drops_official_rows_stored_long_after_publication():
    rows = [_r("arsenal_official", datetime(2015, 9, 16, 7), h="old"),
            _r("arsenal_official", T - timedelta(hours=3), h="new")]
    keep, n = drop_late_official(rows)
    assert [r["content_hash"] for r in keep] == ["new"] and n == 1


def test_exactly_thirty_days_is_kept():
    keep, n = drop_late_official([_r("arsenal_official", T - timedelta(days=30))])
    assert len(keep) == 1 and n == 0
    keep, n = drop_late_official([_r("arsenal_official", T - timedelta(days=30, seconds=1))])
    assert keep == [] and n == 1


def test_other_sources_are_untouched():
    rows = [_r("fmkorea", datetime(2022, 10, 1)), _r("guardian", datetime(2025, 1, 1))]
    keep, n = drop_late_official(rows)
    assert len(keep) == 2 and n == 0


def test_missing_dates_are_kept():
    rows = [_r("arsenal_official", None), _r("arsenal_official", T, fetched=None)]
    keep, n = drop_late_official(rows)
    assert len(keep) == 2 and n == 0
