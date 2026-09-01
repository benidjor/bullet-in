"""운영 마트의 이력을 GCS 위 Iceberg 테이블로 남긴다.

설계 = docs/superpowers/specs/2026-09-02-history-lakehouse-design.md

회차 안에서 돌지 않는다 — 별도 타이머가 부른다.
게이트가 배포를 막는 자리라 그 위에 네트워크와 인증을 더 얹지 않는다.

새 패키지를 최소로 쓴다 — 자격은 `google-auth` 가 만들고 PyIceberg 가 그것을 받는다.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
from sqlalchemy import text

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


# 스냅샷을 뜰 수 있는 표. 이름을 SQL 에 문자열로 박는 자리라 목록으로 가둔다.
SNAPSHOT_SOURCES = ("articles", "players", "article_players")


def changes_sql(watermark: datetime | None) -> tuple[str, dict]:
    """워터마크 이후 바뀐 기사 행을 가져오는 조회.

    경계를 초과로 둔다 — 같은 시각의 행을 다시 가져오면 이력에 같은 값이 두 번 쌓인다.
    `updated_at` 은 `ON UPDATE CURRENT_TIMESTAMP` 라 초 단위이고, 한 초 안에 여러 행이
    바뀌면 그중 일부를 놓칠 수 있다. 놓친 것은 하루 1회 전량 스냅샷이 받아 준다.
    """
    if watermark is None:
        return "SELECT * FROM articles", {}
    return "SELECT * FROM articles WHERE updated_at > :wm", {"wm": watermark}


def snapshot_sql(table: str) -> str:
    """전량 스냅샷 조회."""
    if table not in SNAPSHOT_SOURCES:
        raise ValueError(f"스냅샷 대상이 아니다 — {table}")
    return f"SELECT * FROM {table}"


def next_watermark(rows: list[dict],
                   previous: datetime | None) -> datetime | None:
    """이번에 가져온 행에서 다음 워터마크를 고른다.

    행이 없으면 그대로 둔다 — 앞으로 당기면 그 사이에 바뀐 행을 영영 못 본다.
    """
    seen = [r["updated_at"] for r in rows if r.get("updated_at")]
    return max(seen) if seen else previous


def snapshot_dates_to_drop(dates: list[date], today: date) -> list[date]:
    """전량 스냅샷 중 지울 날짜.

    90일 안쪽은 매일 남기고, 그보다 오래된 것은 월요일만 남긴다.
    안 지우면 `articles_snapshot` 이 하루 3.0 MiB 씩 쌓여 약 414일에 GCS 무료
    5 GB 를 채운다 (설계 §3.4).
    """
    cutoff = today - timedelta(days=SNAPSHOT_DAILY_DAYS)
    return sorted(d for d in dates if d < cutoff and d.isoweekday() != 1)


def expire_before(now: datetime) -> datetime:
    """이 시각보다 오래된 Iceberg 스냅샷은 만료 대상.

    부피 때문이 아니라 `metadata.json` 이 1 MB 로 막혀 있어서 한다.
    스냅샷 하나가 약 1,015 바이트를 더하므로 그냥 두면 약 124일에 커밋이 실패한다.
    """
    return now - timedelta(days=EXPIRE_SNAPSHOT_DAYS)


def files_to_compact(sizes: dict[str, int]) -> list[str]:
    """합칠 데이터 파일 목록. 둘 미만이면 빈 목록이다.

    회차마다 조금씩 쓰면 Parquet 압축이 안 들어 행당 부피가 6.15배가 된다
    (실측 19,430 B 대 3,160 B · 설계 §2.5).
    """
    small = [p for p, n in sizes.items() if n < COMPACT_TARGET_BYTES]
    return small if len(small) >= 2 else []


# --- 카탈로그 (부수효과) ----------------------------------------------------

# 테이블 생성 속성. 안 주면 커밋마다 `metadata.json` 이 하나씩 영구히 쌓인다
# (실측 — 켠 테이블은 커밋 10회 뒤 4개가 남고 안 켠 테이블은 41회 뒤 42개가 남았다).
# 하루 8회 커밋이면 한 해에 객체 8,760개가 그냥 늘어난다.
TABLE_PROPERTIES = {
    "write.metadata.delete-after-commit.enabled": "true",
    "write.metadata.previous-versions-max": "5",
}


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"환경변수 {name} 가 필요하다")
    return value


def load_catalog():
    """이력 카탈로그에 붙는다.

    `ICEBERG_CATALOG_URI` 가 있으면 그것으로 (운영 = Lakehouse REST), 없으면
    `ICEBERG_LOCAL_WAREHOUSE` 아래 SQLite 카탈로그로 붙는다 (개발 · 테스트).
    같은 코드가 둘 다 다뤄야 개발과 운영이 갈리지 않는다.

    이름이 바뀌었지만 주소는 그대로다 — 2026-04-20 에 BigLake 가 Lakehouse 로,
    BigLake metastore 가 Lakehouse runtime catalog 로 이름이 바뀌었고
    API 주소와 IAM 이름은 `biglake` 를 그대로 쓴다.

    `auth` 는 문자열이 아니라 딕셔너리다 — PyIceberg 가 `auth["type"]` 을 읽으므로
    문자열을 주면 AttributeError 로 죽는다.
    """
    from pyiceberg.catalog.rest import RestCatalog
    from pyiceberg.catalog.sql import SqlCatalog

    uri = os.environ.get("ICEBERG_CATALOG_URI")
    if uri:
        return RestCatalog("bullet_in", **{
            "uri": uri,
            "warehouse": _require_env("ICEBERG_WAREHOUSE"),
            "auth": {
                "type": "google",
                "google": {"scopes": ["https://www.googleapis.com/auth/cloud-platform"]},
            },
        })
    local = Path(_require_env("ICEBERG_LOCAL_WAREHOUSE"))
    local.mkdir(parents=True, exist_ok=True)
    return SqlCatalog("bullet_in", **{
        "uri": f"sqlite:///{local}/catalog.db",
        "warehouse": f"file://{local}",
    })


def ensure_namespace(catalog) -> None:
    """네임스페이스를 멱등하게 만든다."""
    from pyiceberg.exceptions import NamespaceAlreadyExistsError
    try:
        catalog.create_namespace(NAMESPACE)
    except NamespaceAlreadyExistsError:
        pass


def ensure_table(catalog, name: str, schema):
    """테이블을 멱등하게 만들고 돌려준다.

    원본에 컬럼이 늘어나는 저장소라 (`schema.sql` 이 ALTER 를 계속 더한다)
    있는 테이블에는 union_by_name 으로 새 컬럼을 붙인다.
    """
    from pyiceberg.exceptions import NoSuchTableError

    ident = f"{NAMESPACE}.{name}"
    try:
        table = catalog.load_table(ident)
    except NoSuchTableError:
        return catalog.create_table(ident, schema=schema,
                                    properties=TABLE_PROPERTIES)
    with table.update_schema() as u:
        u.union_by_name(schema)
    return table


# --- 적재 (부수효과) --------------------------------------------------------

def columns_of(engine, table: str) -> list[tuple[str, str]]:
    """MariaDB 에서 컬럼 이름과 타입을 읽는다."""
    with engine.connect() as c:
        return [(r[0], r[1]) for r in
                c.execute(text(COLUMN_SQL), {"t": table}).all()]


def _fetch(engine, sql: str, params: dict) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings().all()]


def _max_of(table, column: str) -> datetime | None:
    """이미 쌓인 행에서 그 열의 최댓값. 비어 있으면 None."""
    import pyarrow.compute as pc

    scan = table.scan(selected_fields=(column,)).to_arrow()
    if scan.num_rows == 0:
        return None
    return pc.max(scan.column(column)).as_py()


def read_watermark(table) -> datetime | None:
    """이미 쌓인 변경분에서 마지막 `updated_at` 을 읽는다.

    상태 파일을 따로 두지 않는다 — 적재된 결과 자체가 워터마크라 둘이 어긋날 수 없다.
    """
    return _max_of(table, "updated_at")


def _last_daily_at(catalog) -> datetime | None:
    """하루 1회짜리를 마지막으로 뜬 시각.

    `articles_snapshot` 의 `_loaded_at` 최댓값으로 본다 — 넷이 한 묶음으로 돌아서
    하나만 보면 된다. 테이블이 아직 없으면 한 번도 안 뜬 것이다.
    """
    from pyiceberg.exceptions import NoSuchTableError

    try:
        t = catalog.load_table(f"{NAMESPACE}.articles_snapshot")
    except NoSuchTableError:
        return None
    return _max_of(t, LOADED_AT)


def load_changes(engine, catalog, plan: LoadPlan, now: datetime) -> int:
    """워터마크 이후 바뀐 행만 덧붙인다. 넣은 행 수를 돌려준다."""
    schema = arrow_schema(columns_of(engine, plan.source))
    table = ensure_table(catalog, plan.table, schema)
    wm = read_watermark(table)
    sql, params = changes_sql(wm)
    rows = _fetch(engine, sql, params)
    if not rows:
        log.info("%s — 워터마크 %s 이후 바뀐 행이 없다", plan.table, wm)
        return 0
    table.append(to_arrow(rows, schema, loaded_at=now))
    log.info("%s — %d행 적재 (워터마크 %s → %s)",
             plan.table, len(rows), wm, next_watermark(rows, wm))
    return len(rows)


def load_snapshot(engine, catalog, plan: LoadPlan, now: datetime) -> int:
    """전량을 그날 파티션에 넣는다. 같은 날 두 번 돌면 그 파티션만 갈린다.

    이 덮어쓰기가 이 적재의 멱등성이다 — `players` 와 `article_players` 는
    변경 시각 컬럼이 없어 변경분을 원본에서 뽑을 수 없고, 대신 스냅샷끼리
    대조해서 무엇이 달라졌는지 도출한다 (설계 §3.2).
    """
    from pyiceberg.expressions import EqualTo

    schema = arrow_schema(columns_of(engine, plan.source))
    table = ensure_table(catalog, plan.table, schema)
    rows = _fetch(engine, snapshot_sql(plan.source), {})
    arrow = to_arrow(rows, schema, loaded_at=now)
    # 그날 파티션이 아직 없으면 PyIceberg 가 「Delete operation did not match any
    # records」 경고를 낸다. 그날 첫 적재에서는 늘 나오는 것이고 고장이 아니다.
    table.overwrite(arrow,
                    overwrite_filter=EqualTo(LOADED_DATE, now.date().isoformat()))
    log.info("%s — 전량 %d행 스냅샷 (%s)", plan.table, len(rows), now.date())
    return len(rows)


# 운영 기록 둘. 삽입만 일어나 원본이 이미 이력이라 하루 1회로 묶었다
# (무료 구간 유지 조건 · 설계 §3.1). 계획 이름은 `ops_daily` 하나이고
# 실제 테이블은 원본마다 하나씩 둘이다.
OPS_SOURCES = (("pipeline_runs", "started_at"), ("source_freshness", "checked_at"))


def load_ops(engine, catalog, now: datetime) -> int:
    """`pipeline_runs` 와 `source_freshness` 에서 새 행만 덧붙인다."""
    total = 0
    for source, key in OPS_SOURCES:
        schema = arrow_schema(columns_of(engine, source))
        table = ensure_table(catalog, f"ops_{source}", schema)
        wm = _max_of(table, key)
        sql = f"SELECT * FROM {source}"
        params: dict = {}
        if wm is not None:
            sql += f" WHERE {key} > :wm"
            params = {"wm": wm}
        rows = _fetch(engine, sql, params)
        if not rows:
            log.info("ops_%s — 새 행이 없다 (워터마크 %s)", source, wm)
            continue
        table.append(to_arrow(rows, schema, loaded_at=now))
        log.info("ops_%s — %d행 적재", source, len(rows))
        total += len(rows)
    return total


def run_load(now: datetime | None = None) -> None:
    """이번 회차의 적재를 끝낸다."""
    from sqlalchemy import create_engine

    now = now or datetime.now(timezone.utc)
    engine = create_engine(_require_env("MARIADB_URL"))
    catalog = load_catalog()
    ensure_namespace(catalog)

    for plan in plans_for(now, _last_daily_at(catalog)):
        if plan.mode == "changes":
            load_changes(engine, catalog, plan, now)
        elif plan.mode == "snapshot":
            load_snapshot(engine, catalog, plan, now)
        else:
            load_ops(engine, catalog, now)
