from __future__ import annotations
from datetime import datetime
from dateutil import parser as dtparser
from bullet_in.models import RawItem, Article
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.dedup import classify
from bullet_in.score import confidence

def _published(payload: dict) -> datetime:
    raw = payload.get("published") or payload.get("created_at")
    try:
        return dtparser.parse(raw)
    except (TypeError, ValueError):
        return datetime.now().astimezone()

def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]]) -> list[Article]:
    out: list[Article] = []
    local_seen = dict(seen)
    for item in raw:
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            continue
        local_seen[url] = (h, rev)
        src = sources.get(item.source_id, {})
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=src.get("tier"), confidence_score=confidence(item.source_id, sources),
            title_original=title, body_excerpt=item.raw_payload.get("summary"),
            published_at=_published(item.raw_payload), revision=rev))
    return out
