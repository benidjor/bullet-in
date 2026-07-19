from __future__ import annotations
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
import re
import logging
import httpx
from bs4 import BeautifulSoup
from bullet_in.models import RawItem

log = logging.getLogger(__name__)

_BODY_MAX_CHARS = 2000

def _body_text(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(selector)
    return el.get_text(" ", strip=True)[:_BODY_MAX_CHARS] if el else ""

_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")

_SRL_RE = re.compile(r"document_srl=(\d+)")

def _post_url_from_href(href: str, base_url: str) -> str | None:
    """검색결과 앵커 href → 정규 글 URL. document_srl 우선 · /NNNNN 폴백 · 없으면 None."""
    m = _SRL_RE.search(href or "") or re.match(r"/(\d{6,})", href or "")
    return f"{base_url.rstrip('/')}/{m.group(1)}" if m else None

def _round_robin(per_kw: list[list[tuple[str, str]]], limit: int) -> list[tuple[str, str]]:
    """키워드별 결과 리스트를 라운드로빈으로 최대 limit개 뽑는다 (앞 키워드 독식 방지)."""
    out, i = [], 0
    while len(out) < limit and any(i < len(r) for r in per_kw):
        for r in per_kw:
            if i < len(r):
                out.append(r[i])
                if len(out) >= limit:
                    break
        i += 1
    return out

PAYWALLED_OUTLETS = {"The Athletic"}

OUTLET_MAP = {
    "디 애슬레틱": "The Athletic", "디애슬레틱": "The Athletic",
    "디 애슬래틱": "The Athletic", "디애슬래틱": "The Athletic",  # '래' 변종
    "The Athletic": "The Athletic",                              # 리터럴 명시
    "골닷컴": "Goal", "르퀴프": "L'Équipe", "레퀴프": "L'Équipe",  # '레' 변종
    "인디펜던트": "The Independent", "디 인디펜던트": "The Independent",
    "텔레그래프": "The Telegraph",
    "DM": "Daily Mail", "비사커": "BeSoccer",
    "타임스": "The Times", "타임즈": "The Times",
}

# 클럽 공홈 말머리는 수집하지 않는다 (2026-07-19) — 이용자가 타 구단 공홈 발표에도
# [공홈] 을 써서 Arsenal.com tier 0 오귀속이 발생했고, 아스날 공홈은 직수집
# (arsenal_api) 이 구 URL 중복 없이 official 태깅까지 커버한다.
_OFFICIAL_PREFIX = "공홈"
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

_REPOST_BLOCK_TEXT = "퍼가기가 금지된"

def _is_repost_blocked(html: str) -> bool:
    """퍼가기 금지 표식 감지 — 실측 DOM(2026-07-19): .rd_body 직하위 strong, 본문(.xe_content) 밖."""
    soup = BeautifulSoup(html, "html.parser")
    rb = soup.select_one(".rd_body")
    if rb is None:
        return False
    return any(_REPOST_BLOCK_TEXT in s.get_text()
               for s in rb.select("strong")
               if s.find_parent(class_="xe_content") is None)

_KST = timezone(timedelta(hours=9))
_POST_DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}):(\d{2})")

