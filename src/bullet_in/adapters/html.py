from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

class HtmlAdapter:
    source_type = "html"
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, title_contains: str | list[str] | None = None,
                 body_selector: str | None = None):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.base_url = base_url or list_url
        self.body_selector = body_selector
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
    async def fetch(self) -> list[RawItem]:
        from bullet_in.adapters.meta import extract_og_image
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(self.list_url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            now, matched, seen = datetime.now(timezone.utc), [], set()
            for a in soup.select(self.item_selector):
                href = a.get("href")
                if not href:
                    continue
                url = urljoin(self.base_url, href)
                if url in seen:
                    continue
                seen.add(url)
                title = a.get_text(strip=True)
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
                matched.append((title, url))
            out = []
            for title, url in matched:
                payload = {"title": title}
                if self.body_selector:
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        el = BeautifulSoup(rb.text, "html.parser").select_one(self.body_selector)
                        payload["body"] = el.get_text(" ", strip=True) if el else ""
                        payload["image_url"] = extract_og_image(rb.text)
                    except httpx.HTTPError:
                        payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
                out.append(RawItem(source_id=self.source_id, source_type="html",
                                   url=url, fetched_at=now, raw_payload=payload))
        return out
