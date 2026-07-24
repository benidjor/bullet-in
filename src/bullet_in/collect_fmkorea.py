from __future__ import annotations
import argparse, asyncio, logging, os, socket
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import yaml
from sqlalchemy import create_engine
from pymongo import MongoClient
from bullet_in.adapters.fmkorea import FmkoreaAdapter
from bullet_in.canonical import content_hash, canonical_url
from bullet_in.pipeline import to_articles
from bullet_in.score import load_sources
from bullet_in.credibility import load_registry
from bullet_in.storage.mongo import RawStore
from bullet_in.storage.mariadb import MartStore

log = logging.getLogger(__name__)

GAP_HOURS = 3.0
STATE_PATH = Path.home() / ".bullet-in" / "fmkorea_last_contact"

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


def build_fmkorea_adapter(cfg: dict, proxy: str | None) -> FmkoreaAdapter:
    """config 에서 fmkorea 소스 블록을 읽어 어댑터를 만든다 (factory 와 동일 인자)."""
    s = next(x for x in cfg["sources"] if x["source_id"] == "fmkorea")
    c = s["config"]
    return FmkoreaAdapter(
        "fmkorea", c["search_url"], c["search_keywords"],
        item_selector=c.get("item_selector", "a.hx"),
        base_url=c.get("base_url", "https://www.fmkorea.com"),
        body_selector=c.get("body_selector", ".xe_content"),
        max_posts=c.get("max_posts", 15), proxy=proxy)


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

    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
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

    adapter = build_fmkorea_adapter(cfg, proxy)
    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)  # 신규 0 이어도 접촉 스탬프 (15분 재접촉 방지)
    if not raw:
        log.info("fmkorea 보충 수집 — 신규 0 (새 글 없음 · 전부 스킵)")
        return

    for it in raw:
        it.content_hash = content_hash(
            it.raw_payload.get("title") or "", canonical_url(it.url))
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    RawStore(mongo).insert_many(raw)

    arts, stats = to_articles(raw, sources, seen=mart.seen_map(), registry=registry)
    n = mart.upsert(arts)
    # 번역 · 분류 · 렌더는 하지 않는다 — 다음 정기 회차가 흡수 (번역 전 상태 노출 방지)
    log.info("fmkorea 보충 수집 완료 — 적재 %d · 중복 %d (번역 · 렌더는 다음 정기 회차)",
             n, stats["dup_count"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="중복 가드 무시하고 즉시 수집")
    asyncio.run(main(ap.parse_args().force))
