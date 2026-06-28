from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
import re
import logging
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

log = logging.getLogger(__name__)

_BODY_MAX_CHARS = 2000

def _matches(title: str, keywords: list[str]) -> bool:
    t = title.lower()
    return any(k.lower() in t for k in keywords)

def _body_text(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True)[:_BODY_MAX_CHARS] if el else ""

_REPOST_MARK = "퍼가기가 금지된 글입니다"
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

def _is_repost_blocked(html: str) -> bool:
    return _REPOST_MARK in html

def _extract_original_url(html: str, body_selector: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(body_selector)
    if el is None:
        return None
    # href 우선, 없으면 본문 텍스트의 평문 URL
    for a in el.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("http") and "fmkorea.com" not in href:
            return href
    for m in _URL_RE.finditer(el.get_text(" ", strip=True)):
        if "fmkorea.com" not in m.group(0):
            return m.group(0)
    return None

async def _fetch_og_description(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    tag = (soup.find("meta", property="og:description")
           or soup.find("meta", attrs={"name": "description"}))
    content = tag.get("content") if tag else None
    return content.strip() if content else None

class FmkoreaAdapter:
    source_type = "html"
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 keywords: list[str], base_url: str | None = None,
                 body_selector: str = ".xe_content", max_posts: int = 10):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.keywords = keywords
        self.base_url = base_url or list_url
        self.body_selector = body_selector
        self.max_posts = max_posts

    async def fetch(self) -> list[RawItem]:
        now, out, seen = datetime.now(timezone.utc), [], set()
        # fmkorea는 봇 차단 회피를 위해 Mozilla prefix 포함
        headers = {"User-Agent": "Mozilla/5.0 bullet-in/0.1"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers) as c:
            try:
                r = await c.get(self.list_url)
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    log.warning("fmkorea 리스트 429(rate limit) — 이번 회차 스킵")
                    return []
                raise
            soup = BeautifulSoup(r.text, "html.parser")
            matched = []
            for a in soup.select(self.item_selector):
                title = a.get_text(strip=True)
                href = a.get("href")
                if not href or not title or not _matches(title, self.keywords):
                    continue
                url = urljoin(self.base_url, href)
                if url in seen:
                    continue
                seen.add(url)
                matched.append((title, url))
                if len(matched) >= self.max_posts:
                    break
            for title, url in matched:
                try:
                    rb = await c.get(url)
                    rb.raise_for_status()
                except httpx.HTTPError:
                    continue  # 해당 글만 스킵, 배치 지속
                html = rb.text
                if _is_repost_blocked(html):
                    orig = _extract_original_url(html, self.body_selector)
                    desc = await _fetch_og_description(c, orig) if orig else None
                    if orig and desc:                 # 분기①: 원문 대체
                        item_url, body = orig, desc
                    else:                             # 분기②: 헤드라인만
                        item_url, body = orig or url, ""
                else:                                 # 현행: fmkorea 본문 요약
                    item_url = url
                    body = _body_text(html, self.body_selector)
                out.append(RawItem(
                    source_id=self.source_id, source_type="html", url=item_url,
                    fetched_at=now,
                    raw_payload={"title": title, "body": body, "lang": "ko"}))
        return out
