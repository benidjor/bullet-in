import asyncio, respx, httpx
from pathlib import Path
from bullet_in.adapters.html import HtmlAdapter
from bullet_in.adapters.meta import extract_og_image  # noqa: F401 (의존 확인)

HTML = (Path(__file__).parent / "fixtures" / "list.html").read_text()

@respx.mock
def test_html_adapter_extracts_matching_links():
    respx.get("https://bbc.test/arsenal").mock(return_value=httpx.Response(200, text=HTML))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://bbc.test/arsenal",
                    item_selector="a[href*='/sport/football/articles/']",
                    base_url="https://bbc.test")
    items = asyncio.run(a.fetch())
    assert len(items) == 2
    assert items[0].url == "https://bbc.test/sport/football/articles/abc123"
    assert items[0].raw_payload["title"] == "Saka shines"
    assert items[0].source_type == "html"

@respx.mock
def test_html_adapter_filters_by_title_contains():
    html = ('<a class="card" href="/a">Gabriel signs new deal</a>'
            '<a class="card" href="/b">Match preview vs Spurs</a>'
            '<a class="card" href="/c">Saka SIGNS contract extension</a>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="arsenal_official", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    title_contains="sign")  # 대소문자 무시, '재계약(signs ... extension)'도 포함
    titles = [it.raw_payload["title"] for it in asyncio.run(a.fetch())]
    assert titles == ["Gabriel signs new deal", "Saka SIGNS contract extension"]

@respx.mock
def test_html_adapter_filters_by_keyword_list():
    html = ('<a class="card" href="/a">Arsenal agree deal for Gyokeres</a>'
            '<a class="card" href="/b">Match preview vs Spurs</a>'
            '<a class="card" href="/c">Saka injury update</a>'
            '<a class="card" href="/d">Rice loan talks collapse</a>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    title_contains=["transfer", "deal", "loan", "talks"])
    titles = [it.raw_payload["title"] for it in asyncio.run(a.fetch())]
    assert titles == ["Arsenal agree deal for Gyokeres", "Rice loan talks collapse"]

@respx.mock
def test_html_adapter_no_filter_returns_all():
    html = ('<a class="card" href="/a">Anything one</a>'
            '<a class="card" href="/b">Anything two</a>')
    respx.get("https://a.test/all").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/all",
                    item_selector="a.card", base_url="https://a.test")
    assert len(asyncio.run(a.fetch())) == 2

@respx.mock
def test_html_adapter_fetches_body_and_image_when_selector_set():
    list_html = ('<a class="card" href="/a">Arsenal sign Gyokeres</a>')
    detail = ('<html><head><meta property="og:image" content="https://img.test/g.jpg">'
              '</head><body><div class="article-body"><p>Deal done for 60m.</p>'
              '<p>Five-year contract.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert "Deal done for 60m." in items[0].raw_payload["body"]
    assert items[0].raw_payload["image_url"] == "https://img.test/g.jpg"

@respx.mock
def test_html_adapter_keeps_title_when_detail_fetch_fails():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload.get("body", "") == ""
    assert items[0].raw_payload["title"] == "Arsenal sign Gyokeres"

@respx.mock
def test_html_adapter_title_selector_extracts_clean_headline_and_scopes():
    # content-post(임베드 인라인 링크)는 item_selector 스코프 밖 → 제외,
    # main-content 카드만 수집하고 LinkPostHeadline 헤드라인만 추출(timestamp·visually-hidden 제거)
    html = (
        '<div data-testid="content-post">'
        '<a href="/sport/football/articles/junk">Want more transfer stories? Read gossip column</a>'
        '</div>'
        '<div data-testid="main-content">'
        '<a href="/sport/football/articles/abc">'
        '<span class="ssrcss-1-Timestamp">21:19 BST 29 June</span>'
        '<span class="visually-hidden ssrcss-2-VisuallyHidden">Bournemouth reject Arsenal interest, published at 21:19</span>'
        '<span class="ssrcss-3-LinkPostHeadline">Bournemouth reject Arsenal interest</span>'
        '</a>'
        '</div>'
    )
    respx.get("https://bbc.test/arsenal").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://bbc.test/arsenal",
                    item_selector="[data-testid='main-content'] a[href*='/sport/football/articles/']",
                    base_url="https://bbc.test",
                    title_selector="span[class*='LinkPostHeadline']")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].url == "https://bbc.test/sport/football/articles/abc"
    assert items[0].raw_payload["title"] == "Bournemouth reject Arsenal interest"


