"""arsenal_official 커버리지 백필 (1회성 · spec 2026-07-24 §6 §7).

label — 기존 행의 published_precision NULL 을 'time' 으로 라벨
  (대상 5행 전부 raw 에 발행 시각 실재 — 2026-07-24 감사 확인).
reverify — sitemap 기준으로 2026-06-01 이후 공홈 뉴스를 재검증해
  놓친 오피셜을 표준 경로 (RawStore → to_articles → upsert → rule_stage) 로 적재.

실행 전 `set -a; source .env; set +a` 필수 (dotenv 미사용).
VM 반영 절차 (타이머 창 · 스냅샷) 는 docs/runbook/2026-07-24-vm-live-reprocess-deploy.md.
    uv run python -m bullet_in.backfill_arsenal --phase label            # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase label --apply
    uv run python -m bullet_in.backfill_arsenal --phase reverify         # dry-run
    uv run python -m bullet_in.backfill_arsenal --phase reverify --apply
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone
from pymongo import MongoClient
from sqlalchemy import create_engine, text
from bullet_in import transfer_stage
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
from bullet_in.canonical import canonical_url, content_hash
from bullet_in.credibility import load_registry
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.mongo import RawStore

log = logging.getLogger(__name__)

REVERIFY_SINCE = datetime(2026, 6, 1, tzinfo=timezone.utc)

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
    ruled = transfer_stage.rule_stage("arsenal_official")
    for r in mart.rows_missing_stage():
        if r["source_id"] == "arsenal_official" and ruled:
            mart.set_stage(r["content_hash"], ruled)
    log.info("적재 — 신규 %d · 중복 %d (번역은 정규 회차가 흡수)",
             len(arts), stats["dup_count"])

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["label", "reverify"], required=True)
    ap.add_argument("--apply", action="store_true", help="미지정 시 dry-run")
    args = ap.parse_args()
    (phase_label if args.phase == "label" else phase_reverify)(args.apply)

if __name__ == "__main__":
    main()
