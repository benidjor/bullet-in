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

def test_article_accepts_tier2a_fields():
    art = Article(content_hash="abc", url="https://x.test/a",
                  source_id="bbc_sport", title_original="Title",
                  published_at=datetime(2026, 6, 29, tzinfo=timezone.utc),
                  summary3_ko="①\n②\n③", body_ko="본문", body_source="body",
                  image_url="https://img.test/a.jpg", outlet="BBC",
                  journalist="Sami Mokbel", team="arsenal")
    assert art.summary3_ko == "①\n②\n③"
    assert art.outlet == "BBC" and art.journalist == "Sami Mokbel"
    assert art.team == "arsenal"

def test_article_tier2a_fields_default_none():
    art = Article(content_hash="abc", url="https://x.test/a", source_id="g",
                  title_original="T", published_at=datetime(2026, 6, 29, tzinfo=timezone.utc))
    assert art.summary3_ko is None and art.body_ko is None and art.image_url is None
    assert art.outlet is None and art.journalist is None and art.team == "arsenal"
