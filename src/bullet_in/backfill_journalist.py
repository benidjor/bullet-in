"""기존 기사의 journalist 백필 (1회성).

raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.
통칭 소스 (journalist_label) 는 재fetch 없이 일괄 채운다.
멱등 — 재실행 시 journalist IS NULL 인 행만 다시 시도한다.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_journalist --limit 5 --dry-run
    uv run python -m bullet_in.backfill_journalist
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timezone
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_authors
from bullet_in.credibility import load_registry, resolve_tier
from bullet_in.models import RawItem
from bullet_in.pipeline import select_journalist
from bullet_in.score import load_sources, confidence_from_tier

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 소스별 순차 · 요청 간격 (라이브 사이트 부담 회피)

def journalist_update(html: str, sid: str, url: str, sources: dict, registry) -> dict:
    """재fetch 한 기사 HTML → 저장할 journalist · tier · confidence_score.
    선정 · 보정 규칙은 수집 경로와 같은 함수를 재사용한다 (규칙 이중화 방지)."""
    item = RawItem(source_id=sid, source_type="html", url=url,
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"authors": extract_authors(html)})
    src = sources.get(sid, {})
    journalist = select_journalist(item, src, registry)
    tier = resolve_tier(item, sources, registry, journalist=journalist)
    return {"journalist": journalist, "tier": tier,
            "confidence_score": confidence_from_tier(tier)}

_SELECT_SQL = text(
    "SELECT content_hash, url, source_id FROM articles "
    "WHERE journalist IS NULL AND source_id IN :sids ORDER BY source_id, published_at DESC"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수
_UPDATE_SQL = text(
    "UPDATE articles SET journalist=:j, tier=:t, confidence_score=:c "
    "WHERE content_hash=:h")

async def backfill(limit: int | None = None, dry_run: bool = False) -> dict[str, dict]:
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    # 재fetch 대상 = html 어댑터 · 상세를 읽는 소스 (body_selector) · 통칭 없는 곳.
    # adapter 조건이 없으면 fmkorea (config 에 body_selector 보유) 가 섞여 2h 규칙을 깬다.
    fetch_ids = [sid for sid, s in sources.items()
                 if s.get("adapter") == "html"
                 and s.get("config", {}).get("body_selector")
                 and not s.get("journalist_label")]
    label_ids = [sid for sid, s in sources.items() if s.get("journalist_label")]
    engine = create_engine(os.environ["MARIADB_URL"])
    stats: dict[str, dict] = {}

    # 1) 통칭 소스 — 재fetch 없이 일괄 UPDATE
    for sid in label_ids:
        label = sources[sid]["journalist_label"]
        if dry_run:
            log.info("[dry-run] %s → journalist=%r 일괄", sid, label)
            continue
        with engine.begin() as c:
            n = c.execute(text("UPDATE articles SET journalist=:j "
                               "WHERE journalist IS NULL AND source_id=:s"),
                          {"j": label, "s": sid}).rowcount
        stats[sid] = {"ok": n, "fail": 0}
        log.info("%s: 통칭 %r %d건", sid, label, n)

    # 2) 재fetch 대상 — 소스별 순차 · 간격
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": fetch_ids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("재fetch 대상 %d건 (소스 %s)", len(rows), ", ".join(fetch_ids))

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            sid = row["source_id"]
            st = stats.setdefault(sid, {"ok": 0, "fail": 0})
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    st["fail"] += 1                  # 404 · 타임아웃 → NULL 유지 · 다음 건
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                upd = journalist_update(r.text, sid, row["url"], sources, registry)
                if upd["journalist"] is None:
                    st["fail"] += 1
                    log.warning("저자 부재 %s", row["url"])
                    continue
                if dry_run:
                    log.info("[dry-run] %s → %r tier=%s", row["url"], upd["journalist"], upd["tier"])
                else:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"j": upd["journalist"], "t": upd["tier"],
                                                "c": upd["confidence_score"],
                                                "h": row["content_hash"]})
                st["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="기존 기사 journalist 백필 (멱등)")
    ap.add_argument("--limit", type=int, default=None, help="재fetch 대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    args = ap.parse_args()
    stats = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    for sid, s in sorted(stats.items()):
        print(f"{sid}: 성공 {s['ok']} · 실패 {s['fail']}")

if __name__ == "__main__":
    main()
