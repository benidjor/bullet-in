"""RSS 피드 어댑터 (설계 2026-10-05 §2).

피드는 httpx 로 받는다 — feedparser 가 주소를 직접 받으면 HTTP 오류에도 예외 없이
빈 목록을 돌려줘, 피드가 죽은 것과 새 글이 없는 것이 구별되지 않는다 (§2.2)."""
from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import httpx

from bullet_in.adapters.detail import fetch_article_detail
from bullet_in.adapters.meta import _parse_published
from bullet_in.models import RawItem
from bullet_in.quality import list_signature


class RssAdapter:
    source_type = "rss"

    def __init__(self, source_id: str, feed_url: str,
                 title_contains: str | list[str] | None = None,
                 body_selector: str | None = None):
        self.source_id = source_id
        self.feed_url = feed_url
        self.body_selector = body_selector
        # 수집 단계 기록 — SLO-5 응답 판정 (quality.responded) 이 읽는다 (§3.1).
        self.funnel: dict = {}
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]

    async def fetch(self) -> list[RawItem]:
        self.funnel = {}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "bullet-in/0.1"}) as c:
            r = await c.get(self.feed_url)
            r.raise_for_status()
            entries = feedparser.parse(r.content).entries
            now, matched, seen = datetime.now(timezone.utc), [], []
            funnel = {"entries": len(entries), "deduped": 0, "passed": 0}
            for e in entries:
                url = (e.get("link") or "").strip()
                if not url or url in seen:
                    continue
                seen.append(url)
                funnel["deduped"] += 1
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                if self.title_keywords and not any(
                        k in title.lower() for k in self.title_keywords):
                    continue
                funnel["passed"] += 1
                matched.append((title, url, e))
            # 목록 지문 — 키워드 필터 앞의 링크 묶음 (HTML 어댑터와 같은 규칙 · §2.3)
            funnel["list_sig"] = list_signature(seen)
            self.funnel = funnel
            out = []
            for title, url, e in matched:
                payload = {"title": title, "summary": e.get("summary", "")}
                pub = _parse_published(e.get("published") or "")
                if pub:
                    payload["published"] = pub[0].isoformat()
                    payload["published_precision"] = pub[1]
                if self.body_selector:
                    # 상세 페이지의 발행 시각이 더 정밀할 때만 피드 값을 덮는다 (§2.1)
                    detail = await fetch_article_detail(c, url, self.body_selector)
                    if (detail.get("published_precision") == "day"
                            and payload.get("published_precision") == "time"):
                        detail = {k: v for k, v in detail.items()
                                  if k not in ("published", "published_precision")}
                    payload.update(detail)
                out.append(RawItem(source_id=self.source_id, source_type="rss",
                                   url=url, fetched_at=now, raw_payload=payload))
        return out
