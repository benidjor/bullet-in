from datetime import datetime, timezone
from bullet_in.models import RawItem, Article

def test_rawitem_requires_core_fields():
    item = RawItem(source_id="guardian", source_type="api",
                   url="https://x.test/a", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"k": "v"})
    assert item.url == "https://x.test/a"

def test_article_defaults_enrichment_to_none():
    art = Article(content_hash="abc", url="https://x.test/a",
                  source_id="guardian", title_original="Title",
                  published_at=datetime.now(timezone.utc))
    assert art.title_ko is None and art.summary_ko is None and art.revision == 1
