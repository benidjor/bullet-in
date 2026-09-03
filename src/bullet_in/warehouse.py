"""운영 마트의 변경 이력을 GCS 위 Iceberg 테이블로 남긴다.

설계 = docs/superpowers/specs/2026-09-02-history-lakehouse-design.md

회차 안에서 돌지 않는다 — 별도 타이머가 부른다.
게이트가 배포를 막는 자리라 그 위에 네트워크와 인증을 더 얹지 않는다.

새 패키지를 최소로 쓴다 — 자격은 `google-auth` 가 만들고 PyIceberg 가 그것을 받는다.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
from sqlalchemy import text

log = logging.getLogger(__name__)

NAMESPACE = "mart_history"
# 행동 기록은 성격이 달라 같은 이름 아래 두면 이름과 내용이 어긋난다 (설계 §3.1).
BEHAVIOR_NS = "behavior"

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


# --- 행동 기록 평탄화 (부수효과 없음) ---------------------------------------

KST = timezone(timedelta(hours=9))
# 공개일. 이 하루가 표본의 58% 라 집계에서 가른다 (설계 §2.1).
LAUNCH_DATE = date(2026, 8, 29)

# 평탄화 결과에서 타입을 주는 컬럼. 나머지는 전부 문자열이다.
FLAT_BASE_TYPES = {
    "event_date": pa.string(), "event_timestamp": pa.int64(),
    "event_name": pa.string(), "user_pseudo_id": pa.string(),
    "platform": pa.string(),
    "event_at": pa.timestamp("us", tz="UTC"),
    "event_date_kst": pa.string(), "is_article_click": pa.bool_(),
}

# 중첩 레코드에서 꺼내 컬럼으로 펴는 축.
NESTED_COLUMNS = {
    "device_category": ("device", "category"),
    "device_os": ("device", "operating_system"),
    "device_browser": ("device", "web_info", "browser"),
    "geo_country": ("geo", "country"),
    "geo_region": ("geo", "region"),
    "traffic_source": ("traffic_source", "source"),
    "traffic_medium": ("traffic_source", "medium"),
    "traffic_name": ("traffic_source", "name"),
}

# 파라미터 값이 네 칸에 나뉘어 온다. 있는 것 하나를 문자열로 모은다.
_PARAM_VALUE_FIELDS = ("string_value", "int_value", "float_value", "double_value")

# 원본에서 그대로 가져오는 컬럼. 파생 컬럼 셋은 여기 없다.
_FLAT_SOURCE_COLUMNS = ("event_date", "event_timestamp", "event_name",
                        "user_pseudo_id", "platform")


def _dig(row, path: tuple[str, ...]):
    """중첩 레코드를 따라 내려간다. 도중에 없으면 None."""
    cur = row
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _param_value(value: dict | None) -> str | None:
    for field in _PARAM_VALUE_FIELDS:
        got = (value or {}).get(field)
        if got is not None:
            return str(got)
    return None


def flatten_rows(rows: list[dict]) -> list[dict]:
    """원본 행을 컬럼 하나에 값 하나인 모양으로 편다.

    빈 값은 채우지 않는다 — `card_hash` 가 없다는 것은 기사 카드가 아니라는
    뜻이고 채우면 거짓이 된다 (설계 §3.3).
    """
    out = []
    for row in rows:
        flat = {c: row.get(c) for c in _FLAT_SOURCE_COLUMNS}
        for name, path in NESTED_COLUMNS.items():
            flat[name] = _dig(row, path)
        for param in (row.get("event_params") or []):
            key = param.get("key")
            if not key:
                continue
            # 계측이 심는 키라 기본 컬럼과 겹칠 수 있다. 겹치면 밑에 깔리므로 가른다.
            if key in FLAT_BASE_TYPES or key in NESTED_COLUMNS:
                key = f"{key}_param"
            flat[key] = _param_value(param.get("value"))

        micros = flat.get("event_timestamp")
        at = (datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc)
              if micros else None)
        flat["event_at"] = at
        flat["event_date_kst"] = at.astimezone(KST).date().isoformat() if at else None
        flat["is_article_click"] = bool(flat.get("event_name") == "bi_card_click"
                                        and flat.get("card_hash"))
        out.append(flat)
    return out


def dedupe_events(rows: list[dict]) -> list[dict]:
    """같은 행동이 두 번 도착한 것을 접는다 (실측 51건 · 설계 §1.5).

    `bi_cid` 가 없는 행은 접지 않는다 — 자동 수집 이벤트에는 그 값이 없어서
    키가 전부 널이 되고, 한 덩어리로 뭉쳐 3분의 2가 사라진다.
    """
    seen: set[tuple] = set()
    out = []
    for row in rows:
        cid = row.get("bi_cid")
        if not cid:
            out.append(row)
            continue
        key = (cid, row.get("bi_ts"), row.get("event_name"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def flat_schema(rows: list[dict]) -> pa.Schema:
    """나타난 키 전량으로 스키마를 세운다.

    목록을 사람이 관리하지 않으므로 계측이 바뀌어도 낡지 않는다 (설계 §2 결정 7).
    새 키가 나타나면 `ensure_table` 의 union_by_name 이 컬럼을 늘린다.
    """
    names = list(FLAT_BASE_TYPES) + list(NESTED_COLUMNS)
    seen = set(names)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    fields = [pa.field(n, FLAT_BASE_TYPES.get(n, pa.string())) for n in names]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)


# 팩트의 알갱이는 클릭 한 건이다. 표본 수 (`n_clicks`) 는 여기 두지 않고
# 집계 함수가 낸다 — 행마다 값이 1인 컬럼은 뜻이 없다.
FACT_COLUMNS = ("bi_cid", "event_at", "event_date_kst", "card_hash", "card_slug",
                "card_stage", "card_tier", "card_outlet", "card_surface",
                "page_location", "device_category", "geo_country")


def fact_rows(flat: list[dict]) -> list[dict]:
    """카드 클릭만 골라 정한 축만 남긴다."""
    return [{c: row.get(c) for c in FACT_COLUMNS}
            for row in flat if row.get("event_name") == "bi_card_click"]


def dim_date_rows(dates) -> list[dict]:
    """날짜 축. 공개일로부터 며칠째인지를 함께 담는다."""
    out = []
    for iso in sorted({d for d in dates if d}):
        day = date.fromisoformat(iso)
        out.append({"date": iso, "weekday": day.isoweekday(),
                    "days_since_launch": (day - LAUNCH_DATE).days,
                    "is_launch_day": day == LAUNCH_DATE})
    return out


# 화면이 읽는 집계. 축 이름은 팩트의 컬럼 이름이고, 짝은 마트에서 같은 축을 세는
# 컬럼이다 — 클릭 수만으로는 「등급이 높을수록 더 눌리는가」 에 답할 수 없어서
# 기사 수로 나눈 값을 함께 낸다.
# 짝이 `None` 인 축은 기사 수를 안 붙인다.
# `card_outlet` 은 카드에 찍힌 표시 이름인데, 렌더가 「원문 매체」 와 소스 이름 두 값에서
# 만들어 낸다 (마트의 `source_id` 는 슬러그이고 `outlet` 은 3분의 2가 비어 있다).
# 그 파생을 여기서 다시 짜면 층이 서로 묶이므로 클릭 수만 낸다.
METRIC_AXES = (("card_outlet", None),
               ("card_stage", "transfer_stage"),
               ("card_tier", "tier"),
               ("card_surface", None))

EMPTY_LABEL = "(없음)"


def _axis_key(value) -> str:
    """축 값을 두 층이 견줄 수 있는 꼴로 만든다.

    등급은 클릭이 `4` 로, 마트가 `4.0` 으로 온다 — 문자열 그대로 맞대면 한 건도
    안 붙는다. 숫자로 읽히면 숫자로 접고 아니면 그대로 둔다.
    """
    if value is None or value == "":
        return EMPTY_LABEL
    text = str(value)
    try:
        return f"{float(text):g}"
    except ValueError:
        return text


def aggregate(facts: list[dict], articles: list[dict]) -> dict:
    """축별 클릭 수 · 기사 수 · 기사당 클릭.

    공개일 (2026-08-29) 을 뺀다 — 그 하루가 표본의 58% 라 평균을 왜곡한다.
    뺀 사실과 뺀 양을 `totals` 에 함께 실어 화면이 그대로 적을 수 있게 한다.
    """
    launch = LAUNCH_DATE.isoformat()
    counted = [f for f in facts if f.get("event_date_kst") != launch]

    # 주요 소식 · 타임라인 제목은 2026-09-03 까지 카드에 해시만 실어서 단계 · 등급이
    # 비어 왔다 (실측 — 「(없음)」 52 = mitem 24 + pcard 26 + tltitle 2). 기사 해시가
    # 있으면 마트 스냅샷에서 채운다. 선수 카드는 기사가 아니라 그대로 남는다.
    # 마트 값은 지금 값이라 클릭 시점의 카드 표기와 다를 수 있다.
    by_hash = {a.get("content_hash"): a for a in articles if a.get("content_hash")}

    def value_of(fact, axis, article_column):
        value = fact.get(axis)
        if (value is None or value == "") and article_column:
            article = by_hash.get(fact.get("card_hash"))
            if article:
                value = article.get(article_column)
        return _axis_key(value)

    axes = {}
    for axis, article_column in METRIC_AXES:
        clicks = Counter(value_of(f, axis, article_column) for f in counted)
        denom = (Counter(_axis_key(a.get(article_column)) for a in articles)
                 if article_column else Counter())
        rows = []
        for value, n in clicks.most_common():
            # 빈 칸은 두 층에서 뜻이 다르다 — 「단계가 없는 클릭」 과 「단계가 없는
            # 기사」 를 나누면 거짓이 된다 (실측에서 26.0 이라는 값이 나왔다).
            n_articles = 0 if value == EMPTY_LABEL else denom.get(value, 0)
            rows.append({"value": value, "n_clicks": n, "n_articles": n_articles,
                         "per_article": round(n / n_articles, 2) if n_articles
                         else None})
        axes[axis] = rows

    days = sorted({f.get("event_date_kst") for f in facts if f.get("event_date_kst")})
    return {"totals": {"all": len(facts),
                       "launch_day": len(facts) - len(counted),
                       "counted": len(counted)},
            "dates": {"from": days[0] if days else None,
                      "to": days[-1] if days else None},
            "axes": axes}


# 일별 내보내기 표만 고른다. `events_intraday_*` 는 그날이 끝나면 사라지고 완결된
# 표로 갈리므로 실으면 반쯤 찬 하루가 영구히 남는다.
EVENTS_TABLE_RE = re.compile(r"^events_(\d{8})$")


def event_dates_of(table_ids) -> list[str]:
    """내보내기 표 이름 목록에서 날짜만 오름차순으로 뽑는다."""
    return sorted(m.group(1) for t in table_ids
                  if (m := EVENTS_TABLE_RE.match(t)))


def dates_to_load(available: list[str], loaded: set[str]) -> list[str]:
    """아직 안 실은 날짜를 오래된 것부터.

    상태 파일을 두지 않는다 — 실린 결과 자체가 워터마크라 둘이 어긋날 수 없다
    (`read_watermark` 와 같은 규율).
    """
    return [d for d in sorted(available) if d not in loaded]


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

    경계를 초과로 둔다 — 같은 시각의 행을 다시 가져오면 변경 이력에 같은 값이 두 번 쌓인다.
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
    """변경 이력을 담는 카탈로그에 붙는다.

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


