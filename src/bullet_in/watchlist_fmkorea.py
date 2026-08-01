"""링크 선수 워치리스트 배치 — 활성 이적축 ko_name 로테이션 검색 (스펙 2026-08-01).

정기 회차와 분리된 전용 배치로, 적재까지만 하고 (Gemini 호출 없음)
번역 · 분류 · 렌더는 다음 정기 회차가 흡수한다.
"""
from __future__ import annotations
import argparse, asyncio, logging, os
from pathlib import Path

import yaml
from sqlalchemy import create_engine

from bullet_in.collect_fmkorea import (STATE_PATH, build_fmkorea_adapter, persist,
                                       read_last_contact, should_supplement,
                                       tunnel_alive, write_last_contact)
from bullet_in.storage.mariadb import MartStore
from bullet_in.storage.players import PlayerStore

log = logging.getLogger(__name__)

CURSOR_PATH = Path.home() / ".bullet-in" / "watchlist_cursor"
GAP_HOURS = 1.0      # 최근 접촉 60분 이내면 스킵 (스펙 §3.1)
SLICE_SIZE = 10      # 배치당 검색 인원 (보수안)
MAX_POSTS = 5        # 배치당 fetch 상한 (보수안)


def read_cursor(path: Path) -> int | None:
    """마지막 검색 선수 id — 없거나 손상이면 None (처음부터 재시작)."""
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def write_cursor(path: Path, player_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(player_id))


def next_slice(ids: list[int], cursor: int | None,
               size: int = SLICE_SIZE) -> list[int]:
    """커서 다음 id 부터 size 명 순환 슬라이스.
    커서 id 가 명단에서 사라졌으면 그다음 id 부터 · 명단이 size 이하면 전원 1회씩."""
    if not ids:
        return []
    start = 0
    if cursor is not None:
        start = next((i for i, pid in enumerate(ids) if pid > cursor), 0)
    return [ids[(start + k) % len(ids)] for k in range(min(size, len(ids)))]


def build_keywords(names: list[str]) -> list[dict]:
    """ko_name → fmkorea 제목 검색 키워드 (스펙 §3.1)."""
    return [{"keyword": n, "target": "title"} for n in names]


def next_cursor(slice_ids: list[int], search_failures: int) -> int | None:
    """전진할 커서 값 — 검색 실패가 있으면 None (같은 슬라이스 재시도 · 스펙 §6)."""
    if not slice_ids or search_failures:
        return None
    return slice_ids[-1]


async def main(dry_run: bool = False, force: bool = False) -> None:
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    src = next(s for s in cfg["sources"] if s["source_id"] == "fmkorea")
    if not src.get("enabled", True):
        log.info("fmkorea 비활성 (enabled: false) — 워치리스트 배치 스킵")
        return
    proxy = os.environ.get("FMKOREA_PROXY")
    if proxy and not tunnel_alive(proxy):
        log.info("fmkorea 터널 미접속 — 워치리스트 배치 스킵 (커서 무전진 · 스탬프 무기록)")
        return

    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    pstore = PlayerStore(engine)

    now = mart.db_now()
    marks = [t for t in (read_last_contact(STATE_PATH),
                         mart.source_watermarks().get("fmkorea")) if t]
    last = max(marks) if marks else None
    if not force and not should_supplement(last, now, gap_hours=GAP_HOURS):
        log.info("워치리스트 배치 스킵 — 마지막 fmkorea 접촉 %s (60분 이내)", last)
        return

    players = pstore.active_link_players()
    if not players:
        log.info("활성 링크 선수 0명 — 검색 없이 정상 종료 (시장 폐장 휴면)")
        return
    ids = [pid for pid, _ in players]
    names = dict(players)
    slice_ids = next_slice(ids, read_cursor(CURSOR_PATH))
    kws = build_keywords([names[pid] for pid in slice_ids])

    adapter = build_fmkorea_adapter(cfg, proxy, search_keywords=kws,
                                    max_posts=MAX_POSTS)
    # 무관 글 필터 주입 — 정기 회차 (run.py) 와 같은 인정 집합 (스펙 §3.2).
    # build_fmkorea_adapter 는 변경 범위가 인자 1개로 묶여 있어 (스펙 §3.4)
    # 생성 후 공개 속성에 대입한다.
    adapter.relevance_terms = src["config"].get("relevance_terms") or []
    adapter.player_names = pstore.confirmed_ko_names()

    raw = await adapter.fetch()
    write_last_contact(STATE_PATH, now)   # 신규 0건 · 전량 탈락도 접촉은 기록 (스펙 §6)

    if dry_run:
        log.info("[dry-run] 검색 %d명 · 필터 통과 %d · 탈락 %d · 검색 실패 %d — 적재 없음",
                 len(slice_ids), len(raw), adapter.relevance_dropped,
                 adapter.search_failures)
        for it in raw:
            log.info("[dry-run] 통과: %s", it.raw_payload.get("title"))
        return

    n = dup = blocked = 0
    if raw:
        n, dup, blocked = persist(raw, mart)
    cur = next_cursor(slice_ids, adapter.search_failures)
    if cur is not None:
        write_cursor(CURSOR_PATH, cur)
    log.info("워치리스트 배치 완료 — 검색 %d명 · 적재 %d · 동일 내용 생략 %d · "
             "기존 기사 유지 %d · 필터 탈락 %d · 검색 실패 %d · 커서 %s",
             len(slice_ids), n, dup, blocked, adapter.relevance_dropped,
             adapter.search_failures, cur if cur is not None else "유지")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="적재 없이 검색 · 필터 결과만 출력 (커서 무전진)")
    ap.add_argument("--force", action="store_true", help="최근 접촉 가드 무시")
    a = ap.parse_args()
    asyncio.run(main(dry_run=a.dry_run, force=a.force))
