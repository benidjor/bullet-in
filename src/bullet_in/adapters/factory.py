from __future__ import annotations
import os
import logging
from collections.abc import Collection
from datetime import datetime, timezone
from bullet_in.adapters.rss import RssAdapter
from bullet_in.adapters.guardian_api import GuardianAdapter
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter, REPUBLISHED_MAX_AGE_DAYS
from bullet_in.adapters.html import HtmlAdapter
from bullet_in.adapters.playwright_news import PlaywrightAdapter
from bullet_in.adapters.x_playwright import XPlaywrightAdapter
from bullet_in.adapters.fmkorea import FmkoreaAdapter

from bullet_in.scope import ScopeRule, scope_names
from bullet_in.transfer_windows import in_transfer_window

log = logging.getLogger(__name__)

def scope_rules(cfg: dict, roster) -> tuple[ScopeRule, ScopeRule]:
    """(언론사용, 공식 소스용) 수집 범위 판정 규칙 (설계 2026-10-07 §2 · §3.2).

    공식 소스는 이적 낱말을 이미 자기 경로 (`tag` · `title`) 로 보므로 키워드 갈래를
    빼고 이름 · 추가 낱말 · 팀 낱말만 쓴다. 명단이 없으면 이름 갈래만 빠진다.

    성만으로는 안 받는 사람 (`scope_name_full_only`) 은 {성: 전체 이름} 으로 넘겨
    문맥에 전체 이름이 있을 때 받게 한다 (2주 수집 검토 2026-11-15)."""
    full_only = cfg.get("scope_name_full_only") or ()
    names = (scope_names(roster, cfg.get("scope_name_extras") or (), full_only)
             if roster else set())
    confirm = {sur: full for full, sur in (roster or ()) if full and sur in full_only}
    return (ScopeRule(cfg.get("transfer_keywords") or (), names, confirm),
            ScopeRule((), names, confirm))

def scheduled_skips(sources: list[dict], now: datetime) -> list[str]:
    """이번 실행 칸에 돌지 않는 소스 — `run_hours_utc` 가 있는 수집 대상만 본다.

    실행은 3시간 칸 (0 · 3 · … · 21 UTC) 에 시작하고 늦게 떠도 같은 칸으로 센다.
    이적기간이면 `in_window`, 아니면 `out_of_window` 목록에 이번 칸이 없는 소스를 낸다."""
    utc = now.astimezone(timezone.utc)
    slot = utc.hour - utc.hour % 3
    key = "in_window" if in_transfer_window(now) else "out_of_window"
    return [s["source_id"] for s in sources
            if s.get("run_hours_utc") and s.get("enabled", True) and s.get("collect", True)
            and slot not in s["run_hours_utc"][key]]


def build_adapters(cfg: dict, fmkorea_player_names: set[str] | None = None,
                   scope_roster: list[tuple[str, str]] | None = None,
                   skip: Collection[str] = ()) -> list:
    press_scope, official_scope = scope_rules(cfg, scope_roster)
    out = []
    for s in cfg["sources"]:
        # enabled 는 소스를 통째로 없앤다 — load_sources 도 걸러서 언론사 이름 · 공신력 ·
        # 본문 서빙 범위가 함께 사라지므로, 이미 적재된 기사가 있으면 그 화면이 깨진다.
        # collect 는 수집만 멈추고 표시 설정을 남긴다 (읽는 쪽은 이 키를 안 본다).
        if not s.get("enabled", True) or not s.get("collect", True):
            continue
        if s["source_id"] in skip:
            continue
        c = s.get("config", {})
        kind, sid = s["adapter"], s["source_id"]
        if kind == "rss":
            out.append(RssAdapter(sid, c["feed_url"],
                                  title_contains=c.get("title_contains"),
                                  body_selector=c.get("body_selector"),
                                  scope=press_scope if c.get("title_scope") else None))
        elif kind == "guardian_api":
            key = os.environ.get("GUARDIAN_API_KEY")
            if not key:
                log.warning("GUARDIAN_API_KEY 미설정 — %s 소스 스킵 (다음 사이클 재시도)", sid)
                continue
            out.append(GuardianAdapter(sid, key,
                                       tag=c.get("tag", "football/arsenal"),
                                       title_contains=c.get("title_contains")))
        elif kind == "arsenal_api":
            out.append(ArsenalApiAdapter(
                sid, scope=official_scope if c.get("title_scope") else None,
                max_age_days=REPUBLISHED_MAX_AGE_DAYS))
        elif kind == "html":
            out.append(HtmlAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url"),
                                   title_contains=c.get("title_contains"),
                                   body_selector=c.get("body_selector"),
                                   title_selector=c.get("title_selector"),
                                   thumbnail_only=c.get("thumbnail_only", False),
                                   title_attr=c.get("title_attr"),
                                   scope=press_scope if c.get("title_scope") else None,
                                   scope_url_contains=c.get("scope_url_contains") or ()))
        elif kind == "playwright":
            out.append(PlaywrightAdapter(sid, c["list_url"], c["item_selector"], c.get("base_url")))
        elif kind == "x_playwright":
            out.append(XPlaywrightAdapter(sid, c["handle"],
                                          c.get("max_tweets", 20),
                                          c.get("cookies_path", "x_cookies.json"),
                                          c.get("backtrack_config"),
                                          self_source=c.get("self_source", False),
                                          own_source_handles=c.get("own_source_handles"),
                                          cache_path=c.get("cache_path")))
        elif kind == "fmkorea":
            out.append(FmkoreaAdapter(
                sid, c["search_url"], c["search_keywords"],
                item_selector=c.get("item_selector", "a.hx"),
                base_url=c.get("base_url", "https://www.fmkorea.com"),
                body_selector=c.get("body_selector", ".xe_content"),
                max_posts=c.get("max_posts", 15),
                proxy=os.environ.get("FMKOREA_PROXY"),
                relevance_terms=c.get("relevance_terms"),
                player_names=fmkorea_player_names))
        else:
            raise ValueError(f"unknown adapter: {kind}")
    return out