def ensure_namespace(catalog, namespace: str = NAMESPACE) -> None:
    """네임스페이스를 멱등하게 만든다."""
    from pyiceberg.exceptions import NamespaceAlreadyExistsError
    try:
        catalog.create_namespace(namespace)
    except NamespaceAlreadyExistsError:
        pass


def ensure_table(catalog, name: str, schema, namespace: str = NAMESPACE):
    """테이블을 멱등하게 만들고 돌려준다.

    원본에 컬럼이 늘어나는 저장소라 (`schema.sql` 이 ALTER 를 계속 더하고,
    행동 기록은 계측이 새 키를 심는다) 있는 테이블에는 union_by_name 으로
    새 컬럼을 붙인다.
    """
    from pyiceberg.exceptions import NoSuchTableError

    ident = f"{namespace}.{name}"
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


# 운영 기록 둘. 삽입만 일어나 원본에 이미 시점별 기록이 남으므로 하루 1회로 묶었다
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


# --- 유지보수 (부수효과) ----------------------------------------------------

# --- 행동 기록 (BigQuery -> bronze) ----------------------------------------

GA4_TABLE = "ga4_events"
GA4_FLAT_TABLE = "ga4_events_flat"


def with_load_columns(table: pa.Table, loaded_at: datetime) -> pa.Table:
    """중첩을 그대로 둔 채 적재 시각 두 컬럼만 덧붙인다.

    `to_arrow()` 를 쓰지 않는다 — 그쪽은 행 딕셔너리에서 세우는 길이라
    `event_params` 배열과 `device` 레코드가 뭉개진다.
    """
    n = table.num_rows
    ts = pa.timestamp("us", tz="UTC")
    return (table
            .append_column(pa.field(LOADED_AT, ts),
                           pa.array([loaded_at] * n, type=ts))
            .append_column(pa.field(LOADED_DATE, pa.string()),
                           pa.array([loaded_at.date().isoformat()] * n,
                                    type=pa.string())))


