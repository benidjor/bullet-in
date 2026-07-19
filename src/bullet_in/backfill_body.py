"""풀 수집 전환 소스의 기존 행 본문 백필 (1회성).

raw 저장소에 원본 HTML 이 없어 기사 URL 재fetch 가 유일한 경로다.
추출은 HtmlAdapter 풀 수집 경로와 같은 함수 · 규칙을 쓴다 (규칙 이중화 방지).
본문이 채워진 행은 title_ko 를 NULL 로 되돌려 다음 enrich 가 본문 기반으로
번역 · 요약을 재생성하게 한다 (transfer_stage 전건 재분류 런북과 같은 멱등 패턴).
멱등 — 재실행 시 body_source 가 비어 있는 행만 다시 시도한다.

대상 소스는 --source 로 명시한다 — config 파생으로 뽑으면 body_source 빈 행을 가진
football.london (재수집 금지) · fmkorea (2h 규칙) 가 섞일 수 있어 명시 인자 채택.

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_body --source bbc_gossip --limit 5 --dry-run
    uv run python -m bullet_in.backfill_body --source bbc_gossip
"""
from __future__ import annotations
import argparse, asyncio, json, logging, os
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, text
from bullet_in.adapters.meta import extract_body_images, extract_og_image
from bullet_in.score import load_sources

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 순차 · 요청 간격 (라이브 사이트 부담 회피)

def body_update(html: str, url: str, body_selector: str) -> dict | None:
    """재fetch 한 기사 HTML → 저장할 body_source · images_json · image_url.
    본문 미추출 (셀렉터 불일치 등) 은 None — 행을 건드리지 않고 재실행 몫."""
    el = BeautifulSoup(html, "html.parser").select_one(body_selector)
    body = el.get_text(" ", strip=True) if el else ""
    if not body:
        return None
    images = extract_body_images(html, body_selector, base_url=url)
    return {"body": body,
            "images_json": json.dumps(images) if images else None,
            "image": extract_og_image(html)}

_SELECT_SQL = text(
    "SELECT content_hash, url FROM articles "
    "WHERE source_id=:s AND (body_source IS NULL OR body_source='') "
    "ORDER BY published_at DESC")
# image_url 은 이미 채워진 값 (thumbnail 백필분) 을 보존하고 빈 행만 채운다.
_UPDATE_SQL = text(
    "UPDATE articles SET body_source=:b, images_json=:ij, "
    "image_url=COALESCE(image_url, :img), title_ko=NULL WHERE content_hash=:h")

async def backfill(source_id: str, limit: int | None = None,
                   dry_run: bool = False) -> dict[str, int]:
    sources = load_sources("config/sources.yaml")
    src = sources.get(source_id) or {}
    body_selector = src.get("config", {}).get("body_selector")
    stats = {"ok": 0, "fail": 0}
    if src.get("adapter") != "html" or not body_selector:
        log.error("%s: html 어댑터 + body_selector 소스가 아님 — 종료", source_id)
        return stats
    engine = create_engine(os.environ["MARIADB_URL"])
    with engine.connect() as c:
        rows = [dict(r) for r in
                c.execute(_SELECT_SQL, {"s": source_id}).mappings().all()]
    if limit:
        rows = rows[:limit]
    log.info("재fetch 대상 %d건 (소스 %s)", len(rows), source_id)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "bullet-in/0.1"}) as client:
        for i, row in enumerate(rows):
            try:
                try:
                    r = await client.get(row["url"])
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    stats["fail"] += 1        # 404 · 타임아웃 → 빈 값 유지 · 재실행 가능
                    log.warning("fetch 실패 %s: %r", row["url"], e)
                    continue
                upd = body_update(r.text, row["url"], body_selector)
                if upd is None:
                    stats["fail"] += 1
                    log.warning("본문 미추출 %s", row["url"])
                    continue
                if dry_run:
                    log.info("[dry-run] %s → 본문 %d자 · 인라인 %s", row["url"],
                             len(upd["body"]), upd["images_json"] or "없음")
                else:
                    with engine.begin() as c:
                        c.execute(_UPDATE_SQL, {"b": upd["body"], "ij": upd["images_json"],
                                                "img": upd["image"], "h": row["content_hash"]})
                stats["ok"] += 1
            finally:
                if i < len(rows) - 1:
                    await asyncio.sleep(REQUEST_GAP_SEC)
    return stats

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="풀 수집 전환 소스 본문 백필 (멱등)")
    ap.add_argument("--source", required=True, help="대상 source_id (명시 필수)")
    ap.add_argument("--limit", type=int, default=None, help="재fetch 대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    args = ap.parse_args()
    stats = asyncio.run(backfill(args.source, limit=args.limit, dry_run=args.dry_run))
    print(f"성공 {stats['ok']} · 실패 {stats['fail']}")

if __name__ == "__main__":
    main()
