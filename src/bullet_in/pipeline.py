from __future__ import annotations
import re
from datetime import datetime, timezone, timedelta
from dateutil import parser as dtparser
from bullet_in.models import RawItem, Article
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.dedup import classify
from bullet_in.credibility import resolve_tier, norm_alias, Registry
from bullet_in.score import confidence_from_tier
from bullet_in.adapters.meta import split_authors

_WOMEN_RE = re.compile(r"women|wsl|여자", re.I)

def _is_womens_football(title: str, body: str | None) -> bool:
    """여자팀 기사 판별 — 제목 마커 또는 본문 도입부 (400자) 의 women 언급.
    남자팀 기사 후반부의 스치는 언급은 잡지 않는다 (도입부 한정)."""
    if _WOMEN_RE.search(title or ""):
        return True
    return bool(_WOMEN_RE.search((body or "")[:400]))

def _body_level(payload: dict) -> int:
    """본문 출처 등급 — 어댑터가 실은 값이 있으면 그대로 쓴다.
    미명시 소스는 언론사 페이지에서 직접 본문을 받으므로 있으면 2 · 없으면 0.
    (커뮤니티가 옮긴 본문 1 은 그 재료를 아는 어댑터만 명시할 수 있다.)"""
    declared = payload.get("body_level")
    if declared is not None:
        return int(declared)
    return 2 if payload.get("body") else 0

def _published(payload: dict, fetched_at: datetime) -> datetime:
    """발행 시각 — payload 추출값 우선, 실패 시 수집 시각 폴백 (처리 시각 now() 아님).
    naive 는 UTC 간주 · fetched_at+1h 초과 미래값은 오파싱으로 보고 폴백."""
    raw = payload.get("published") or payload.get("created_at")
    try:
        dt = dtparser.parse(raw)
    except (TypeError, ValueError):
        return fetched_at
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    if dt > fetched_at + timedelta(hours=1):
        return fetched_at
    return dt

def select_journalist(item, src: dict, registry: "Registry | None") -> str | None:
    """항목의 대표 기자 1명 — 기존 값 · 소스 통칭 · 추출 저자 (등재자 우선) 순.
    journalist 컬럼은 단일 문자열 — 복수 저자는 대표 1명만 남긴다 (spec 확정 결정)."""
    j = item.raw_payload.get("journalist")
    if j:
        return j                                   # 동적 소스 (x · fmkorea) 가 이미 실은 값
    label = src.get("journalist_label")
    if label:
        return label                               # 조직 바이라인 통칭 (추출값보다 우선)
    authors = item.raw_payload.get("authors") or []
    if registry is not None:
        for a in authors:
            if norm_alias(a) in registry.journalists:
                return a
    return authors[0] if authors else None

def select_authors(item, journalist: str | None) -> list[str]:
    """항목의 저자 전원 — 대표를 포함해 등장 순서를 보존하고 중복을 없앤다.

    어댑터가 실은 목록이 있으면 그대로 쓰고, 없으면 대표 문자열을 구분자로 쪼갠다
    (합성 저장값 '잭 로서, 사이먼 콜링스' 가 이 갈래로 두 이름이 된다).
    노출 정책은 읽는 쪽이 정한다 — 여기서는 재료를 버리지 않는 것이 일이다."""
    names = list(item.raw_payload.get("authors") or []) or ([journalist] if journalist else [])
    out: list[str] = []
    for raw in names:
        # 이어 붙은 이름을 한 번 더 쪼갠다 — 옛 규칙으로 저장된 재료 ('A and B' 가 한 칸)
        # 를 소급할 때도 같은 함수를 쓰기 위해서다.
        for n in split_authors(raw or ""):
            if n not in out:
                out.append(n)
    return out

def to_articles(raw: list[RawItem], sources: dict[str, dict],
                seen: dict[str, tuple[str, int, str, int]],
                registry: "Registry | None" = None) -> tuple[list[Article], dict]:
    out: list[Article] = []
    local_seen = dict(seen)
    dup_count = 0
    women_count = 0
    author_drop_count = 0
    blocked_count = 0
    source_counts: dict[str, int] = {}
    # fmkorea(발견 소스)는 같은 원문 URL 에서 EN/X 보다 후순위 → first-seen 이 EN/X 가 되게 정렬
    raw = sorted(raw, key=lambda it: 1 if it.source_id == "fmkorea" else 0)
    for item in raw:
        src = sources.get(item.source_id, {})
        journalist = select_journalist(item, src, registry)
        allowlist = src.get("journalist_allowlist")
        if allowlist and journalist not in allowlist:
            author_drop_count += 1     # 전담 외 기자 · 저자 미상 drop (spec §3.1)
            continue
        tier = resolve_tier(item, sources, registry, journalist=journalist)
        if tier is None:
            continue
        title = item.raw_payload.get("title") or item.raw_payload.get("text") or ""
        if _is_womens_football(title, item.raw_payload.get("body")):
            women_count += 1
            continue
        url = canonical_url(item.url)
        h = content_hash(title, url)
        body_level = _body_level(item.raw_payload)
        decision, rev = classify(url, h, local_seen, item.source_id, body_level)
        if decision == "duplicate":
            dup_count += 1
            continue
        if decision == "blocked":
            blocked_count += 1     # 완전체 보호 · 스텁끼리 충돌 (spec §4)
            continue
        local_seen[url] = (h, rev, item.source_id, body_level)
        out.append(Article(
            content_hash=h, url=url, source_id=item.source_id,
            tier=tier, confidence_score=confidence_from_tier(tier),
            title_original=title,
            body_excerpt=item.raw_payload.get("summary") or item.raw_payload.get("body"),
            body_source=item.raw_payload.get("body"),
            body_level=body_level,
            image_url=item.raw_payload.get("image_url"),
            images=item.raw_payload.get("images") or [],
            outlet=item.raw_payload.get("outlet"),
            journalist=journalist,
            authors=select_authors(item, journalist),
            team="arsenal",
            accept_path=item.raw_payload.get("accept_path"),
            published_at=_published(item.raw_payload, item.fetched_at),
            published_precision=item.raw_payload.get("published_precision"),
            fetched_at=item.fetched_at,
            revision=rev))
        source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
    return out, {"dup_count": dup_count, "source_counts": source_counts,
                 "women_count": women_count, "author_drop_count": author_drop_count,
                 "blocked_count": blocked_count}
