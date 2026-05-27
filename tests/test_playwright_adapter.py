import asyncio
from pathlib import Path
from bullet_in.adapters.playwright_news import PlaywrightAdapter

PAGE = (Path(__file__).parent / "fixtures" / "js_list.html").as_uri()

def test_playwright_adapter_reads_js_rendered_links():
    a = PlaywrightAdapter(source_id="goal", list_url=PAGE,
                          item_selector="a[data-testid='article-link']")
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].url == "https://goal.test/n/1"
    assert items[0].raw_payload["title"] == "Late goal"
    assert items[0].source_type == "playwright"
