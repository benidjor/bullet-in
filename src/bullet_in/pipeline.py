from __future__ import annotations
from datetime import datetime, timezone
from dateutil import parser as dtparser
from bullet_in.models import RawItem, Article
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.dedup import classify
from bullet_in.credibility import resolve_tier, Registry
from bullet_in.score import confidence_from_tier

def _published(payload: dict) -> datetime:
    raw = payload.get("published") or payload.get("created_at")
    try:
        return dtparser.parse(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)

def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]],
                registry: "Registry | None" = None) -> list[Article]:
    out: list[Article] = []
    local_seen = dict(seen)
    for item in raw:
        tier = resolve_tier(item, sources, registry)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            continue
        local_seen[url] = (h, rev)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            published_at=_published(item.raw_payload), fetched_at=item.fetched_at,
            revision=rev))
    return out
