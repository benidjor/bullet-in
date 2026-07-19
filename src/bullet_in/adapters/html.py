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
                 body_selector: str | None = None, title_selector: str | None = None,
                 thumbnail_only: bool = False):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.base_url = base_url or list_url
        self.body_selector = body_selector
        self.title_selector = title_selector
        self.thumbnail_only = thumbnail_only
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
    async def fetch(self) -> list[RawItem]:
        from bullet_in.adapters.meta import (extract_og_image, extract_body_images,
                                             extract_authors, extract_published_at)
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
                if self.title_selector:
                    el = a.select_one(self.title_selector)
                    if el is None:
                        continue  # 헤드라인 sub-요소 없음 → 제목 없는 항목 적재 방지
                    title = el.get_text(strip=True)
                else:
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
                        payload["images"] = extract_body_images(
                            rb.text, self.body_selector, base_url=url)
                        payload["authors"] = extract_authors(rb.text)
                        pub = extract_published_at(rb.text)
                        if pub:
                            payload["published"] = pub[0].isoformat()
                            payload["published_precision"] = pub[1]
                    except httpx.HTTPError:
                        payload["body"] = ""  # 본문 실패 — 제목만 유지, 다음 회차 재시도
                elif self.thumbnail_only:
                    # 경량 상세 방문 — og:image 만 (본문 · 저자 미추출 = 번역 비용 무변경)
                    try:
                        rb = await c.get(url)
                        rb.raise_for_status()
                        payload["image_url"] = extract_og_image(rb.text)
                        pub = extract_published_at(rb.text)
                        if pub:
                            payload["published"] = pub[0].isoformat()
                            payload["published_precision"] = pub[1]
                    except httpx.HTTPError:
                        pass  # 상세 실패 — 제목만 적재, 놓친 이미지는 백필 몫
                out.append(RawItem(source_id=self.source_id, source_type="html",
                                   url=url, fetched_at=now, raw_payload=payload))
        return out
