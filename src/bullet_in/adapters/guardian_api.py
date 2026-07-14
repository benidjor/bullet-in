from __future__ import annotations
from datetime import datetime, timezone
import httpx
from bullet_in.models import RawItem

class GuardianAdapter:
    source_type = "api"
    BASE = "https://content.guardianapis.com/search"
    def __init__(self, source_id: str, api_key: str, tag: str = "football/arsenal",
                 title_contains: str | list[str] | None = None):
        self.source_id = source_id
        # q= 전문검색은 타 구단 기사 혼입 → tag 스코프 (spec §5.1)
        self.params = {"tag": tag, "api-key": api_key,
                       "show-fields": "trailText,bodyText,thumbnail",
                       "order-by": "newest", "page-size": 20}
        if title_contains is None:
            self.title_keywords: list[str] | None = None
        elif isinstance(title_contains, str):
            self.title_keywords = [title_contains.lower()]
        else:
            self.title_keywords = [k.lower() for k in title_contains]
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self.BASE, params=self.params)
            r.raise_for_status()
            results = r.json()["response"]["results"]
        now = datetime.now(timezone.utc)
        out = []
        for x in results:
            title = x["webTitle"]
            if self.title_keywords and not any(
                    k in title.lower() for k in self.title_keywords):
                continue
            f = x.get("fields", {})
            out.append(RawItem(source_id=self.source_id, source_type="api",
                               url=x["webUrl"], fetched_at=now,
                               raw_payload={"title": title,
                                            "published": x.get("webPublicationDate"),
                                            "summary": f.get("trailText", ""),
                                            "body": f.get("bodyText", ""),
                                            "image_url": f.get("thumbnail")}))
        return out
