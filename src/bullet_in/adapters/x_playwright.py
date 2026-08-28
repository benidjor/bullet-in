from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime
from bullet_in.models import RawItem
from playwright.async_api import async_playwright

_TWEET_JS = """
els => els.map(a => {
  const t = a.querySelector('[data-testid="tweetText"]');
  const time = a.querySelector('time');
  const link = a.querySelector('a[href*="/status/"]');
  const img = a.querySelector('[data-testid="tweetPhoto"] img');
  const card = a.querySelector('[data-testid="card.wrapper"]');
  const ca = card ? card.querySelector('a[href]') : null;
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  const am = href ? href.match(/^\\/([A-Za-z0-9_]+)\\/status\\//) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    author: am ? am[1] : '',
    image_url: img ? img.src : null,
    card_href: ca ? ca.getAttribute('href') : ''
  };
})
"""

_JOURN_JS = """
els => els.map(a => {
  const t = a.querySelector('[data-testid="tweetText"]');
  const time = a.querySelector('time');
  const card = a.querySelector('[data-testid="card.wrapper"]');
  const ca = card ? card.querySelector('a[href]') : null;
  const link = a.querySelector('a[href*="/status/"]');
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    card_href: ca ? ca.getAttribute('href') : ''
  };
})
"""

_CITE_RE = re.compile(r"\[\s*@([A-Za-z0-9_]{1,15})\s*\]")
# afcstuff 는 인용을 대괄호로만 쓰지 않는다 (2026-07-30 실측: 라이브 30건 중 4건 유실).
# 기자 발언 relay 는 멘션이 줄 단위로 서고 콜론이 따르거나 이름 뒤 괄호에 핸들이 온다
#   '@JacobsBen\n: "…"' · 'Bruno Andrade (\n@ESPNBrasil\n): "…"'
# 콜론 바로 앞까지 공백 · 개행 · 닫는 괄호만 허용해 문장 중간 멘션을 오탐하지 않는다.
_COLON_CITE_RE = re.compile(r"@([A-Za-z0-9_]{1,15})\s*\)?\s*:")


def cited_handles(text: str) -> list[str]:
    """트윗 본문에서 인용된 핸들 — 대괄호 형태 우선, 없으면 콜론 형태.

    대괄호가 있으면 그것만 쓴다 (기존 동작 무변경). 둘을 합치면 같은 트윗에서
    본문 중간 멘션이 대표 기자를 밀어내 tier 가 오귀속될 수 있다."""
    for rule in (_CITE_RE, _COLON_CITE_RE):
        found = rule.findall(text or "")
        if found:
            return ["@" + h for h in found]
    return []


def _accumulate_tweets(acc: dict[str, dict], batch: list[dict]) -> None:
    """스크롤 스냅샷(batch)을 status_id 기준으로 acc에 누적. 이미 본 것은 무시, 삽입 순서 보존.

    DOM 가상화로 화면 밖 트윗이 스냅샷에서 사라져도 acc에 남으므로 수율이 단조 증가한다.
    """
    for t in batch:
        sid = t.get("status_id")
        if sid and sid not in acc:
            acc[sid] = t


