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

from bullet_in.pipeline import select_journalist

def _html_item(source_id, payload):
    return RawItem(source_id=source_id, source_type="html",
                   url="https://x.test/a", fetched_at=datetime.now(timezone.utc),
                   raw_payload={"published": "2026-07-15T10:00:00Z", **payload})

def test_select_journalist_prefers_registered_author():
    # BBC 실측: Telfer(미등재) + Mokbel(등재) → 등재자 대표
    it = _html_item("bbc_sport", {"title": "x", "authors": ["Alastair Telfer", "Sami Mokbel"]})
    assert select_journalist(it, {"tier": 1}, REG) == "Sami Mokbel"

def test_select_journalist_falls_back_to_first_author():
    it = _html_item("football_london", {"title": "x", "authors": ["Raff Tindale", "Unregistered Writer"]})
    assert select_journalist(it, {"tier": 4}, REG) == "Raff Tindale"

def test_select_journalist_uses_source_label_when_configured():
    it = _html_item("arsenal_official", {"title": "x", "authors": ["Arsenal Media"]})
    src = {"tier": 0, "journalist_label": "Arsenal Official"}
    assert select_journalist(it, src, REG) == "Arsenal Official"

def test_select_journalist_label_applies_without_authors():
    # bbc_gossip: 상세 미방문 → authors 없음, 통칭만으로 채워진다
    it = _html_item("bbc_gossip", {"title": "x"})
    assert select_journalist(it, {"tier": 4, "journalist_label": "BBC Gossip"}, REG) == "BBC Gossip"

def test_select_journalist_keeps_existing_payload_value():
    # 동적 소스 (x · fmkorea) 는 이미 journalist 를 실어 보낸다 — 그대로 존중
    it = _html_item("fmkorea", {"title": "x", "journalist": "온스테인",
                                "authors": ["Someone Else"]})
    assert select_journalist(it, {"credibility": "fmkorea"}, REG) == "온스테인"

def test_select_journalist_none_when_no_authors():
    assert select_journalist(_html_item("goal", {"title": "x"}), {"tier": 4}, REG) is None

def test_to_articles_promotes_tier_for_affiliated_journalist():
    raw = [_html_item("skysports", {"title": "Alvarez latest", "authors": ["Dharmesh Sheth"]})]
    sources = {"skysports": {"source_id": "skysports", "tier": 4, "outlet": "Sky Sports"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert arts[0].journalist == "Dharmesh Sheth"
    assert arts[0].tier == 1.5                       # min(1.5, 4) → 승격
    assert arts[0].confidence_score == 0.625

def test_to_articles_keeps_source_tier_for_unregistered_journalist():
    raw = [_html_item("football_london", {"title": "Alvarez latest", "authors": ["Raff Tindale"]})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "outlet": "football.london"}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert arts[0].journalist == "Raff Tindale" and arts[0].tier == 4.0

def test_to_articles_allowlist_drops_other_journalists():
    now = datetime.now(timezone.utc)
    raw = [
        RawItem(source_id="football_london", source_type="html", url="https://y.test/c1",
                fetched_at=now, raw_payload={"title": "Arsenal transfer latest",
                                             "authors": ["Tom Canton"]}),
        RawItem(source_id="football_london", source_type="html", url="https://y.test/c2",
                fetched_at=now, raw_payload={"title": "Arsenal deal news",
                                             "authors": ["Jake Stokes"]}),
    ]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert [a.url for a in arts] == ["https://y.test/c1"]
    assert stats["author_drop_count"] == 1

def test_to_articles_allowlist_coauthor_with_canton_survives():
    # select_journalist 가 등재 기자(Canton, credibility.yaml)를 우선 선정 → 공저 생존
    now = datetime.now(timezone.utc)
    raw = [RawItem(source_id="football_london", source_type="html", url="https://y.test/c3",
                   fetched_at=now, raw_payload={"title": "Arsenal news",
                                                "authors": ["Jake Stokes", "Tom Canton"]})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, _ = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1 and arts[0].journalist == "Tom Canton"

def test_to_articles_allowlist_drops_journalist_none():
    # 상세 fetch 실패 · 저자 부재 → Canton 확인 불가 → drop (seen 미기록 → 다음 회차 재시도)
    raw = [RawItem(source_id="football_london", source_type="html", url="https://y.test/c4",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal transfer latest"})]
    sources = {"football_london": {"source_id": "football_london", "tier": 4,
                                   "journalist_allowlist": ["Tom Canton"]}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert arts == [] and stats["author_drop_count"] == 1

def test_to_articles_no_allowlist_source_unaffected():
    raw = [RawItem(source_id="bbc_sport", source_type="html", url="https://x.test/b1",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "Arsenal sign Rice",
                                "authors": ["Alastair Telfer"]})]
    sources = {"bbc_sport": {"source_id": "bbc_sport", "tier": 1}}
    arts, stats = to_articles(raw, sources, seen={}, registry=REG)
    assert len(arts) == 1
    assert stats["author_drop_count"] == 0

from datetime import timedelta
from bullet_in.pipeline import _published

_FETCH = datetime(2026, 7, 19, 13, 36, tzinfo=timezone.utc)

def test_published_uses_payload_value():
    assert _published({"published": "2026-07-19T08:00:00+00:00"}, _FETCH) == \
        datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)

def test_published_fallback_is_fetched_at_not_now():
    assert _published({}, _FETCH) == _FETCH

def test_published_naive_value_treated_as_utc():
    assert _published({"published": "2026-07-19T08:00:00"}, _FETCH) == \
        datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc)

def test_published_future_beyond_1h_discarded_to_fetched_at():
    future = (_FETCH + timedelta(hours=2)).isoformat()
    assert _published({"published": future}, _FETCH) == _FETCH
