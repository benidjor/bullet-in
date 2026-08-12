"""arsenal_official 커버리지 백필 (1회성 · spec 2026-07-24 §6 §7).

label — 기존 행의 published_precision NULL 을 'time' 으로 라벨
  (대상 5행 전부 raw 에 발행 시각 실재 — 2026-07-24 감사 확인).
reverify — sitemap 기준으로 REVERIFY_SINCE 이후 공홈 뉴스를 재검증해
  놓친 오피셜을 표준 경로 (RawStore → to_articles → upsert → rule_stage) 로 적재.
rebody — 이미 적재된 공홈 기사의 본문을 다시 받아 갱신 (2026-08-12 파서 개정 소급).
  제목 · URL 이 그대로면 content_hash 도 같아 표준 경로가 duplicate 로 걸러내므로
  (dedup.classify) 재수집으로는 본문이 안 바뀐다. 대상 행만 직접 갱신하고 번역을
  초기화해 다음 정기 회차가 재번역하게 한다.

실행 전 `set -a; source .env; set +a` 필수 (dotenv 미사용).
VM 반영 절차 (타이머 창 · 스냅샷) 는 docs/runbook/2026-07-24-vm-live-reprocess-deploy.md.
    uv run python -m bullet_in.backfill_arsenal --phase label            # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase label --apply
    uv run python -m bullet_in.backfill_arsenal --phase reverify         # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase reverify --apply
    uv run python -m bullet_in.backfill_arsenal --phase rebody           # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase rebody --apply
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone
import httpx
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from bullet_in.adapters.arsenal_api import (ARTICLE_QUERY, GRAPHQL_URL,
                                            ArsenalApiAdapter, _body_payload,
                                            _glide_id)
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.credibility import load_registry
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.mongo import RawStore

log = logging.getLogger(__name__)

# 2026-08-12 개정 — 제목 채택 도입분 (뇌르고르 08-05 발표) 만 회수하면 되므로 창을 좁혔다.
# 넓힐수록 sitemap 창 안 기사마다 GetArticle 을 부르므로 라이브 접촉이 그만큼 늘어난다.
REVERIFY_SINCE = datetime(2026, 8, 1, tzinfo=timezone.utc)

_LABEL_SELECT = text(
    "SELECT content_hash, title_original, published_at FROM articles "
    "WHERE source_id='arsenal_official' AND published_precision IS NULL")
_LABEL_UPDATE = text(
    "UPDATE articles SET published_precision='time' "
    "WHERE source_id='arsenal_official' AND published_precision IS NULL")

def phase_label(apply: bool) -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = c.execute(_LABEL_SELECT).mappings().all()
    for r in rows:
        log.info("label 대상: %s %s %s",
                 r["content_hash"][:9], r["published_at"], r["title_original"][:50])
    if not apply:
        log.info("dry-run — 대상 %d행 (적용하려면 --apply)", len(rows))
        return
    with engine.begin() as c:
        res = c.execute(_LABEL_UPDATE)
    log.info("label 적용 — %d행 갱신", res.rowcount)

def phase_reverify(apply: bool) -> None:
    hours = (datetime.now(timezone.utc) - REVERIFY_SINCE).total_seconds() / 3600
    adapter = ArsenalApiAdapter("arsenal_official", window_hours=hours)
    raw = asyncio.run(adapter.fetch())
    log.info("재검증 퍼널: %s", adapter.coverage)
    for it in raw:
        it.content_hash = content_hash(it.raw_payload.get("title") or "",
                                       canonical_url(it.url))
        log.info("accept: %s %s", it.raw_payload.get("published"),
                 it.raw_payload.get("title"))
    if not apply:
        log.info("dry-run — accept %d건 (적용하려면 --apply)", len(raw))
        return
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)
    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    mart.upsert(arts)
    # stage 는 여기서 채우지 않는다 — 정기 회차의 규칙 경로가 공홈을 official 로 고정하면서
    # 방향은 LLM 배치에서 함께 받는다 (run.py 의 stage_ruled). 여기서 stage 만 채우면 그 행이
    # 분류 대상 (rows_missing_stage) 에서 빠져 direction 이 NULL 로 남고, 단계 필터가 방향
    # 한정이 된 뒤로는 (단계 재정의 스펙 §8) 오피셜 배지를 달고도 필터에서 사라진다.
    log.info("적재 — 신규 %d · 중복 %d (번역 · 분류는 정규 회차가 흡수)",
             len(arts), stats["dup_count"])

_REBODY_SELECT = text(
    "SELECT content_hash, url, title_original, body_source FROM articles "
    "WHERE source_id='arsenal_official' ORDER BY published_at")
_REBODY_UPDATE = text(
    "UPDATE articles SET body_source=:b, body_excerpt=:b WHERE content_hash=:h")

def rebody_update(row: dict, body: str) -> dict | None:
    """새 본문이 더 길 때만 갱신 대상 — 응답 이상 · 파서 회귀로 기존 본문을 줄이지 않는다."""
    if not body or len(body) <= len(row.get("body_source") or ""):
        return None
    return {"h": row["content_hash"], "b": body}

async def _fetch_bodies(urls: list[str]) -> dict[str, str]:
    """URL → 새 본문. 저장된 URL 로 건별 조회한다 (sitemap 창을 훑지 않아 접촉이 대상 수만큼)."""
    out: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=20,
                                 headers={"User-Agent": "bullet-in/0.1"}) as c:
        for url in urls:
            gid = _glide_id(url)
            if gid is None:
                log.warning("glideId 추출 실패 — %s", url)
                continue
            try:
                r = await c.post(GRAPHQL_URL, json={
                    "operationName": "GetArticle", "query": ARTICLE_QUERY,
                    "variables": {"articleId": "", "glideId": gid, "glidePath": ""}})
                r.raise_for_status()
                art = r.json()["data"]["getArticle"]
            except (httpx.HTTPError, KeyError) as e:
                log.warning("GetArticle 실패 (%s) — %s", e, url)
                continue
            if art:
                out[url] = _body_payload(art.get("articleBody") or [])["body"]
    return out

def phase_rebody(apply: bool) -> None:
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in c.execute(_REBODY_SELECT).mappings().all()]
    bodies = asyncio.run(_fetch_bodies([r["url"] for r in rows]))
    targets = []
    for r in rows:
        body = bodies.get(r["url"], "")
        upd = rebody_update(r, body)
        log.info("%s %4d → %4d자 %s %s", r["content_hash"][:9],
                 len(r["body_source"] or ""), len(body),
                 "갱신" if upd else "유지", (r["title_original"] or "")[:45])
        if upd:
            targets.append(upd)
    if not apply:
        log.info("dry-run — 갱신 대상 %d/%d행 (적용하려면 --apply)", len(targets), len(rows))
        return
    with engine.begin() as c:
        for t in targets:
            c.execute(_REBODY_UPDATE, t)
    mart = MartStore(engine)
    cleared = mart.clear_translation([t["h"] for t in targets])
    log.info("본문 갱신 %d행 · 번역 초기화 %d행 (재번역 · 재요약은 다음 정기 회차)",
             len(targets), cleared)

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["label", "reverify", "rebody"], required=True)
    ap.add_argument("--apply", action="store_true", help="미지정 시 dry-run")
    args = ap.parse_args()
    {"label": phase_label, "reverify": phase_reverify,
     "rebody": phase_rebody}[args.phase](args.apply)

if __name__ == "__main__":
    main()
