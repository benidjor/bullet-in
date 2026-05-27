from datetime import datetime, timezone
import mongomock
from bullet_in.storage.mongo import RawStore
from bullet_in.models import RawItem

def _item(url, h):
    return RawItem(source_id="s", source_type="api", url=url,
                  fetched_at=datetime.now(timezone.utc), raw_payload={}, content_hash=h)

def test_insert_is_idempotent_on_content_hash():
    store = RawStore(mongomock.MongoClient().db)
    store.insert_many([_item("https://x.test/a", "h1")])
    store.insert_many([_item("https://x.test/a", "h1")])
    assert store.count() == 1
