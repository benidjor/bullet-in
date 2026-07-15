from __future__ import annotations
import re
from datetime import datetime, timezone
from dateutil import parser as dtparser
from bullet_in.models import RawItem, Article
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.dedup import classify
from bullet_in.credibility import resolve_tier, Registry
from bullet_in.score import confidence_from_tier

_WOMEN_RE = re.compile(r"women|wsl|여자", re.I)

def _is_womens_football(title: str, body: str | None) -> bool:
    """여자팀 기사 판별 — 제목 마커 또는 본문 도입부 (400자) 의 women 언급.
    남자팀 기사 후반부의 스치는 언급은 잡지 않는다 (도입부 한정)."""
    if _WOMEN_RE.search(title or ""):
        return True
    return bool(_WOMEN_RE.search((body or "")[:400]))

def _published(payload: dict) -> datetime:
    raw = payload.get("published") or payload.get("created_at")
    try:
        return dtparser.parse(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)

def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int]],
                registry: "Registry | None" = None) -> tuple[list[Article], dict]:
    out: list[Article] = []
    local_seen = dict(seen)
    dup_count = 0
    women_count = 0
    source_counts: dict[str, int] = {}
    # fmkorea(발견 소스)는 같은 원문 URL 에서 EN/X 보다 후순위 → first-seen 이 EN/X 가 되게 정렬
    raw = sorted(raw, key=lambda it: 1 if it.source_id == "fmkorea" else 0)
    for item in raw:
        tier = resolve_tier(item, sources, registry)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        if _is_womens_football(title, item.raw_payload.get("body")):
            women_count += 1
            continue
        url = canonical_url(item.url)
        h = content_hash(title, url)
        decision, rev = classify(url, h, local_seen)
        if decision == "duplicate":
            dup_count += 1
            continue
        local_seen[url] = (h, rev)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            body_source=item.raw_payload.get("body"),
            image_url=item.raw_payload.get("image_url"),
            images=item.raw_payload.get("images") or [],
            outlet=item.raw_payload.get("outlet"),
            journalist=item.raw_payload.get("journalist"),
            team="arsenal",
            published_at=_published(item.raw_payload), fetched_at=item.fetched_at,
            revision=rev))
        source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
    return out, {"dup_count": dup_count, "source_counts": source_counts,
                 "women_count": women_count}