def flatten_day(arrow: pa.Table) -> list[dict]:
    """하루치 원본에서 평탄화 · 겹침 접기까지 끝낸 행을 만든다."""
    return dedupe_events(flatten_rows(arrow.to_pylist()))


def loaded_event_dates(table) -> set[str]:
    """이미 실린 날짜. 비어 있으면 빈 집합이다."""
    scan = table.scan(selected_fields=("event_date",)).to_arrow()
    if scan.num_rows == 0:
        return set()
    return set(scan.column("event_date").to_pylist())


def _bq_client():
    """읽기 전용 BigQuery 클라이언트.

    자격은 `GOOGLE_APPLICATION_CREDENTIALS` 가 가리키는 서비스 계정이고,
    그 계정은 `bullet-in-analytics` 에 `bigquery.dataViewer` 를 받아 두었다.
    """
    from google.cloud import bigquery
    return bigquery.Client(project=os.environ.get("GA4_BILLING_PROJECT")
                           or "bullet-in-lakehouse")


def _bq_table_ids(dataset: str) -> list[str]:
    return [t.table_id for t in _bq_client().list_tables(dataset)]


def _bq_read_day(dataset: str, table_id: str) -> pa.Table:
    return _bq_client().list_rows(f"{dataset}.{table_id}").to_arrow()


