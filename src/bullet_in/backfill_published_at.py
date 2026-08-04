"""발행일이 수집 시각으로 대체된 행 복구 (1회성 · 멱등).

수집 당시 발행일 추출에 실패하면 pipeline._published() 가 수집 시각을 넣는다.
추출기 자체는 지금 정상이라 URL 을 다시 받아 발행일만 다시 읽으면 복구된다.
번역 · 본문 · 저자는 건드리지 않는다 — 재번역 과금을 피하려는 설계다 (스펙 §4.1).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_published_at --dry-run
    uv run python -m bullet_in.backfill_published_at --source-id fmkorea
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from datetime import datetime, timedelta
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_published_at
from bullet_in.score import load_sources

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 다른 백필들과 같은 기준 (라이브 사이트 부담 회피)
NEAR_FETCH_SEC = 300       # 발행일이 수집 시각의 5분 이내면 대체값으로 본다 (스펙 §3.1)


def decide(html: str, fetched_at: datetime) -> tuple[datetime, str] | None:
    """저장할 (발행일, 정밀도). 정할 수 없으면 None — 그 행은 건드리지 않는다.

    미래값 가드는 pipeline._published() 와 같은 기준이다 — 수집 시각보다 한 시간
    넘게 뒤인 발행일은 오파싱으로 본다.
    """
    got = extract_published_at(html)
    if not got:
        return None
    dt = got[0].replace(tzinfo=None)
    if dt > fetched_at + timedelta(hours=1):
        return None
    return dt, got[1]


def target_source_ids(sources: dict) -> list[str]:
    """재수집 대상 소스 — 트윗은 뺀다.

    트윗에는 JSON-LD 가 없고 날짜가 created_at 에서 오므로 재수집할 것이 없다.
    """
    return [sid for sid, s in sources.items()
            if s.get("adapter") != "x_playwright"]


_SELECT_SQL = text(
    "SELECT content_hash, url, source_id, published_at, fetched_at FROM articles "
    "WHERE published_precision IS NULL "
    f"AND ABS(TIMESTAMPDIFF(SECOND, published_at, fetched_at)) < {NEAR_FETCH_SEC} "
    "AND source_id IN :sids ORDER BY source_id, published_at"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수

_UPDATE_SQL = text(
    "UPDATE articles SET published_at=:p, published_precision=:pr "
    "WHERE content_hash=:h")


async def backfill(source_id: str | None = None, limit: int | None = None,
                   dry_run: bool = False) -> dict[str, dict]:
    sources = load_sources("config/sources.yaml")
    allowed = target_source_ids(sources)
    if source_id and source_id not in allowed:
        raise SystemExit(f"대상 아닌 소스: {source_id} — 가능한 소스: {', '.join(allowed)}")
    sids = [source_id] if source_id else allowed
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": sids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("대상 %d건 (소스 %s)", len(rows), ", ".join(sids))
    stats: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            sid = row["source_id"]
            st = stats.setdefault(sid, {"ok": 0, "skip": 0, "fail": 0})
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    st["fail"] += 1              # 404 · 차단 · 타임아웃 → 무변경
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                got = decide(r.text, row["fetched_at"])
                if got is None:
                    st["skip"] += 1
                    log.info("발행일 못 읽음 · 무변경 %s", row["url"])
                    continue
                prefix = "[dry-run] " if dry_run else ""
                log.info("%s%s %s → %s (%s)", prefix, sid, row["published_at"], got[0], got[1])
                if not dry_run:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"p": got[0], "pr": got[1],
                                                "h": row["content_hash"]})
                st["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="발행일 복구 (멱등)")
    ap.add_argument("--source-id", default=None, help="한 소스만 대상 (스펙 §4.4 분리 실행)")
    ap.add_argument("--limit", type=int, default=None, help="대상 상한")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    return ap


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parser().parse_args()
    stats = asyncio.run(backfill(source_id=args.source_id, limit=args.limit,
                                 dry_run=args.dry_run))
    prefix = "[dry-run] " if args.dry_run else ""
    for sid, s in sorted(stats.items()):
        print(f"{prefix}{sid}: 복구 {s['ok']} · 무변경 {s['skip']} · 실패 {s['fail']}")


if __name__ == "__main__":
    main()
