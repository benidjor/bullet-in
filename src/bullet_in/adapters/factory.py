from __future__ import annotations
import os
import logging
from bullet_in.adapters.rss import RssAdapter
from bullet_in.adapters.guardian_api import GuardianAdapter
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
from bullet_in.adapters.html import HtmlAdapter
from bullet_in.adapters.playwright_news import PlaywrightAdapter
from bullet_in.adapters.x_playwright import XPlaywrightAdapter
from bullet_in.adapters.fmkorea import FmkoreaAdapter

log = logging.getLogger(__name__)

def build_adapters(cfg: dict) -> list:
    out = []
    for s in cfg["sources"]:
        if not s.get("enabled", True):
            continue
        c = s.get("config", {})
        kind, sid = s["adapter"], s["source_id"]
        if kind == "rss":
            out.append(RssAdapter(sid, c["feed_url"]))
        elif kind == "guardian_api":
            key = os.environ.get("GUARDIAN_API_KEY")
            if not key:
                log.warning("GUARDIAN_API_KEY 미설정 — %s 소스 스킵 (다음 사이클 재시도)", sid)
                continue
            out.append(GuardianAdapter(sid, key,
                                       tag=c.get("tag", "football/arsenal"),
                                       title_contains=c.get("title_contains")))
        elif kind == "arsenal_api":
            out.append(ArsenalApiAdapter(sid))
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector"),
                                   title_selector=c.get("title_selector"),
                                   thumbnail_only=c.get("thumbnail_only", False)))
        elif kind == "playwright":
            out.append(PlaywrightAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url")))
        elif kind == "x_playwright":
            out.append(XPlaywrightAdapter(sid, c["handle"],
                                          c.get("max_tweets", 20),
                                          c.get("cookies_path", "x_cookies.json"),
                                          c.get("backtrack_config")))
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["search_url"], c["search_keywords"],
                item_selector=c.get("item_selector", "a.hx"),
                base_url=c.get("base_url", "https://www.fmkorea.com"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 15)))
        else:
            raise ValueError(f"unknown adapter: {kind}")
    return out
