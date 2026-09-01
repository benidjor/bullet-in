"""운영 마트의 이력을 GCS 위 Iceberg 테이블로 남긴다.

설계 = docs/superpowers/specs/2026-09-02-history-lakehouse-design.md

회차 안에서 돌지 않는다 — 별도 타이머가 부른다.
게이트가 배포를 막는 자리라 그 위에 네트워크와 인증을 더 얹지 않는다.

새 패키지를 최소로 쓴다 — 자격은 `google-auth` 가 만들고 PyIceberg 가 그것을 받는다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

NAMESPACE = "mart_history"

# 스냅샷을 며칠까지 매일 남기나. 이후는 주 1회만 남긴다 (설계 §3.4).
SNAPSHOT_DAILY_DAYS = 90
# Iceberg 스냅샷을 며칠까지 남기나. metadata.json 1 MB 한도 때문에 필요하다.
EXPIRE_SNAPSHOT_DAYS = 7
# 컴팩션이 이 크기 아래인 데이터 파일만 합친다.
COMPACT_TARGET_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class LoadPlan:
    """한 번의 적재 대상 하나."""
    table: str      # Iceberg 테이블 이름 (네임스페이스 제외)
    source: str     # MariaDB 쪽 이름
    mode: str       # changes · snapshot · append


TABLES = ("articles_changes", "articles_snapshot", "players_snapshot",
          "article_players_snapshot", "ops_daily")

_DAILY = (
    LoadPlan("articles_snapshot", "articles", "snapshot"),
    LoadPlan("players_snapshot", "players", "snapshot"),
    LoadPlan("article_players_snapshot", "article_players", "snapshot"),
    LoadPlan("ops_daily", "ops", "append"),
)
_EVERY_RUN = (LoadPlan("articles_changes", "articles", "changes"),)


# --- 판정 (부수효과 없음) ---------------------------------------------------

def plans_for(now: datetime,
              last_daily_at: datetime | None) -> tuple[LoadPlan, ...]:
    """이 시각에 적재할 대상.

    변경분은 부를 때마다 뜬다.
    하루 1회짜리는 마지막으로 뜬 날이 오늘이 아닐 때만 붙는다 — 날짜로 가르는 것은
    타이머가 밀리거나 (`Persistent=true` 로 밀린 회차가 몰려 실행된다) 손으로 한 번 더
    돌려도 같은 날 두 번 뜨지 않게 하기 위해서다.
    """
    plans = list(_EVERY_RUN)
    if last_daily_at is None or last_daily_at.date() != now.date():
        plans.extend(_DAILY)
    return tuple(plans)
