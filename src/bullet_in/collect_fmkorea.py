from __future__ import annotations
import argparse, asyncio, logging, math, os, socket
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from pymongo import MongoClient
from bullet_in.adapters.fmkorea import FmkoreaAdapter
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.models import RawItem
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

GAP_HOURS = 3.0
STATE_PATH = Path.home() / ".bullet-in" / "fmkorea_last_contact"

# 릴레이가 맥 전원에 매여 있어 접촉이 끊긴다 (안건 2ι). 다시 붙을 때 검색 1페이지만
# 읽으면 그 사이 밀려난 글이 2페이지로 넘어가 다음 회차에도 안 보인다 — 지연이 아니라
# 손실이다. 공백에 비례해 페이지를 넓히되 상한을 둔다 (한 회차에 다 못 가져오면 다음
# 회차가 이어받는다). 글번호가 시간순이고 content_hash · URL UNIQUE 라 재수집은
# 중복을 안 만든다.
CATCHUP_GAP_HOURS = 12.0        # 이 시간을 넘길 때마다 페이지 하나를 더 읽는다
MAX_CATCHUP_PAGES = 3           # 실측 2026-07-25 — 페이지당 20건 · 3페이지가 약 2주를 덮는다
CATCHUP_REQUEST_GAP_SEC = 1.5   # backfill 과 같은 기준 (라이브 사이트 부담 · 430 회피)
CATCHUP_MAX_POSTS = 45          # 페이지를 넓혀도 상한이 15 면 더 가져오지 못한다


def pages_for_gap(gap_hours: float) -> int:
    """접촉 공백에 비례해 읽을 검색 페이지 수 — 정상 주기면 1 (정기 회차와 같다)."""
    if gap_hours <= CATCHUP_GAP_HOURS:
        return 1
    if gap_hours >= CATCHUP_GAP_HOURS * MAX_CATCHUP_PAGES:
        return MAX_CATCHUP_PAGES        # 접촉 기록이 아예 없으면 (inf) 여기로 온다
    return int(math.ceil(gap_hours / CATCHUP_GAP_HOURS))


def catchup_options(gap_hours: float) -> dict:
    """공백에 따른 어댑터 인자. 정상 주기면 빈 dict — 인자 하나도 안 바뀐다."""
    pages = pages_for_gap(gap_hours)
    if pages == 1:
        return {}
    return {"pages": pages, "request_gap_sec": CATCHUP_REQUEST_GAP_SEC,
            "max_posts": CATCHUP_MAX_POSTS}


_TITLES_SQL = text(
    "SELECT title_original FROM articles WHERE source_id='fmkorea'")


def existing_titles(engine: Engine) -> set[str]:
    """이미 적재된 fmkorea 글 제목 — 어댑터에 넘길 배제 집합.
    fmkorea 행의 title_original 은 게시글 제목 그대로라 후보 제목과 직접 비교된다."""
    with engine.connect() as c:
        return {t for (t,) in c.execute(_TITLES_SQL).all() if t}

def should_supplement(last_contact: datetime | None, now: datetime,
                      gap_hours: float = GAP_HOURS) -> bool:
    """fmkorea 마지막 접촉에서 gap_hours 이상 지났으면 보충 수집.
    기록이 없으면 True. now · last_contact 는 같은 시계 (UTC) 여야 한다."""
    if last_contact is None:
        return True
    return now - last_contact >= timedelta(hours=gap_hours)

def read_last_contact(path: Path) -> datetime | None:
    """접촉 스탬프 파일 (ISO 8601) 을 읽는다. 없거나 못 읽으면 None."""
    try:
        return datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return None

def write_last_contact(path: Path, now: datetime) -> None:
    """접촉 시각 스탬프 — 신규 0건이어도 접촉했으면 기록한다 (가드 fail-open 방지)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(now.isoformat())

def tunnel_alive(proxy_url: str, timeout: float = 3.0) -> bool:
    """SOCKS 터널 포트 연결성 확인 — fmkorea 접촉 없이 TCP connect 만 시도."""
    u = urlparse(proxy_url)
    try:
        with socket.create_connection((u.hostname, u.port), timeout=timeout):
            return True
    except OSError:
        return False


def build_fmkorea_adapter(cfg: dict, proxy: str | None, *, pages: int = 1,
                          request_gap_sec: float = 0.0,
                          exclude_titles: set[str] | None = None,
                          max_posts: int | None = None,
                          search_keywords: list[dict] | None = None,
                          round_robin_start: int = 0) -> FmkoreaAdapter:
    """config 에서 fmkorea 소스 블록을 읽어 어댑터를 만든다 (factory 와 동일 인자).
    선택 인자는 백필 회차 전용이고, 기본값이면 정기 회차와 같은 어댑터가 된다."""
    s = next(x for x in cfg["sources"] if x["source_id"] == "fmkorea")
    c = s["config"]
    return FmkoreaAdapter(
        "fmkorea", c["search_url"], search_keywords if search_keywords is not None else c["search_keywords"],
        item_selector=c.get("item_selector", "a.hx"),
        base_url=c.get("base_url", "https://www.fmkorea.com"),
        body_selector=c.get("body_selector", ".xe_content"),
        max_posts=max_posts if max_posts is not None else c.get("max_posts", 15),
        proxy=proxy, pages=pages, request_gap_sec=request_gap_sec,
        exclude_titles=exclude_titles, round_robin_start=round_robin_start)


def persist(raw: list[RawItem], mart: MartStore) -> tuple[int, int, int]:
    """수집 결과를 raw (Mongo) · mart (MariaDB) 에 적재한다.
    번역 · 분류 · 렌더는 하지 않는다 — 다음 정기 회차가 흡수한다."""
    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or "", canonical_url(it.url))
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    return mart.upsert(arts), stats["dup_count"], stats["blocked_count"]


async def main(force: bool = False) -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 보충 수집 스킵")
        return
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 보충 수집 스킵 (스탬프 없음 · 다음 주기 재시도)")
        return

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()

    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now):
        log.info("fmkorea 보충 수집 스킵 — 마지막 접촉 %s (3h 이내)", last)
        return

    gap = (now - last).total_seconds() / 3600 if last else float("inf")
    opts = catchup_options(gap)
    if opts:
        # 밀린 글을 실제로 건지려면 이미 적재된 글이 상한을 먹지 않아야 한다.
        # 정상 주기에는 넘기지 않는다 — 재수집이 본문 등급을 올리는 경로가 살아 있다.
        opts["exclude_titles"] = existing_titles(engine)
        log.info("fmkorea 따라잡기 — 공백 %.1fh · 검색 %d페이지 · 기존 %d건 배제",
                 gap, opts["pages"], len(opts["exclude_titles"]))
    adapter = build_fmkorea_adapter(cfg, proxy, **opts)
    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)  # 신규 0 이어도 접촉 스탬프 (15분 재접촉 방지)
    if not raw:
        log.info("fmkorea 보충 수집 — 신규 0 (새 글 없음 · 전부 스킵)")
        return
    n, dup, blocked = persist(raw, mart)
    log.info("fmkorea 보충 수집 완료 — 적재 %d · 동일 내용 생략 %d · 기존 기사 유지 %d "
             "(번역 · 렌더는 다음 정기 회차)", n, dup, blocked)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="중복 가드 무시하고 즉시 수집")
    asyncio.run(main(ap.parse_args().force))