def load_ga4_events(catalog, now: datetime) -> int:
    """아직 안 실은 날짜를 오래된 것부터 원본 그대로 넣는다.

    `GA4_DATASET` 이 없으면 아무것도 안 한다 — 개발 환경에는 이 설정이 없고,
    없다는 것이 고장은 아니다.
    """
    dataset = os.environ.get("GA4_DATASET")
    if not dataset:
        log.info("%s — GA4_DATASET 이 없어 넘어간다", GA4_TABLE)
        return 0

    from pyiceberg.exceptions import NoSuchTableError

    # 자기 표를 담을 자리는 자기가 챙긴다 — 부르는 쪽 순서에 기대면 이 함수만
    # 따로 돌릴 수 없다.
    ensure_namespace(catalog, BEHAVIOR_NS)
    try:
        loaded = loaded_event_dates(
            catalog.load_table(f"{BEHAVIOR_NS}.{GA4_TABLE}"))
    except NoSuchTableError:
        loaded = set()

    days = dates_to_load(event_dates_of(_bq_table_ids(dataset)), loaded)
    if not days:
        log.info("%s — 새로 실을 날짜가 없다 (실린 날 %d일)", GA4_TABLE, len(loaded))
        return 0

    total = 0
    for day in days:
        raw = _bq_read_day(dataset, f"events_{day}")
        arrow = with_load_columns(raw, now)
        table = ensure_table(catalog, GA4_TABLE, arrow.schema,
                             namespace=BEHAVIOR_NS)
        table.append(arrow)
        log.info("%s — %s %d행 적재", GA4_TABLE, day, arrow.num_rows)
        total += arrow.num_rows
    return total


