from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

class HtmlAdapter:
    source_type = "html"
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, title_contains: str | None = None):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.base_url = base_url or list_url
        self.title_contains = title_contains.lower() if title_contains else None
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(self.list_url)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        now, out, seen = datetime.now(timezone.utc), [], set()
        for a in soup.select(self.item_selector):
            href = a.get("href")
            if not href:
                continue
            url = urljoin(self.base_url, href)
            if url in seen:
                continue
            seen.add(url)
            title = a.get_text(strip=True)
            if self.title_contains and self.title_contains not in title.lower():
                continue
            out.append(RawItem(source_id=self.source_id, source_type="html", url=url,
                               fetched_at=now, raw_payload={"title": title}))
        return out