def _post_published(html: str) -> datetime | None:
    """fmkorea 게시 시각 — 실측 (2026-07-20) `.rd_hd .date` 'YYYY.MM.DD HH:MM' KST → UTC.
    목록 위젯의 .date 다중 매칭 (실측 7개) 이 있어 반드시 .rd_hd 스코프."""
    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(".rd_hd .date")
    m = _POST_DATE_RE.search(el.get_text(strip=True)) if el else None
    if not m:
        return None
    y, mo, d, h, mi = map(int, m.groups())
    return datetime(y, mo, d, h, mi, tzinfo=_KST).astimezone(timezone.utc)

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
    def __init__(self, source_id: str, search_url: str, search_keywords: list[dict],
                 item_selector: str = "a.hx",
                 base_url: str = "https://www.fmkorea.com",
                 body_selector: str = ".xe_content", max_posts: int = 15):
        self.source_id = source_id
        self.search_url = search_url            # {keyword} · {target} 자리표시 포함
        self.search_keywords = search_keywords
        self.item_selector = item_selector
        self.base_url = base_url
        self.body_selector = body_selector
        self.max_posts = max_posts

    async def _discover(self, c: httpx.AsyncClient) -> list[tuple[str, str]]:
        """키워드별 검색 → a.hx 파싱 → 정규 글 URL. 키워드별 결과를 라운드로빈으로 max_posts 배분."""
        per_kw, seen = [], set()
        for kw in self.search_keywords:
            url = self.search_url.format(keyword=quote(kw["keyword"]), target=kw["target"])
            try:
                r = await c.get(url)
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    log.warning("fmkorea 검색 429(rate limit) kw=%s — 스킵", kw["keyword"])
                else:
                    log.warning("fmkorea 검색 HTTP %s kw=%s — 스킵", e.response.status_code, kw["keyword"])
                continue
            except httpx.HTTPError as e:
                log.warning("fmkorea 검색 실패 kw=%s err=%s — 스킵", kw["keyword"], e)
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for a in soup.select(self.item_selector):
                title = a.get_text(strip=True)
                post_url = _post_url_from_href(a.get("href", ""), self.base_url)
                if not title or not post_url or post_url in seen:
                    continue
                seen.add(post_url)
                results.append((title, post_url))
            per_kw.append(results)
        return _round_robin(per_kw, self.max_posts)

    async def _process(self, c: httpx.AsyncClient,
                       matched: list[tuple[str, str]]) -> list[RawItem]:
        """글별 fetch → 말머리 파싱 → 페이월/무료 라우팅 → RawItem."""
        from bullet_in.adapters.meta import (extract_og_image, extract_article_body,
                                             extract_body_images, extract_published_at)
        now, out = datetime.now(timezone.utc), []
        for title, url in matched:
            pub: tuple | None = None
            try:
                rb = await c.get(url)
                rb.raise_for_status()
            except httpx.HTTPError:
                continue  # 글 fetch 실패 — 스킵, 배치 지속
            html = rb.text
            outlet, journalist, _excl = parse_bracket(title)
            if outlet and _OFFICIAL_PREFIX in outlet:
                log.info("fmkorea [공홈] 말머리 drop — 직수집 경로가 커버 url=%s", url)
                continue
            orig = _extract_original_url(html, self.body_selector)
            if orig is None or outlet is None:
                log.warning("fmkorea 원문/말머리 해소 실패 — 스킵 url=%s", url)
                continue
            if outlet in PAYWALLED_OUTLETS:
                if _is_repost_blocked(html):
                    # §9.1 ②: 퍼가기 금지 + 페이월 → 헤드라인 + 출처 + 링크만 (본문·게시글 이미지 미복제)
                    log.info("fmkorea 퍼가기 금지 + 페이월 — 헤드라인만 저장 url=%s", url)
                    body, images = "", []
                else:
                    body = _body_text(html, self.body_selector)
                    # 게시글 이미지 ≈ 원문 기사 이미지 재게재 (spec 확정 결정)
                    images = extract_body_images(html, self.body_selector, base_url=url)
                image = await _fetch_og_image(c, orig)
                lang = "ko"
            else:
                try:
                    ro = await c.get(orig)
                    ro.raise_for_status()
                    body = extract_article_body(ro.text)
                    image = extract_og_image(ro.text)
                    images = extract_body_images(ro.text, base_url=orig)
                    pub = extract_published_at(ro.text)
                except httpx.HTTPError:
                    body, image, images = "", None, []
                lang = "en"
            if pub is None:
                post_dt = _post_published(html)
                pub = (post_dt, "time") if post_dt else None
            extra = ({"published": pub[0].isoformat(), "published_precision": pub[1]}
                     if pub else {})
            out.append(RawItem(
                source_id=self.source_id, source_type="html", url=orig,
                fetched_at=now,
                raw_payload={"title": title, "body": body, "lang": lang,
                             "outlet": outlet, "journalist": journalist,
                             "image_url": image, "images": images, **extra}))
        return out

    async def fetch(self) -> list[RawItem]:
        headers = {"User-Agent": "Mozilla/5.0 bullet-in/0.1"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers) as c:
            matched = await self._discover(c)
            return await self._process(c, matched)