def load_ga4_flat(catalog, now: datetime) -> int:
    """원본에 있으나 평탄화본에 없는 날짜를 편다.

    워터마크를 자기 표에서 읽는다 — 앞 층이 새로 실은 날짜에 얹으면 이미 원본에
    들어와 있던 날은 영원히 안 펴진다. 운영에 붙이고 나서야 그 상태가 드러났고,
    로그가 「새로 실을 날짜가 없다」 로 정상처럼 읽혀 조용히 지나갔다.

    이 갈래가 따로 있어야 설계 §3.3 이 약속한 성질 — 평탄화본을 통째로 지우고
    원본에서 다시 만들 수 있다 — 이 실제로 성립한다.
    """
    from pyiceberg.exceptions import NoSuchTableError
    from pyiceberg.expressions import EqualTo

    try:
        source = catalog.load_table(f"{BEHAVIOR_NS}.{GA4_TABLE}")
    except NoSuchTableError:
        log.info("%s — 원본이 아직 없다", GA4_FLAT_TABLE)
        return 0

    try:
        done = loaded_event_dates(
            catalog.load_table(f"{BEHAVIOR_NS}.{GA4_FLAT_TABLE}"))
    except NoSuchTableError:
        done = set()

    days = dates_to_load(sorted(loaded_event_dates(source)), done)
    if not days:
        log.info("%s — 펼 날짜가 없다 (편 날 %d일)", GA4_FLAT_TABLE, len(done))
        return 0

    total = 0
    for day in days:
        raw = source.scan(row_filter=EqualTo("event_date", day)).to_arrow()
        flat = flatten_day(raw)
        schema = flat_schema(flat)
        table = ensure_table(catalog, GA4_FLAT_TABLE, schema,
                             namespace=BEHAVIOR_NS)
        table.append(to_arrow(flat, schema, loaded_at=now))
        log.info("%s — %s 원본 %d행 → 평탄화 %d행",
                 GA4_FLAT_TABLE, day, raw.num_rows, len(flat))
        total += len(flat)
    return total


FACT_TABLE = "fact_card_click"
DIM_DATE_TABLE = "dim_date"

_FACT_TYPES = {"event_at": pa.timestamp("us", tz="UTC")}
_DIM_DATE_TYPES = {"date": pa.string(), "weekday": pa.int32(),
                   "days_since_launch": pa.int32(), "is_launch_day": pa.bool_()}


def _typed_schema(names, types: dict) -> pa.Schema:
    fields = [pa.field(n, types.get(n, pa.string())) for n in names]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)


def build_gold(catalog, now: datetime) -> int:
    """평탄화본 전량에서 팩트와 날짜 디멘션을 다시 세운다.

    덧붙이지 않고 갈아 끼운다 — 원본이 남아 있어 언제든 다시 만들 수 있고,
    그래야 겹침 접기 규칙을 고쳤을 때 옛 결과가 안 남는다.

    기사 · 선수 디멘션은 `mart_history` 에 이미 있어 새로 만들지 않고 참조한다
    (설계 §3.5).
    """
    from pyiceberg.exceptions import NoSuchTableError

    try:
        flat_table = catalog.load_table(f"{BEHAVIOR_NS}.{GA4_FLAT_TABLE}")
    except NoSuchTableError:
        log.info("%s — 평탄화본이 아직 없다", FACT_TABLE)
        return 0

    flat = flat_table.scan().to_arrow().to_pylist()
    facts = fact_rows(flat)
    dims = dim_date_rows(r.get("event_date_kst") for r in flat)

    for name, rows, names, types in (
            (FACT_TABLE, facts, FACT_COLUMNS, _FACT_TYPES),
            (DIM_DATE_TABLE, dims, tuple(_DIM_DATE_TYPES), _DIM_DATE_TYPES)):
        schema = _typed_schema(names, types)
        table = ensure_table(catalog, name, schema, namespace=BEHAVIOR_NS)
        table.overwrite(to_arrow(rows, schema, loaded_at=now))
        log.info("%s — %d행 갈아 끼움", name, len(rows))
    return len(facts)


