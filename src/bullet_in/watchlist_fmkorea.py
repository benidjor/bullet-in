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
