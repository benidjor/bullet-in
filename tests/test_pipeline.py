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

def test_to_articles_maps_tier2a_fields():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://www.bbc.com/sport/football/articles/g",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign Gyokeres", "body": "English body",
                                "image_url": "https://img.test/g.jpg", "outlet": "BBC",
                                "journalist": "Sami Mokbel"})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].body_source == "English body"
    assert arts[0].image_url == "https://img.test/g.jpg"
    assert arts[0].outlet == "BBC" and arts[0].journalist == "Sami Mokbel"
    assert arts[0].team == "arsenal"

def test_to_articles_prefers_en_source_over_fmkorea_for_same_url():
    now = datetime.now(timezone.utc)
    url = "https://www.bbc.com/sport/football/articles/g"
    raw = [
        RawItem(source_id="fmkorea", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "Arsenal sign Gyokeres", "outlet": "BBC"}),
        RawItem(source_id="bbc_sport", source_type="html", url=url, fetched_at=now,
                raw_payload={"title": "Arsenal sign Gyokeres", "outlet": "BBC"}),
    ]
    sources = {"fmkorea": {"source_id": "fmkorea", "tier": 4},
               "bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, stats = to_articles(raw, sources, seen={})
    assert len(arts) == 1
    assert arts[0].source_id == "bbc_sport"   # EN 우선, fmkorea 스킵
    assert stats["dup_count"] == 1

def test_to_articles_passes_inline_images():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://x.test/g", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign G", "body": "B",
                                "images": ["https://img.test/1.jpg"]})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].images == ["https://img.test/1.jpg"]

def test_to_articles_defaults_images_empty():
    raw = [RawItem(source_id="bbc_sport", source_type="html",
                   url="https://x.test/h", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign H"})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 2}}
    arts, _ = to_articles(raw, sources, seen={})
    assert arts[0].images == []

def test_to_articles_drops_womens_football():
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="football_london", source_type="html", url="https://y.test/w1",
                fetched_at=now, raw_payload={"title": "Arsenal Women complete transfer"}),
        RawItem(source_id="football_london", source_type="html", url="https://y.test/w2",
                fetched_at=now,
                raw_payload={"title": "Arsenal announce fifth summer transfer",
                             "body": "Lisa Baum has been confirmed as Arsenal Women's fifth summer addition."}),
        RawItem(source_id="football_london", source_type="html", url="https://y.test/m1",
                fetched_at=now, raw_payload={"title": "Arsenal agree deal for Gyokeres",
                                             "body": "Arsenal have agreed a deal."}),
    ]
    sources = {"football_london": {"source_id": "football_london", "tier": 4}}
    arts, stats = to_articles(raw, sources, seen={})
    assert [a.url for a in arts] == ["https://y.test/m1"]
    assert stats["women_count"] == 2

def test_to_articles_keeps_mens_article_with_late_women_mention():
    # 본문 후반부의 women 언급 (도입 400자 밖) 은 필터하지 않는다
    now = datetime.now(timezone.utc)
    raw = [RawItem(source_id="football_london", source_type="html", url="https://y.test/m2",
                   fetched_at=now,
                   raw_payload={"title": "Arsenal transfer roundup",
                                "body": ("Arsenal have agreed a deal. " * 20) + "Also Arsenal Women won."})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4}}
    arts, _ = to_articles(raw, sources, seen={})
    assert len(arts) == 1
