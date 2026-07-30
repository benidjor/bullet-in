"""본문 빈 fmkorea 행에 게시글 본문 채우기 (1회성 · 멱등).

원문 기사 URL 재수집은 26건 중 1건만 성공했다 (스펙 §6.2). 게시글 본문이 유일하게
남은 재료인데, 게시글 URL 은 저장되지 않으므로 검색 페이징으로 후보를 모아 저장된
제목과 정확히 일치하는 것만 골라 받는다.

채운 행은 번역 4필드를 NULL 로 되돌려 다음 회차 enrich 가 본문 기반으로 재생성하게
한다 (backfill_body 와 같은 멱등 패턴).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
라이브 사이트에 접촉하므로 출력은 tee 로 남기고 재실행하지 않는다.
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 --dry-run 2>&1 | tee ~/bf.log
    uv run python -m bullet_in.backfill_fmkorea_body --pages 3 2>&1 | tee ~/bf.log
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from pathlib import Path

import httpx
import yaml
from sqlalchemy import create_engine, text

from bullet_in.adapters.fmkorea import (_body_text, _is_repost_blocked,
                                        extract_body_journalist,
                                        strip_publish_datetime)
from bullet_in.backfill_fmkorea import check_page_placeholder
from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5      # 라이브 사이트 부담 회피 (다른 백필과 같은 기준)
MAX_POSTS = 120            # 검색 후보 상한 — 대상 제목을 놓치지 않을 만큼 넉넉히
POST_BODY_LEVEL = 1

_SELECT_SQL = text(
    "SELECT content_hash, title_original FROM articles "
    "WHERE source_id='fmkorea' AND COALESCE(body_source,'')='' "
    "ORDER BY published_at DESC")
# journalist 는 이미 값이 있으면 보존한다 (말머리 값 우선 · 스펙 §4.1).
# 번역 4필드는 NULL 로 되돌려 다음 회차가 본문 기반으로 재생성한다.
_UPDATE_SQL = text(
    "UPDATE articles SET body_source=:b, body_level=:lv, "
    "journalist=COALESCE(journalist, :j), "
    "title_ko=NULL, summary_ko=NULL, summary3_ko=NULL, body_ko=NULL "
    "WHERE content_hash=:h")


def match_targets(targets: dict[str, str],
                  found: list[tuple[str, str]]) -> dict[str, str]:
    """{content_hash: 제목} × [(제목, 글 URL)] → {content_hash: 글 URL}.
    제목 완전 일치만 인정한다 — 부분 일치를 허용하면 다른 글의 본문이 들어간다."""
    by_title = {t.strip(): u for t, u in found}
    return {h: by_title[title.strip()] for h, title in targets.items()
            if title.strip() in by_title}


def row_update(html: str, body_selector: str) -> dict | None:
    """게시글 HTML → 저장할 body_source · body_level · journalist.
    퍼가기 금지거나 본문이 비면 None — 행을 건드리지 않고 재실행 몫으로 남긴다."""
    if _is_repost_blocked(html):
        return None
    body = strip_publish_datetime(_body_text(html, body_selector))
    if not body:
        return None
    return {"body": body, "body_level": POST_BODY_LEVEL,
            "journalist": extract_body_journalist(body)}


async def backfill(pages: int = 3, limit: int | None = None,
                   dry_run: bool = False, force: bool = False) -> dict[str, int]:
    stats = {"target": 0, "matched": 0, "filled": 0, "blocked": 0, "failed": 0}
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    check_page_placeholder(src["config"]["search_url"], pages)
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 백필 중단 (접촉 없음)")
        return stats

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    if not force and not should_supplement(max(marks) if marks else None, now):
        log.info("fmkorea 백필 중단 — 3h 이내 접촉 (--force 로 우회)")
        return stats

    with engine.connect() as c:
        targets = {r["content_hash"]: r["title_original"]
                   for r in c.execute(_SELECT_SQL).mappings().all()}
    if limit:
        targets = dict(list(targets.items())[:limit])
    stats["target"] = len(targets)
    log.info("본문 빈 fmkorea 행 %d건", len(targets))
    if not targets:
        return stats

    # exclude_titles 를 비워야 이미 적재된 글이 후보에 남는다 (정기 회차와 반대 방향).
    adapter = build_fmkorea_adapter(cfg, proxy, pages=pages,
                                    request_gap_sec=REQUEST_GAP_SEC,
                                    exclude_titles=set(),
                                    max_posts=MAX_POSTS)
    found = await adapter.discover()
    write_last_contact(STATE_PATH, now)     # 후보 0건이어도 접촉 스탬프
    log.info("검색 후보 %d건", len(found))
    matched = match_targets(targets, found)
    stats["matched"] = len(matched)
    log.info("제목 일치 %d/%d건", len(matched), len(targets))

    async with adapter._client() as c:
        for i, (h, post_url) in enumerate(matched.items()):
            if i:
                await asyncio.sleep(REQUEST_GAP_SEC)
            try:
                r = await c.get(post_url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                stats["failed"] += 1
                log.warning("글 fetch 실패 %s: %r", post_url, e)
                continue
            upd = row_update(r.text, adapter.body_selector)
            if upd is None:
                stats["blocked"] += 1
                log.info("퍼가기 금지 또는 본문 없음 — 건너뜀 %s", post_url)
                continue
            if dry_run:
                log.info("[dry-run] %s → 본문 %d자 · 기자 %s",
                         h[:8], len(upd["body"]), upd["journalist"])
            else:
                with engine.begin() as conn:
                    conn.execute(_UPDATE_SQL, {"b": upd["body"], "lv": upd["body_level"],
                                               "j": upd["journalist"], "h": h})
            stats["filled"] += 1
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="본문 빈 fmkorea 행 본문 채우기 (멱등)")
    ap.add_argument("--pages", type=int, default=3, help="검색 페이지 수")
    ap.add_argument("--limit", type=int, default=None, help="대상 상한 (드라이런 검증용)")
    ap.add_argument("--dry-run", action="store_true", help="DB 쓰기 없이 결과만 로깅")
    ap.add_argument("--force", action="store_true", help="3h 접촉 간격 가드 우회")
    args = ap.parse_args()
    s = asyncio.run(backfill(pages=args.pages, limit=args.limit,
                             dry_run=args.dry_run, force=args.force))
    print(f"대상 {s['target']} · 일치 {s['matched']} · 채움 {s['filled']} "
          f"· 금지·본문없음 {s['blocked']} · 실패 {s['failed']}")


if __name__ == "__main__":
    main()
