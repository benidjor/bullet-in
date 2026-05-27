from __future__ import annotations
import os
from bullet_in.adapters.rss import RssAdapter
from bullet_in.adapters.guardian_api import GuardianAdapter
from bullet_in.adapters.html import HtmlAdapter
from bullet_in.adapters.playwright_news import PlaywrightAdapter
from bullet_in.adapters.x_twikit import XAdapter

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
            out.append(GuardianAdapter(sid, os.environ["GUARDIAN_API_KEY"],
                                       c.get("query", "Arsenal"), c.get("section", "football")))
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url")))
        elif kind == "playwright":
            out.append(PlaywrightAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url")))
        elif kind == "x_twikit":
            out.append(XAdapter(sid, c["handle"], c.get("max_tweets", 20)))
        else:
            raise ValueError(f"unknown adapter: {kind}")
    return out
