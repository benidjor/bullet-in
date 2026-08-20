from datetime import datetime, timezone
import mongomock
from bullet_in.storage.mongo import RawStore
from bullet_in.models import RawItem

def _item(url, h):
    return RawItem(source_id="s", source_type="api", url=url,
                  fetched_at=datetime.now(timezone.utc), raw_payload={}, content_hash=h)

def _at(source_id, h, when):
    return RawItem(source_id=source_id, source_type="api",
                   url=f"https://x.test/{h}", fetched_at=when,
                   raw_payload={}, content_hash=h)

def test_insert_is_idempotent_on_content_hash():
    store = RawStore(mongomock.MongoClient().db)
    store.insert_many([_item("https://x.test/a", "h1")])
    store.insert_many([_item("https://x.test/a", "h1")])
    assert store.count() == 1

def test_source_watermarks_returns_max_per_source_as_naive_utc():
    store = RawStore(mongomock.MongoClient().db)
    old = datetime(2026, 8, 1, 12, 3, tzinfo=timezone.utc)
    new = datetime(2026, 8, 19, 15, 5, tzinfo=timezone.utc)
    store.insert_many([_at("x_ornstein", "h1", old), _at("x_ornstein", "h2", new),
                       _at("bbc_sport", "h3", old)])
    # db_now() 가 tz-naive UTC 라 경과 계산이 바로 되게 같은 모양으로 돌려준다
    assert store.source_watermarks() == {
        "x_ornstein": datetime(2026, 8, 19, 15, 5),
        "bbc_sport": datetime(2026, 8, 1, 12, 3)}

def test_source_watermarks_omits_sources_without_documents():
    store = RawStore(mongomock.MongoClient().db)
    assert store.source_watermarks() == {}
