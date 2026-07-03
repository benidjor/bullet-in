from __future__ import annotations
import json
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
  const href = link ? link.getAttribute('href') : '';
  const m = href ? href.match(/status\\/(\\d+)/) : null;
  return {
    text: t ? t.innerText : '',
    created_at: time ? time.getAttribute('datetime') : '',
    status_id: m ? m[1] : '',
    image_url: img ? img.src : null
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
                 cookies_path: str = "x_cookies.json", backtrack_config_path: str | None = None):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path
        self.backtrack_config_path = backtrack_config_path

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
            items = parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets, now)
            timelines = {}
            if bt:
                timelines = await self._scrape_journalists(ctx, items, bt, log)
            await browser.close()
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


def parse_afcstuff_tweets(source_id: str, handle: str,
                          raw_tweets: list[dict], now: datetime) -> list[RawItem]:
    """DOM에서 뽑은 트윗 dict → 인용(`[ @handle ]`) 있는 것만 RawItem."""
    out: list[RawItem] = []
    for t in raw_tweets:
        text = t.get("text") or ""
        cited = ["@" + h for h in _CITE_RE.findall(text)]
        if not cited:
            continue
        sid = t.get("status_id") or ""
        out.append(RawItem(
            source_id=source_id, source_type="x",
            url=f"https://x.com/{handle}/status/{sid}", fetched_at=now,
            raw_payload={"text": text, "created_at": t.get("created_at"),
                         "journalist": cited[-1], "handles": cited,
                         "image_url": t.get("image_url")}))
    return out
