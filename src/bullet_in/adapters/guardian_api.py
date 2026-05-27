from __future__ import annotations
from datetime import datetime, timezone
import httpx
from bullet_in.models import RawItem

class GuardianAdapter:
    source_type = "api"
    BASE = "https://content.guardianapis.com/search"
    def __init__(self, source_id: str, api_key: str, query: str = "Arsenal",
                 section: str = "football"):
        self.source_id = source_id
        self.params = {"q": query, "section": section, "api-key": api_key,
                       "show-fields": "trailText", "order-by": "newest"}
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(self.BASE, params=self.params)
            r.raise_for_status()
            results = r.json()["response"]["results"]
        now = datetime.now(timezone.utc)
        return [RawItem(source_id=self.source_id, source_type="api", url=x["webUrl"],
                        fetched_at=now,
                        raw_payload={"title": x["webTitle"],
                                     "published": x.get("webPublicationDate"),
                                     "summary": x.get("fields", {}).get("trailText", "")})
                for x in results]
