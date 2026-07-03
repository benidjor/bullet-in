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

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

PAYWALLED_OUTLETS = {"The Athletic"}

OUTLET_MAP = {
    "디 애슬레틱": "The Athletic", "디애슬레틱": "The Athletic",
    "디 애슬래틱": "The Athletic", "디애슬래틱": "The Athletic",  # '래' 변종
    "The Athletic": "The Athletic",                              # 리터럴 명시
    "골닷컴": "Goal", "르퀴프": "L'Équipe",
}
_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]")

def parse_bracket(title: str) -> tuple[str | None, str | None, bool]:
    """fmkorea 말머리 [언론사] / [언론사 - 기자] / [언론사-독점] 파싱."""
    m = _BRACKET_RE.match(title)
    if not m:
        return None, None, False
    inner = m.group(1).strip()
    is_excl = "독점" in inner
    inner = inner.replace("독점", "")
    parts = re.split(r"\s*-\s*", inner, maxsplit=1)
    outlet = parts[0].strip(" -")
    journalist = parts[1].strip(" -") if len(parts) > 1 and parts[1].strip(" -") else None
    outlet = OUTLET_MAP.get(outlet, outlet)
    return (outlet or None), journalist, is_excl

def _extract_original_url(html: str, body_selector: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(body_selector)
    if el is None:
        return None
    # 1) 본문 평문 출처 URL 우선 (fmkorea 관례: 본문 끝). 여럿이면 마지막.
    plains = [m.group(0) for m in _URL_RE.finditer(el.get_text(" ", strip=True))
              if "fmkorea.com" not in m.group(0)]
    if plains:
        return plains[-1]
    # 2) 폴백: 외부 앵커 (기자 프로필일 수 있으나 평문 없을 때만)
    for a in el.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("http") and "fmkorea.com" not in href:
            return href
    return None

async def _fetch_og_image(client: httpx.AsyncClient, url: str) -> str | None:
    from bullet_in.adapters.meta import extract_og_image
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    return extract_og_image(r.text)

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
            from bullet_in.adapters.meta import extract_og_image, extract_article_body
            for title, url in matched:
                try:
                    rb = await c.get(url)
                    rb.raise_for_status()
                except httpx.HTTPError:
                    continue  # 글 fetch 실패 — 스킵, 배치 지속
                html = rb.text
                outlet, journalist, _excl = parse_bracket(title)
                orig = _extract_original_url(html, self.body_selector)
                if orig is None or outlet is None:
                    log.warning("fmkorea 원문/말머리 해소 실패 — 스킵 url=%s", url)
                    continue
                if outlet in PAYWALLED_OUTLETS:
                    # 유료 (디 애슬레틱): fmkorea 한국어 번역본 유지, 원문 og:image 만 시도
                    body = _body_text(html, self.body_selector)
                    image = await _fetch_og_image(c, orig)
                    lang = "ko"
                else:
                    # 무료: 원문 fetch 후 영어 본문·이미지 추출
                    try:
                        ro = await c.get(orig)
                        ro.raise_for_status()
                        body = extract_article_body(ro.text)
                        image = extract_og_image(ro.text)
                    except httpx.HTTPError:
                        body, image = "", None
                    lang = "en"
                out.append(RawItem(
                    source_id=self.source_id, source_type="html", url=orig,
                    fetched_at=now,
                    raw_payload={"title": title, "body": body, "lang": lang,
                                 "outlet": outlet, "journalist": journalist,
                                 "image_url": image}))
        return out
