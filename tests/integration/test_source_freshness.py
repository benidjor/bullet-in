from datetime import datetime, timezone
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


def test_record_freshness_empty_records_is_noop(engine):
    MartStore(engine).record_freshness("run-1", datetime(2026, 7, 13), [])
    with engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM source_freshness")).scalar_one()
    assert n == 0
