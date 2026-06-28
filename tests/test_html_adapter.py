import asyncio, respx, httpx
from pathlib import Path
from bullet_in.adapters.html import HtmlAdapter

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
