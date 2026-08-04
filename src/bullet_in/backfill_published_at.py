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