def _x_cookies(cookies_path: str) -> list[dict]:
    """x_cookies.json({auth_token, ct0}) → Playwright 쿠키 목록(.x.com · .twitter.com). SP2 재사용."""
    if not os.path.exists(cookies_path):
        raise FileNotFoundError(f"X 쿠키 파일 없음: {cookies_path}")
    with open(cookies_path, encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for dom in (".x.com", ".twitter.com"):
        for name in ("auth_token", "ct0"):
            if raw.get(name):
                out.append({"name": name, "value": raw[name],
                            "domain": dom, "path": "/"})
    return out


async def _scroll_collect(page, js, max_items):
    """스크롤하며 status_id로 누적 (SP1.5 로직 일반화 · afcstuff · 기자 공용)."""
    acc: dict[str, dict] = {}
    stagnant = 0
    for _ in range(12):
        batch = await page.eval_on_selector_all('article[data-testid="tweet"]', js)
        before = len(acc)
        _accumulate_tweets(acc, batch)
        if len(acc) >= max_items:
            break
        if len(acc) == before:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(800)
    return list(acc.values())[:max_items]


class XPlaywrightAdapter:
    source_type = "x"

    def __init__(self, source_id: str, handle: str, max_tweets: int = 20,
                 cookies_path: str = "x_cookies.json", backtrack_config_path: str | None = None,
                 self_source: bool = False, own_source_handles: list[str] | None = None):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path
        self.backtrack_config_path = backtrack_config_path
        self.self_source = self_source
        self.own_source_handles = own_source_handles or []

    async def fetch(self) -> list[RawItem]:
        from datetime import timezone
        import logging
        log = logging.getLogger(__name__)
        cookies = _x_cookies(self.cookies_path)
        bt = None
        if self.backtrack_config_path:
            from bullet_in.adapters.x_backtrack import load_backtrack_config
            bt = load_backtrack_config(self.backtrack_config_path)
        now = datetime.now(timezone.utc)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            await page.goto(f"https://x.com/{self.handle}", wait_until="domcontentloaded")
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            raw_tweets = await _scroll_collect(page, _TWEET_JS, self.max_tweets)
            items = self._parse_tweets(raw_tweets, now)
            timelines = {}
            if bt:
                timelines = await self._scrape_journalists(ctx, items, bt, log)
            await browser.close()
        if self.self_source:
            items = await resolve_card_urls(items, log)
        if bt:
            from bullet_in.adapters.x_backtrack import backtrack_promote
            items = await backtrack_promote(items, timelines, bt)
        return items

    async def _scrape_journalists(self, ctx, items, cfg, log):
        skip = {h.lower() for h in cfg.get("skip_handles", [])}
        depth = cfg.get("params", {}).get("timeline_depth", 25)
        cap = cfg.get("params", {}).get("max_journalists", 15)
        handles, seen = [], set()
        for it in items:
            h = (it.raw_payload.get("journalist") or "").lstrip("@")
            hl = h.lower()
            if h and hl not in seen and hl not in skip:
                seen.add(hl)
                handles.append(h)
        if len(handles) > cap:
            log.info("backtrack 기자 상한 초과 %d → %d (드롭 로깅)", len(handles), cap)
            handles = handles[:cap]
        timelines = {}
        for h in handles:
            page = None
            try:
                page = await ctx.new_page()
                await page.goto(f"https://x.com/{h}", wait_until="domcontentloaded")
                await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
                timelines[h.lower()] = await _scroll_collect(page, _JOURN_JS, depth)
            except Exception as e:  # 소스 격리 : 한 핸들 실패는 그 인용만 2순위로 강등
                log.warning("backtrack 타임라인 실패 handle=%s err=%s", h, e)
            finally:
                if page is not None:
                    await page.close()
        return timelines

    def _parse_tweets(self, raw_tweets: list[dict], now: datetime) -> list[RawItem]:
        """파서 선택 — self_source 면 본인 트윗 경로, 아니면 기존 인용 경로 (spec §5.2)."""
        if self.self_source:
            return parse_self_tweets(self.source_id, self.handle, raw_tweets, now)
        return parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets, now,
                                     own_source_handles=self.own_source_handles)


# 큰따옴표 (곧은 것 · 둥근 것) — 기자의 '말' 을 옮긴 트윗의 표지.
_QUOTED_RE = re.compile(r'["\u201c\u201d]')


def is_commentary(text: str) -> bool:
    """기자의 말을 옮긴 트윗인가 (속보 전달과 구분) — 큰따옴표 유무로 가른다.

    실측 (2026-08-28 · 온스테인 인용 16건) 에서 둘이 깨끗이 갈렸다. 속보 12건은
    afcstuff 가 원문을 다시 쓴 것이라 따옴표가 없고, 논평 4건은 방송 · 팟캐스트
    발언을 옮긴 것이라 전부 따옴표 안에 들어 있다."""
    return bool(_QUOTED_RE.search(text or ""))


