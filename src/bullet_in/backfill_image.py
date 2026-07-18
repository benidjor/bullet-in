"""thumbnail_only 소스의 기존 행 image_url 백필 (1회성).

raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.
멱등 — 재실행 시 image_url IS NULL 인 행만 다시 시도한다.
대상 소스는 config 의 thumbnail_only 로 도출한다 (현재 bbc_gossip —
fmkorea 등 2h 규칙 소스가 섞이지 않는 구조).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_image --limit 5 --dry-run
    uv run python -m bullet_in.backfill_image
"""
from __future__ import annotations
import argparse, asyncio, logging, os
import httpx
from sqlalchemy import bindparam, create_engine, text
from bullet_in.adapters.meta import extract_og_image
from bullet_in.score import load_sources

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 순차 · 요청 간격 (라이브 사이트 부담 회피)

def thumbnail_source_ids(sources: dict) -> list[str]:
    return [sid for sid, s in sources.items()
            if s.get("config", {}).get("thumbnail_only")]

_SELECT_SQL = text(
    "SELECT content_hash, url FROM articles "
    "WHERE image_url IS NULL AND source_id IN :sids ORDER BY published_at DESC"
).bindparams(bindparam("sids", expanding=True))   # text() 의 IN 은 expanding 필수
_UPDATE_SQL = text("UPDATE articles SET image_url=:img WHERE content_hash=:h")

async def backfill(limit: int | None = None, dry_run: bool = False) -> dict[str, int]:
    sources = load_sources("config/sources.yaml")
    sids = thumbnail_source_ids(sources)
    stats = {"ok": 0, "fail": 0}
    if not sids:
        log.info("thumbnail_only 소스 없음 — 종료")
        return stats
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"sids": sids}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("재fetch 대상 %d건 (소스 %s)", len(rows), ", ".join(sids))
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    stats["fail"] += 1        # 404 · 타임아웃 → NULL 유지 · 재실행 가능
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                img = extract_og_image(r.text)
                if not img:
                    stats["fail"] += 1
                    log.warning("og:image 부재 %s", row["url"])
                    continue
                if dry_run:
                    log.info("[dry-run] %s → %s", row["url"], img)
                else:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"img": img, "h": row["content_hash"]})
                stats["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="thumbnail_only 소스 image_url 백필 (멱등)")
    ap.add_argument("--limit", type=int, default=None, help="재fetch 대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    args = ap.parse_args()
    stats = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    print(f"성공 {stats['ok']} · 실패 {stats['fail']}")

if __name__ == "__main__":
    main()
