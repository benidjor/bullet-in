import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from bullet_in.adapters.rss import RssAdapter
from bullet_in.quality import list_signature

FIX = Path(__file__).parent / "fixtures"
FEED = "https://feeds.test/arsenal/rss.xml"
BBC = (FIX / "bbc_arsenal_feed.xml").read_bytes()
DEAL = ("https://www.bbc.co.uk/sport/football/articles/ckd68e40ze3jo"
        "?at_medium=RSS&at_campaign=rss")
RAMSDALE = ("https://www.bbc.co.uk/sport/football/articles/cvgy802y2n9o"
            "?at_medium=RSS&at_campaign=rss")
LOAN = ("https://www.bbc.co.uk/sport/football/articles/crp3k23nkl8go"
        "?at_medium=RSS&at_campaign=rss")
KW = ["deal", "loan", "agree"]


def _mini(items: str) -> bytes:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'.encode()


@respx.mock
def test_rss_adapter_parses_items():
    # 종전 테스트 (공식 소스 피드 픽스처) — 받기를 httpx 로 옮긴 뒤에도 같은 값
    respx.get(FEED).mock(return_value=httpx.Response(
        200, content=(FIX / "sample_feed.xml").read_bytes()))
    items = asyncio.run(RssAdapter(source_id="arsenal_official", feed_url=FEED).fetch())
    assert len(items) == 1
    assert items[0].raw_payload["title"] == "Arteta on win"
    assert items[0].url == "https://www.arsenal.com/news/arteta-win"
    assert items[0].source_type == "rss"


@respx.mock
def test_rss_filters_by_keyword_and_records_funnel():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    items = asyncio.run(a.fetch())
    assert [it.raw_payload["title"] for it in items] == [
        "Arteta agrees new deal with champions Arsenal",
        "Arsenal open to Dowman loan in right circumstances"]
    assert [it.url for it in items] == [DEAL, LOAN]       # 주소 정규화는 파이프라인 몫
    assert a.funnel == {"entries": 3, "deduped": 3, "passed": 2,
                        "list_sig": list_signature([DEAL, RAMSDALE, LOAN])}


@respx.mock
def test_rss_list_signature_covers_items_the_keywords_drop():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    a = RssAdapter("bbc_sport", FEED, title_contains=["nothing-matches"])
    assert asyncio.run(a.fetch()) == []
    assert a.funnel["passed"] == 0
    assert a.funnel["list_sig"] == list_signature([DEAL, RAMSDALE, LOAN])


@respx.mock
def test_rss_carries_feed_published_time():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    items = asyncio.run(RssAdapter("bbc_sport", FEED, title_contains=KW).fetch())
    assert items[0].raw_payload["published"] == "2026-09-22T11:48:23+00:00"
    assert items[0].raw_payload["published_precision"] == "time"


@respx.mock
def test_rss_fetches_article_body_when_selector_set():
    respx.get(FEED).mock(return_value=httpx.Response(200, content=BBC))
    respx.get(DEAL).mock(return_value=httpx.Response(
        200, text='<html><head><meta property="og:image" content="https://img.test/a.jpg">'
                  '</head><body><article><p>Arteta has agreed a new deal.</p></article></body></html>'))
    respx.get(LOAN).mock(return_value=httpx.Response(500))
    items = asyncio.run(RssAdapter("bbc_sport", FEED, title_contains=KW,
                                   body_selector="article").fetch())
    assert items[0].raw_payload["body"] == "Arteta has agreed a new deal."
    assert items[0].raw_payload["image_url"] == "https://img.test/a.jpg"
    # 상세 실패 — 제목 · 피드 발행 시각은 남고 본문만 빈다
    assert items[1].raw_payload["body"] == ""
    assert items[1].raw_payload["title"] == "Arsenal open to Dowman loan in right circumstances"
    assert items[1].raw_payload["published"] == "2026-09-18T21:30:38+00:00"


@respx.mock
def test_rss_http_error_raises_and_leaves_no_funnel():
    respx.get(FEED).mock(return_value=httpx.Response(503))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(a.fetch())
    assert a.funnel == {}


@respx.mock
def test_rss_non_xml_page_yields_zero_entries():
    # 200 인데 피드가 아닌 페이지 — 예외 없이 0개, SLO-5 가 no_entries 로 본다
    respx.get(FEED).mock(return_value=httpx.Response(200, text="<html><body>Moved</body></html>"))
    a = RssAdapter("bbc_sport", FEED, title_contains=KW)
    assert asyncio.run(a.fetch()) == []
    assert a.funnel == {"entries": 0, "deduped": 0, "passed": 0, "list_sig": ""}


@respx.mock
def test_rss_skips_missing_link_dedups_and_counts_untitled():
    feed = _mini("<item><title>No link deal</title></item>"
                 "<item><title>Twice deal</title><link>https://a.test/1</link></item>"
                 "<item><title>Twice deal</title><link>https://a.test/1</link></item>"
                 "<item><link>https://a.test/2</link></item>")
    respx.get(FEED).mock(return_value=httpx.Response(200, content=feed))
    a = RssAdapter("bbc_sport", FEED, title_contains=["deal"])
    items = asyncio.run(a.fetch())
    assert [it.url for it in items] == ["https://a.test/1"]
    assert a.funnel["entries"] == 4
    assert a.funnel["deduped"] == 2          # 링크 없는 항목은 빠지고 같은 링크는 한 번
    assert a.funnel["passed"] == 1           # 제목 없는 항목은 키워드에 못 닿는다
    assert a.funnel["list_sig"] == list_signature(["https://a.test/1", "https://a.test/2"])
