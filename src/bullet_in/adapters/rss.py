from __future__ import annotations
from datetime import datetime, timezone
import asyncio, feedparser
from bullet_in.models import RawItem

class RssAdapter:
    source_type = "rss"
    def __init__(self, source_id: str, feed_url: str):
        self.source_id = source_id
        self.feed_url = feed_url
    async def fetch(self) -> list[RawItem]:
        parsed = await asyncio.to_thread(feedparser.parse, self.feed_url)
        now = datetime.now(timezone.utc)
        out: list[RawItem] = []
        for e in parsed.entries:
            out.append(RawItem(
                source_id=self.source_id, source_type="rss", url=e.link,
                fetched_at=now,
                raw_payload={"title": e.title,
                             "published": e.get("published"),
                             "summary": e.get("summary", "")}))
        return out
