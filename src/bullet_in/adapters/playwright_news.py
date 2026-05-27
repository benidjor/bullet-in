from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import urljoin
from playwright.async_api import async_playwright
from bullet_in.models import RawItem

class PlaywrightAdapter:
    source_type = "playwright"
    def __init__(self, source_id: str, list_url: str, item_selector: str,
                 base_url: str | None = None, timeout_ms: int = 15000):
        self.source_id = source_id
        self.list_url = list_url
        self.item_selector = item_selector
        self.base_url = base_url or list_url
        self.timeout_ms = timeout_ms
    async def fetch(self) -> list[RawItem]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent="bullet-in/0.1")
            await page.goto(self.list_url, wait_until="domcontentloaded")
            await page.wait_for_selector(self.item_selector, timeout=self.timeout_ms)
            links = await page.eval_on_selector_all(
                self.item_selector,
                "els => els.map(e => ({href: e.href || e.getAttribute('href'),"
                " title: e.textContent.trim()}))")
            await browser.close()
        now, out, seen = datetime.now(timezone.utc), [], set()
        for l in links:
            if not l["href"]:
                continue
            url = urljoin(self.base_url, l["href"])
            if url in seen:
                continue
            seen.add(url)
            out.append(RawItem(source_id=self.source_id, source_type="playwright",
                               url=url, fetched_at=now,
                               raw_payload={"title": l["title"]}))
        return out
