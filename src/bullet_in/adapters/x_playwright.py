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

_CITE_RE = re.compile(r"\[\s*@([A-Za-z0-9_]{1,15})\s*\]")


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


class XPlaywrightAdapter:
    source_type = "x"

    def __init__(self, source_id: str, handle: str, max_tweets: int = 20,
                 cookies_path: str = "x_cookies.json"):
        self.source_id, self.handle = source_id, handle
        self.max_tweets, self.cookies_path = max_tweets, cookies_path

    async def fetch(self) -> list[RawItem]:
        from datetime import timezone
        cookies = _x_cookies(self.cookies_path)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            await ctx.add_cookies(cookies)
            page = await ctx.new_page()
            await page.goto(f"https://x.com/{self.handle}",
                            wait_until="domcontentloaded")
            await page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
            seen = 0
            for _ in range(6):  # max_tweets 채울 때까지 소폭 스크롤
                raw_tweets = await page.eval_on_selector_all(
                    'article[data-testid="tweet"]', _TWEET_JS)
                if len(raw_tweets) >= self.max_tweets or len(raw_tweets) == seen:
                    break
                seen = len(raw_tweets)
                await page.mouse.wheel(0, 3000)
                await page.wait_for_timeout(800)
            await browser.close()
        raw_tweets = raw_tweets[: self.max_tweets]
        return parse_afcstuff_tweets(self.source_id, self.handle, raw_tweets,
                                     datetime.now(timezone.utc))


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
