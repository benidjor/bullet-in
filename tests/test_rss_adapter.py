import asyncio
from pathlib import Path
from bullet_in.adapters.rss import RssAdapter

FEED = (Path(__file__).parent / "fixtures" / "sample_feed.xml").as_uri()

def test_rss_adapter_parses_items():
    a = RssAdapter(source_id="arsenal_official", feed_url=FEED)
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert items[0].raw_payload["title"] == "Arteta on win"
    assert items[0].url == "https://www.arsenal.com/news/arteta-win"
    assert items[0].source_type == "rss"
