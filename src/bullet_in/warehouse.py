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

import pyarrow as pa

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


# information_schema.DATA_TYPE 이 주는 이름에서 Arrow 타입으로.
# 모르는 이름은 문자열로 떨어뜨린다 — 새 컬럼 하나 때문에 적재가 죽으면 안 된다
# (`schema.sql` 이 ALTER 로 컬럼을 계속 더하는 저장소다).
_TYPE_MAP = {
    "bigint": pa.int64(), "int": pa.int32(), "mediumint": pa.int32(),
    "smallint": pa.int16(), "tinyint": pa.int8(),
    "float": pa.float64(), "double": pa.float64(), "decimal": pa.float64(),
    "datetime": pa.timestamp("us", tz="UTC"),
    "timestamp": pa.timestamp("us", tz="UTC"),
    "date": pa.timestamp("us", tz="UTC"),
}

# 적재 시각과 그 날짜. 원본에 없는 열이라 이름 앞에 밑줄을 둬 원본 컬럼과 갈라 놓는다.
# 날짜를 따로 두는 것은 스냅샷을 그 값으로 갈아 끼우기 때문이다 — 파티션 변환을 쓰면
# 카탈로그마다 지원이 갈리므로 문자열 열 하나로 단순하게 간다.
LOADED_AT = "_loaded_at"
LOADED_DATE = "_loaded_date"

COLUMN_SQL = (
    "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS"
    " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    " ORDER BY ORDINAL_POSITION")


def arrow_schema(columns: list[tuple[str, str]]) -> pa.Schema:
    """(컬럼명, MariaDB DATA_TYPE) 목록에서 Arrow 스키마를 만든다."""
    fields = [pa.field(name, _TYPE_MAP.get(dtype.lower(), pa.string()))
              for name, dtype in columns]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)


def to_arrow(rows: list[dict], schema: pa.Schema,
             loaded_at: datetime) -> pa.Table:
    """행 목록을 스키마대로 눕힌다. 없는 컬럼은 널이다.

    MariaDB 의 DATETIME 은 시간대가 없는 값으로 오는데 스키마는 UTC 를 붙여 둔다.
    pyarrow 가 그 값을 UTC 로 간주해 받으므로 저장된 값이 UTC 인 한 정확하다
    (이 저장소는 `mart.db_now()` 로 UTC 를 넣는다). 로컬 시각을 저장하는 표가
    생기면 여기서 조용히 9시간이 어긋나므로 그때는 변환을 넣어야 한다.
    """
    cols = {}
    for f in schema:
        if f.name == LOADED_AT:
            cols[f.name] = pa.array([loaded_at] * len(rows), type=f.type)
        elif f.name == LOADED_DATE:
            cols[f.name] = pa.array([loaded_at.date().isoformat()] * len(rows),
                                    type=f.type)
        else:
            cols[f.name] = pa.array([r.get(f.name) for r in rows], type=f.type)
    return pa.table(cols, schema=schema)
