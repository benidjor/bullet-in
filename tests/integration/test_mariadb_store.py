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

def test_watermark_returns_seen_map(engine):
    store = MartStore(engine)
    store.upsert([_art()])
    seen = store.seen_map()
    assert seen["https://x.test/a"][0] == "h1"
