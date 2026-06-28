from datetime import datetime, timezone
from pathlib import Path
from bullet_in.pipeline import to_articles
from bullet_in.models import RawItem
from bullet_in.credibility import load_registry

REG = load_registry(Path("config/credibility.yaml"))

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
    arts, _ = to_articles(raw, sources, seen={})
    assert len(arts) == 1
    assert arts[0].tier == 0 and arts[0].confidence_score == 1.0
    assert len(arts[0].content_hash) == 64

def test_to_articles_drops_x_item_without_journalist():
    raw = [RawItem(source_id="x_afcstuff", source_type="x",
                   url="https://x.test/t1", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"text": "no journalist here"})]
    sources = {"x_afcstuff": {"source_id": "x_afcstuff", "credibility": "x_mentions"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert arts == []

def test_to_articles_fmkorea_uses_body_as_excerpt_and_fallback_tier():
    raw = [RawItem(source_id="fmkorea", source_type="html",
                   url="https://fm.test/1", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "[무명] 카더라", "body": "본문 내용",
                                "published": "2026-06-11T10:00:00Z"})]
    sources = {"fmkorea": {"source_id": "fmkorea", "credibility": "fmkorea"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1
    assert arts[0].tier == 4.0 and arts[0].confidence_score == 0.0
    assert arts[0].body_excerpt == "본문 내용"

def test_to_articles_returns_dup_and_source_counts():
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/a",
                fetched_at=now, raw_payload={"title": "Arsenal sign Rice"}),
        RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/a?utm_source=x",
                fetched_at=now, raw_payload={"title": "Arsenal sign Rice"}),  # 중복
        RawItem(source_id="football_london", source_type="html", url="https://y.test/b",
                fetched_at=now, raw_payload={"title": "Saka deal"}),
    ]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2},
               "football_london": {"source_id": "football_london", "tier": 4}}
    arts, stats = to_articles(raw, sources, seen={})
    assert len(arts) == 2
    assert stats["dup_count"] == 1
    assert stats["source_counts"] == {"bbc_sport": 1, "football_london": 1}