# 화면이 읽는 자리. 회차의 렌더가 Iceberg 를 직접 읽으면 게이트 앞에 인증과
# 네트워크가 붙으므로 (모듈 첫 주석) 파일 하나를 사이에 둔다.
METRICS_PATH = Path("state/behavior_metrics.json")


def _latest_articles(catalog) -> list[dict]:
    """가장 최근에 뜬 기사 스냅샷. 없으면 빈 목록이다.

    디멘션을 새로 만들지 않고 `mart_history` 의 것을 참조한다 (설계 §3.5).
    """
    from pyiceberg.exceptions import NoSuchTableError
    from pyiceberg.expressions import EqualTo

    try:
        snap = catalog.load_table(f"{NAMESPACE}.articles_snapshot")
    except NoSuchTableError:
        return []
    latest = _max_of(snap, LOADED_AT)
    if latest is None:
        return []
    return snap.scan(row_filter=EqualTo(
        LOADED_DATE, latest.date().isoformat())).to_arrow().to_pylist()


def write_metrics(catalog, now: datetime) -> dict:
    """팩트와 마트 스냅샷에서 집계를 내어 JSON 으로 떨어뜨린다."""
    from pyiceberg.exceptions import NoSuchTableError

    try:
        facts = catalog.load_table(
            f"{BEHAVIOR_NS}.{FACT_TABLE}").scan().to_arrow().to_pylist()
    except NoSuchTableError:
        log.info("%s — 팩트가 아직 없다", METRICS_PATH)
        return {}

    metrics = aggregate(facts, _latest_articles(catalog))
    metrics["generated_at"] = now.isoformat()
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    log.info("%s — 클릭 %d건 (공개일 %d건 제외) 기준 집계",
             METRICS_PATH, metrics["totals"]["counted"],
             metrics["totals"]["launch_day"])
    return metrics


def compact(table) -> dict:
    """조각난 데이터 파일을 한 파일로 다시 쓴다.

    PyIceberg 는 컴팩션을 제공하지 않는다 (문서 원문 「Compaction is planned」).
    fast append 가 커밋마다 파일 하나를 만들어서, 회차마다 조금씩 쓰면 Parquet
    압축이 안 들어 행당 부피가 6.15배가 된다 (실측 19,430 B 대 3,160 B).

    방법은 단순하다 — 담긴 행을 전부 읽어서 그 자리를 덮어쓴다.
    Iceberg 의 스냅샷 격리 덕에 그 사이 읽는 쪽은 옛 스냅샷을 계속 본다.
    """
    sizes = {f.file.file_path: f.file.file_size_in_bytes
             for f in table.scan().plan_files()}
    targets = files_to_compact(sizes)
    if not targets:
        return {"files_before": len(sizes), "compacted": 0}

    before = sum(sizes[p] for p in targets)
    rows = table.scan().to_arrow()
    table.overwrite(rows)
    table.refresh()
    after = sum(f.file.file_size_in_bytes for f in table.scan().plan_files())
    log.info("컴팩션 — 파일 %d개 %s바이트를 다시 씀 → %s바이트",
             len(targets), f"{before:,}", f"{after:,}")
    return {"files_before": len(sizes), "compacted": len(targets),
            "bytes_before": before, "bytes_after": after}


def expire(table, now: datetime) -> int:
    """오래된 Iceberg 스냅샷을 만료한다.

    부피가 아니라 `metadata.json` 1 MB 한도 때문에 한다.
    스냅샷 하나가 약 1,015 바이트를 더하므로 그냥 두면 약 124일에 커밋이 실패한다.

    호출 경로가 `table.maintenance` 아래다 — `table.expire_snapshots()` 는
    PyIceberg 0.11.1 에 없다. 인자도 밀리초가 아니라 datetime 이다.
    """
    before = len(table.metadata.snapshots)
    table.maintenance.expire_snapshots().older_than(expire_before(now)).commit()
    table.refresh()
    after = len(table.metadata.snapshots)
    log.info("스냅샷 만료 — %d개에서 %d개로", before, after)
    return before - after