def parse_afcstuff_tweets(source_id: str, handle: str,
                          raw_tweets: list[dict], now: datetime,
                          own_source_handles: list[str] | None = None) -> list[RawItem]:
    """DOM에서 뽑은 트윗 dict → 인용 있는 것만 RawItem.

    인용 형태는 둘이다 — 대괄호 (`[ @handle ]`) 와 콜론 (`@handle : "…"`).
    인용 주체가 없는 트윗 (생일 축하 · 훈련 사진 · 기자회견 발언) 은 기자 tier 를
    매길 근거가 없어 제외한다.

    own_source_handles 는 우리가 그 기자의 계정을 따로 수집하는 핸들이다. 그런
    기자의 **속보** 인용은 원문이 다른 경로로 이미 들어오므로 같은 소식이 두 행이
    된다 (실측: 온스테인 속보 12건 전량이 x_ornstein 에도 있었다). 그래서 속보만
    빼고 **논평은 남긴다** — 논평은 본인이 트윗한 적이 없어 여기서만 들어온다."""
    own = {h.lstrip("@").lower() for h in (own_source_handles or [])}
    out: list[RawItem] = []
    for t in raw_tweets:
        text = t.get("text") or ""
        cited = cited_handles(text)
        if not cited:
            continue
        if own and cited[-1].lstrip("@").lower() in own and not is_commentary(text):
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": cited[-1], "handles": cited,
                         "image_url": t.get("image_url")}))
    return out


_AFC_TAG_RE = re.compile(r"#AFC\b", re.IGNORECASE)


def parse_self_tweets(source_id: str, handle: str,
                      raw_tweets: list[dict], now: datetime) -> list[RawItem]:
    """본인 트윗 파싱(self_source) — 인용 불요, #AFC 태그 있는 것만 RawItem (spec §5.2·§5.4).
    #AFCB(본머스)·#AFCON 은 \\b 경계로 자연 배제. journalist 는 계정 주인으로 고정.
    리트윗은 status 링크 작성자(author)가 계정 주인과 달라 드롭된다 (tier 1 오귀속 가드)."""
    out: list[RawItem] = []
    for t in raw_tweets:
        author = t.get("author") or ""
        if author and author.lower() != handle.lower():
            continue
        text = t.get("text") or ""
        if not _AFC_TAG_RE.search(text):
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": "@" + handle,
                         "image_url": t.get("image_url"),
                         "card_href": t.get("card_href") or None}))
    return out


def _is_tweet_host(url: str) -> bool:
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    return (host in ("x.com", "twitter.com", "t.co")
            or host.endswith(".x.com") or host.endswith(".twitter.com"))


async def resolve_card_urls(items: list[RawItem], log: logging.Logger) -> list[RawItem]:
    """card_href 있는 트윗의 키를 원문 기사 URL 로 교체 (spec 2026-07-26 §6).
    같은 기사의 fmkorea 전문 도착 시 dedup upgrade 로 한 행에 합류하기 위한 선행 조건.
    리졸브 실패 · 트윗 도메인 카드 (인용 트윗) 는 현행 트윗 URL 폴백 — 본문은 저장하지 않는다."""
    import httpx
    from bullet_in.adapters import x_backtrack
    targets = [it for it in items if it.raw_payload.get("card_href")]
    if not targets:
        return items
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 bullet-in/0.1"}) as c:
        for it in targets:
            try:
                final_url, _body, _title, _image, _images = await x_backtrack.resolve_and_fetch(
                    c, it.raw_payload["card_href"])
            except Exception as e:  # 소스 격리 : 카드 하나 파싱 실패가 배치 전체를 죽이지 않게
                log.warning("card 리졸브 실패 (트윗 URL 유지) url=%s err=%s", it.url, e)
                continue
            if not final_url:
                log.info("card 리졸브 실패 — 트윗 URL 유지 %s", it.url)
                continue
            if _is_tweet_host(final_url):
                log.info("card 가 트윗 링크 — 트윗 URL 유지 %s", final_url)
                continue
            it.raw_payload["tweet_url"] = it.url
            it.url = final_url
    return items
