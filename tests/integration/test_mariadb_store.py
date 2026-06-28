from datetime import datetime, timezone
from bullet_in.storage.mariadb import MartStore
from bullet_in.models import Article

def _art(h="h1", url="https://x.test/a", title="T"):
    return Article(content_hash=h, url=url, source_id="guardian",
                   title_original=title, published_at=datetime(2026,5,27,tzinfo=timezone.utc))

def test_upsert_dedup_keeps_single_row(engine):
    store = MartStore(engine)
    store.upsert([_art()]); store.upsert([_art()])
    assert store.count() == 1

def test_upsert_empty_list_is_noop(engine):
    # 신규 없는 회차(6시간마다 흔함)는 빈 배치 → 에러 없이 0 반환해야 한다
    assert MartStore(engine).upsert([]) == 0

def test_watermark_returns_seen_map(engine):
    store = MartStore(engine)
    store.upsert([_art()])
    seen = store.seen_map()
    assert seen["https://x.test/a"][0] == "h1"

def test_changed_url_updates_hash_and_resets_translation(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="g",
                          title_original="Old", published_at=datetime(2026,5,27,tzinfo=timezone.utc))])
    store.set_translation("h1", "옛제목", "옛요약")
    # same url, new hash + title, revision bumped
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="g",
                          title_original="New", revision=2,
                          published_at=datetime(2026,5,27,tzinfo=timezone.utc))])
    assert store.count() == 1
    assert store.seen_map()["https://x.test/a"] == ("h2", 2)
    missing = {r["content_hash"] for r in store.rows_missing_translation()}
    assert "h2" in missing  # translation reset so enrich re-runs
