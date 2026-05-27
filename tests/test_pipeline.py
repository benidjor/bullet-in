from datetime import datetime, timezone
from bullet_in.pipeline import to_articles
from bullet_in.models import RawItem

def test_to_articles_assigns_hash_tier_confidence_and_dedups():
    raw = [
        RawItem(source_id="arsenal_official", source_type="rss",
                url="https://x.test/a", fetched_at=datetime.now(timezone.utc),
                raw_payload={"title": "Win", "published": "2026-05-27T10:00:00Z"}),
        RawItem(source_id="arsenal_official", source_type="rss",
                url="https://x.test/a?utm_source=x", fetched_at=datetime.now(timezone.utc),
                raw_payload={"title": "Win", "published": "2026-05-27T10:00:00Z"}),
    ]
    sources = {"arsenal_official": {"source_id": "arsenal_official", "tier": 0}}
    arts = to_articles(raw, sources, seen={})
    assert len(arts) == 1
    assert arts[0].tier == 0 and arts[0].confidence_score == 1.0
    assert len(arts[0].content_hash) == 64