def drop_old_snapshot_dates(table, today: date) -> int:
    """90일 넘은 전량 스냅샷 중 월요일이 아닌 날을 지운다."""
    from pyiceberg.expressions import EqualTo
    import pyarrow.compute as pc

    scan = table.scan(selected_fields=(LOADED_DATE,)).to_arrow()
    if scan.num_rows == 0:
        return 0
    have = sorted({date.fromisoformat(d)
                   for d in pc.unique(scan.column(LOADED_DATE)).to_pylist()})
    drop = snapshot_dates_to_drop(have, today)
    for d in drop:
        table.delete(EqualTo(LOADED_DATE, d.isoformat()))
    if drop:
        log.info("스냅샷 파티션 %d일치 삭제 (%s ~ %s)", len(drop), drop[0], drop[-1])
    return len(drop)


def _existing_tables(catalog, namespace: str = NAMESPACE) -> list[str]:
    """네임스페이스 안의 테이블 이름. 아직 아무것도 없으면 빈 목록이다.

    네임스페이스가 없는 것은 고장이 아니라 「아직 한 번도 안 실었다」 는 뜻이다.
    그대로 예외를 올리면 유지보수 타이머가 적재보다 먼저 도는 첫날에 유닛이 실패하고
    `OnFailure` 가 헛알림을 보낸다.
    """
    from pyiceberg.exceptions import NoSuchNamespaceError

    try:
        return [t[-1] for t in catalog.list_tables(namespace)]
    except NoSuchNamespaceError:
        return []


def run_maintenance(now: datetime | None = None) -> None:
    """컴팩션 · 스냅샷 만료 · 오래된 파티션 솎기를 한 번에."""
    from pyiceberg.exceptions import NoSuchTableError

    now = now or datetime.now(timezone.utc)
    catalog = load_catalog()
    for ns in (NAMESPACE, BEHAVIOR_NS):
        for name in _existing_tables(catalog, ns):
            try:
                table = catalog.load_table(f"{ns}.{name}")
            except NoSuchTableError:
                continue
            if name.endswith("_snapshot"):
                drop_old_snapshot_dates(table, now.date())
            compact(table)
            expire(table, now)
            # 남은 스냅샷 수를 남긴다 — 1 MB 한도까지 얼마나 남았는지 보는 눈이다.
            log.info("%s.%s — 남은 스냅샷 %d개", ns, name,
                     len(table.metadata.snapshots))


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

    # 행동 기록은 출처가 다르고 하루 늦게 도착한다. 위의 적재는 이미 끝났으므로
    # 여기서 실패해도 그쪽은 잃지 않는다. 다만 삼키면 유닛이 0 으로 끝나 `OnFailure=`
    # 알림이 안 뜨고 집계 파일이 조용히 낡으므로, 적어 두고 다시 던진다.
    try:
        load_ga4_events(catalog, now)
        load_ga4_flat(catalog, now)
        build_gold(catalog, now)
        write_metrics(catalog, now)
    except Exception:
        log.warning("행동 기록 적재 실패 — 마트 이력 적재는 끝났다", exc_info=True)
        raise


def run_show() -> None:
    """쌓인 테이블의 행 수 · 파일 수 · 남은 스냅샷 수를 보여 준다.

    파일 수와 스냅샷 수가 함께 보이는 것이 요점이다 — 앞은 컴팩션이,
    뒤는 만료가 도는지를 말해 준다.
    """
    catalog = load_catalog()
    for ns in (NAMESPACE, BEHAVIOR_NS):
        for name in sorted(_existing_tables(catalog, ns)):
            t = catalog.load_table(f"{ns}.{name}")
            files = list(t.scan().plan_files())
            size = sum(f.file.file_size_in_bytes for f in files)
            print(f"{ns}.{name:28} {t.scan().to_arrow().num_rows:>8,}행  "
                  f"파일 {len(files):>3}개  {size:>12,}B  "
                  f"스냅샷 {len(t.metadata.snapshots):>3}개")


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="운영 마트 변경 이력 적재")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("load", help="변경분 · 스냅샷 적재")
    sub.add_parser("maint", help="컴팩션 · 만료 · 파티션 솎기")
    sub.add_parser("show", help="쌓인 것 보기")

    args = ap.parse_args()
    if args.command == "load":
        run_load()
    elif args.command == "maint":
        run_maintenance()
    else:
        run_show()
    sys.exit(0)
