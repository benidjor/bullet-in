"""fmkorea 소급 백필 — 검색 페이징으로 차단 기간 누락 글 복원 (멱등).

정기 회차는 검색 1페이지만 읽으므로, 수집이 끊겼던 기간의 글은 페이지 밖으로
밀려나 다시 닿지 않는다. 이 스크립트는 여러 페이지를 읽되 이미 적재된 제목을
빼고 신규분만 받아온다. 적재까지만 하고 번역 · 분류 · 렌더는 다음 정기 회차가
흡수한다 (번역 전 상태 노출 방지).

실행 전 `set -a; source .env; set +a` 필수 (이 프로젝트는 dotenv 미사용).
    uv run python -m bullet_in.backfill_fmkorea --pages 3 --dry-run
    uv run python -m bullet_in.backfill_fmkorea --pages 3 --limit 5
    uv run python -m bullet_in.backfill_fmkorea --pages 3
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter, persist,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

REQUEST_GAP_SEC = 1.5   # backfill_journalist 와 같은 기준 (라이브 사이트 부담 회피)
DEFAULT_PAGES = 3       # 실측 2026-07-25 — 페이지당 20건 · 2페이지가 07-18 까지 도달
MAX_POSTS = 60          # 한 회차 신규 처리 상한 (키워드 3 × 페이지당 20)

_TITLES_SQL = text(
    "SELECT title_original FROM articles WHERE source_id='fmkorea'")


def existing_titles(engine: Engine) -> set[str]:
    """이미 적재된 fmkorea 글 제목 — 어댑터에 넘길 배제 집합.
    fmkorea 행의 title_original 은 게시글 제목 그대로라 후보 제목과 직접 비교된다."""
    with engine.connect() as c:
        return {t for (t,) in c.execute(_TITLES_SQL).all() if t}


def check_page_placeholder(search_url: str, pages: int) -> None:
    """자리표시 없이 여러 페이지를 돌면 같은 URL 을 반복 접촉하게 된다 — 미리 막는다."""
    if pages > 1 and "{page}" not in search_url:
        raise SystemExit(
            "config 의 fmkorea search_url 에 {page} 자리표시가 없다 "
            "— 같은 페이지 반복 접촉 위험 (--pages 1 로 실행하거나 config 를 고칠 것)")


def resolve_keywords(config_keywords: list[dict], names: list[str] | None,
                     target: str) -> list[dict]:
    """--keyword 로 임시 키워드를 지정하면 config 의 광역 키워드 대신 그것만 쓴다.
    미지정 (None · 빈 리스트) 이면 config 그대로 — 정기 회차와 같은 동작."""
    if not names:
        return config_keywords
    return [{"keyword": n, "target": target} for n in names]


async def main(pages: int, limit: int | None, dry_run: bool, force: bool,
               keywords: list[str] | None = None, target: str = "title") -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 백필 중단")
        return
    check_page_placeholder(src["config"]["search_url"], pages)

    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 백필 중단 (접촉 없음)")
        return

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now):
        log.info("fmkorea 백필 중단 — 마지막 접촉 %s (3h 이내 · --force 로 우회)", last)
        return

    known = existing_titles(engine)
    src["config"]["search_keywords"] = resolve_keywords(
        src["config"]["search_keywords"], keywords, target)
    adapter = build_fmkorea_adapter(
        cfg, proxy, pages=pages, request_gap_sec=REQUEST_GAP_SEC,
        exclude_titles=known, max_posts=limit if limit is not None else MAX_POSTS)
    log.info("검색 키워드: %s", [k["keyword"] for k in src["config"]["search_keywords"]])

    if dry_run:
        found = await adapter.discover()
        write_last_contact(STATE_PATH, now)
        log.info("[dry-run] 기존 %d건 배제 · 신규 후보 %d건 (페이지 %d · 상한 %d)",
                 len(known), len(found), pages, adapter.max_posts)
        for title, url in found:
            print(f"  {title}  {url}")
        return

    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)     # 신규 0 이어도 접촉 스탬프
    if not raw:
        log.info("fmkorea 백필 — 신규 0건 (기존 %d건 배제 후 남은 글 없음)", len(known))
        return
    n, dup = persist(raw, mart)
    log.info("fmkorea 백필 완료 — 적재 %d · 중복 %d (번역 · 렌더는 다음 정기 회차)", n, dup)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="fmkorea 소급 백필 (검색 페이징 · 멱등)")
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                    help=f"키워드당 읽을 검색 페이지 수 (기본 {DEFAULT_PAGES})")
    ap.add_argument("--limit", type=int, default=None,
                    help="신규 글 처리 상한 (소규모 검증용)")
    ap.add_argument("--dry-run", action="store_true",
                    help="검색만 하고 글 본문을 받지 않으며 DB 에 데이터를 쓰지 않는다 (스키마 부트스트랩은 수행)")
    ap.add_argument("--force", action="store_true", help="3시간 접촉 가드 우회")
    ap.add_argument("--keyword", action="append", default=None,
                    help="검색 키워드 직접 지정 (여러 번 사용 가능) — 미지정 시 config 키워드 사용")
    ap.add_argument("--target", choices=["title", "title_content"], default="title",
                    help="--keyword 의 검색 범위 (기본 title)")
    a = ap.parse_args()
    asyncio.run(main(a.pages, a.limit, a.dry_run, a.force, a.keyword, a.target))
