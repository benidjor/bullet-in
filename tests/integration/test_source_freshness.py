from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.quality import evaluate_freshness
from bullet_in.storage.mariadb import MartStore


def _art(h, url, fetched_at):
    return Article(content_hash=h, url=url, source_id="bbc_sport",
                   title_original="T", published_at=fetched_at, fetched_at=fetched_at)


def test_source_watermarks_returns_max_fetched_at(engine):
    store = MartStore(engine)
    store.upsert([_art("h1", "https://x.test/1", datetime(2026, 7, 10, 8, 0)),
                  _art("h2", "https://x.test/2", datetime(2026, 7, 12, 9, 30))])
    wm = store.source_watermarks()
    assert wm["bbc_sport"] == datetime(2026, 7, 12, 9, 30)


def test_db_now_returns_utc_datetime(engine):
    now = MartStore(engine).db_now()
    assert isinstance(now, datetime)
    drift = abs((datetime.now(timezone.utc).replace(tzinfo=None) - now).total_seconds())
    assert drift < 300  # UTC 계약: 세션 TZ 와 무관하게 UTC 현재 시각


def test_record_freshness_persists_rows_with_shared_run_id(engine):
    store = MartStore(engine)
    now = store.db_now()
    records = evaluate_freshness({"bbc_sport": None}, now, default_hours=48)
    store.record_freshness("run-1", now, records)
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT run_id, source_id, last_fetched_at, stale "
            "FROM source_freshness")).all()
    assert rows == [("run-1", "bbc_sport", None, 0)]


def test_record_freshness_persists_stored_watermark_for_absorption_watch(engine):
    # 판정은 원본 수집으로 하고 기사 표 워터마크는 여기 기록만 남긴다 —
    # 두 값이 벌어지는 소스가 곧 흡수당하는 소스다 (설계 2026-08-20 §3.4)
    store = MartStore(engine)
    now = store.db_now()
    raw_wm = now - timedelta(hours=10)
    records = evaluate_freshness({"x_ornstein": raw_wm}, now, default_hours=120)
    records[0].stored_fetched_at = datetime(2026, 8, 1, 12, 3)
    store.record_freshness("run-1", now, records)
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT stale, stored_fetched_at FROM source_freshness")).one()
    assert row == (0, datetime(2026, 8, 1, 12, 3))


def test_record_freshness_empty_records_is_noop(engine):
    MartStore(engine).record_freshness("run-1", datetime(2026, 7, 13), [])
    with engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM source_freshness")).scalar_one()
    assert n == 0


def test_previous_freshness_returns_latest_cycle_only(engine):
    store = MartStore(engine)
    older = datetime(2026, 8, 19, 3, 0)
    newer = datetime(2026, 8, 19, 6, 0)
    store.record_freshness("run-old", older, evaluate_freshness(
        {"x_ornstein": older - timedelta(hours=423)}, older, 120.0))
    store.record_freshness("run-new", newer, evaluate_freshness(
        {"x_ornstein": newer - timedelta(hours=426),
         "bbc_sport": newer - timedelta(hours=2)}, newer, 120.0))
    prev = store.previous_freshness()
    assert sorted(prev) == ["bbc_sport", "x_ornstein"]
    assert round(prev["x_ornstein"]["age_hours"]) == 426
    assert prev["x_ornstein"]["threshold_hours"] == 120.0


def test_previous_freshness_empty_on_first_cycle(engine):
    assert MartStore(engine).previous_freshness() == {}