@respx.mock
def test_html_adapter_skips_item_when_title_selector_not_found():
    html = (
        '<div data-testid="main-content">'
        '<a href="/sport/football/articles/abc"><span class="other">no headline span</span></a>'
        '</div>'
    )
    respx.get("https://bbc.test/arsenal").mock(return_value=httpx.Response(200, text=html))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://bbc.test/arsenal",
                    item_selector="[data-testid='main-content'] a[href*='/sport/football/articles/']",
                    base_url="https://bbc.test",
                    title_selector="span[class*='LinkPostHeadline']")
    assert asyncio.run(a.fetch()) == []

@respx.mock
def test_html_adapter_collects_body_images():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><body><div class="article-body"><p>One.</p>'
              '<img src="https://img.test/1.jpg"><p>Two.</p>'
              '<img src="https://img.test/2.jpg"></div>'
              '<img src="https://img.test/outside.jpg"></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == [
        "https://img.test/1.jpg", "https://img.test/2.jpg"]

@respx.mock
def test_html_adapter_collects_authors_from_detail():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><head><script type="application/ld+json">'
              '{"@type":"NewsArticle","author":[{"@type":"Person","name":"Alastair Telfer"},'
              '{"@type":"Person","name":"Sami Mokbel"}]}</script></head>'
              '<body><div class="article-body"><p>Deal done.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["authors"] == ["Alastair Telfer", "Sami Mokbel"]

@respx.mock
def test_html_adapter_authors_absent_when_detail_fetch_fails():
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload.get("authors", []) == []

@respx.mock
def test_html_adapter_thumbnail_only_fetches_og_image_only():
    list_html = '<a class="card" href="/a">Gossip roundup</a>'
    detail = ('<html><head><meta property="og:image" content="https://img.test/t.jpg">'
              '</head><body><article><p>Body text.</p>'
              '<script type="application/ld+json">{"@type":"NewsArticle",'
              '"author":{"@type":"Person","name":"Some Writer"}}</script>'
              '</article></body></html>')
    respx.get("https://a.test/gossip").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/gossip",
                    item_selector="a.card", base_url="https://a.test",
                    thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload["image_url"] == "https://img.test/t.jpg"
    # 본문 · 인라인 이미지 · 저자는 추출하지 않는다 (spec §3.3 — 번역 비용 무변경)
    assert "body" not in items[0].raw_payload
    assert "images" not in items[0].raw_payload
    assert "authors" not in items[0].raw_payload

@respx.mock
def test_html_adapter_thumbnail_only_keeps_title_on_detail_failure():
    list_html = '<a class="card" href="/a">Gossip roundup</a>'
    respx.get("https://a.test/gossip").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(500))
    a = HtmlAdapter(source_id="bbc_gossip", list_url="https://a.test/gossip",
                    item_selector="a.card", base_url="https://a.test",
                    thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload["title"] == "Gossip roundup"
    assert "image_url" not in items[0].raw_payload

@respx.mock
def test_html_adapter_body_selector_takes_precedence_over_thumbnail_only():
    # body_selector 가 있으면 풀 수집 경로 그대로 — thumbnail_only 는 무시 (spec §3.3)
    list_html = '<a class="card" href="/a">Arsenal sign Gyokeres</a>'
    detail = ('<html><head><meta property="og:image" content="https://img.test/g.jpg">'
              '</head><body><div class="article-body"><p>Deal done.</p></div></body></html>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=list_html))
    respx.get("https://a.test/a").mock(return_value=httpx.Response(200, text=detail))
    a = HtmlAdapter(source_id="bbc_sport", list_url="https://a.test/news",
                    item_selector="a.card", base_url="https://a.test",
                    body_selector=".article-body", thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["body"] == "Deal done."
    assert items[0].raw_payload["image_url"] == "https://img.test/g.jpg"

ART_WITH_PUB = ('<html><head><script type="application/ld+json">'
                '{"@type":"NewsArticle","datePublished":"2026-07-19T10:00:00Z"}'
                '</script></head><body><article><p>Body text.</p></article></body></html>')

@respx.mock
def test_html_body_path_extracts_published():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(200, text=ART_WITH_PUB))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", body_selector="article")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["published"] == "2026-07-19T10:00:00+00:00"
    assert items[0].raw_payload["published_precision"] == "time"

@respx.mock
def test_html_thumbnail_only_path_extracts_published():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(200, text=ART_WITH_PUB))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", thumbnail_only=True)
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["published"] == "2026-07-19T10:00:00+00:00"

@respx.mock
def test_html_no_published_leaves_payload_clean():
    respx.get("https://ex.test/list").mock(return_value=httpx.Response(
        200, text='<a class="i" href="/a1">Arsenal sign</a>'))
    respx.get("https://ex.test/a1").mock(return_value=httpx.Response(
        200, text="<html><body><article><p>x</p></article></body></html>"))
    a = HtmlAdapter(source_id="s", list_url="https://ex.test/list",
                    item_selector="a.i", body_selector="article")
    items = asyncio.run(a.fetch())
    assert "published" not in items[0].raw_payload
