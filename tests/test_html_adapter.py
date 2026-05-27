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
