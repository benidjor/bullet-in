# 이력 레이크하우스 구현 계획 (2026-09-02)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 덮어써서 사라지는 `articles` · `players` · `article_players` 의 값을 GCS 위의 Iceberg 테이블로 옮겨 시점별로 되짚을 수 있게 만든다.

**Architecture:** 회차와 분리된 systemd 타이머가 `bullet_in.warehouse` 를 부른다.
`articles` 는 `updated_at` 워터마크로 회차마다 변경분을 쌓고, 세 표는 하루 1회 전량 스냅샷을 쌓는다.
PyIceberg 에 없는 컴팩션과 스냅샷 만료를 직접 만들어 무료 구간 안에서 돌게 한다.

**Tech Stack:** Python 3.11 · uv · PyIceberg 0.11.1 · PyArrow · google-auth · httpx · SQLAlchemy · Google Lakehouse Iceberg REST 카탈로그 · GCS

**Spec:** `docs/superpowers/specs/2026-09-02-history-lakehouse-design.md`

## Global Constraints

- Python 3.11 · 의존 추가는 `pyproject.toml` 의 `dependencies` 에 넣는다.
- 이 프로젝트는 dotenv 를 쓰지 않는다.
  설정은 환경변수로 받고 systemd 는 `EnvironmentFile` 로 준다.
- 기존 `dbt/models/gold/` 3모델과 `src/bullet_in/run.py` 의 회차 흐름은 한 글자도 건드리지 않는다.
- 테스트 함수 이름은 한국어로 쓴다 (`tests/test_backup.py` 관례).
- 순수 판정 함수와 부수효과 함수를 파일 안에서 절로 나눈다 (`src/bullet_in/backup.py` 관례).
- GCS 버킷과 카탈로그는 `us-central1` 에 만든다.
  무료 5 GB 가 이 리전에만 적용된다.
- 관리형 Iceberg 테이블을 만들지 않는다.
  `BigLake Table Management` SKU 가 시간당 165.99 KRW 다.
- 커밋 메시지는 `docs/conventions/2026-06-11-commit-pr-convention.md` 를 따른다.

---

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `src/bullet_in/warehouse.py` (생성) | 적재 대상 판정 · Arrow 변환 · 카탈로그 접속 · 적재 · 컴팩션 · 만료 · CLI |
| `tests/test_warehouse.py` (생성) | 위 모듈의 순수 판정 부분 전량 |
| `pyproject.toml` (수정) | `pyiceberg` · `pyarrow` 의존 추가 |
| `infra/systemd/bullet-in-warehouse.service` (생성) | 적재 유닛 |
| `infra/systemd/bullet-in-warehouse.timer` (생성) | 회차와 20분 어긋난 3시간 간격 |
| `infra/systemd/bullet-in-warehouse-maint.service` (생성) | 컴팩션 · 만료 · 솎기 유닛 |
| `infra/systemd/bullet-in-warehouse-maint.timer` (생성) | 하루 1회 |
| `infra/systemd/install-units.sh` (수정) | 새 유닛 넷 등록 |
| `docs/runbook/2026-09-02-warehouse-history-load.md` (생성) | 운영 절차 |

`backup.py` 가 426줄에 백업 · 목록 · 복구 세 기능과 CLI 를 담고 있다.
`warehouse.py` 도 같은 크기가 되므로 하나로 둔다.

---

## Task 1: 의존을 더하고 VM arm64 에서 설치되는지 확인한다

VM 은 Oracle 무료 A1 arm64 다.
`pyarrow` 휠이 PyPI 에 있다는 것은 확인했지만 실제로 설치해 본 적이 없다.
여기서 막히면 뒤 태스크가 전부 헛일이 되므로 첫 태스크로 둔다.

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `pyiceberg` · `pyarrow` 를 import 할 수 있는 환경

- [ ] **Step 1: 의존을 더한다**

`pyproject.toml` 의 `dependencies` 목록에서 `dbt-duckdb` 줄 앞에 두 줄을 넣는다.

```toml
  "pyiceberg[sql-sqlite]>=0.11,<0.12",  # 이력 레이크하우스 — 커밋 API 가 마이너 사이에 바뀐다
  "pyarrow>=17",                        # Iceberg 가 Parquet 만 받는다 (Lakehouse 카탈로그 제약)
```

- [ ] **Step 2: 로컬에서 잠긴 버전을 만든다**

```bash
uv sync --extra dev
uv run python -c "import pyiceberg, pyarrow; print(pyiceberg.__version__, pyarrow.__version__)"
```

기대: 두 버전이 찍힌다.

- [ ] **Step 3: VM 에서 arm64 휠이 깔리는지 본다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 "/home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in --with pyiceberg --with pyarrow python -c \"import pyarrow; print(pyarrow.__version__)\""
```

기대: 버전이 찍힌다.
`No matching distribution` 이 나오면 여기서 멈추고 보고한다.
그 경우 대안은 VM 에서 적재하지 않고 맥에서 돌리는 것인데, 그것은 안건 2ι 가 막 없앤 의존을 되살리는 일이라 설계를 다시 봐야 한다.

- [ ] **Step 4: 커밋**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): 이력 적재용 pyiceberg · pyarrow 추가"
```

---

## Task 2: 적재 대상 판정을 순수 함수로 만든다

무엇을 언제 뜨는지가 이 모듈의 뼈대다.
DB 도 GCS 도 없이 판정만 따로 테스트할 수 있게 만든다.

**Files:**
- Create: `src/bullet_in/warehouse.py`
- Create: `tests/test_warehouse.py`

**Interfaces:**
- Produces: `LoadPlan` 데이터클래스 · `plans_for(now, last_daily_at)` · `NAMESPACE` · `TABLES`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_warehouse.py` 를 만든다.

```python
"""이력 레이크하우스의 판정 부분 테스트 — 적재 대상 · 워터마크 · 보관."""
from datetime import datetime, timezone

import pytest

from bullet_in import warehouse


def _t(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


# --- 적재 대상 판정 ---------------------------------------------------------

def test_하루1회짜리를_아직_안_떴으면_전부_대상():
    plans = warehouse.plans_for(_t(2026, 9, 2, 3), last_daily_at=None)
    assert {p.table for p in plans} == set(warehouse.TABLES)


def test_오늘_이미_떴으면_변경분만_남는다():
    plans = warehouse.plans_for(_t(2026, 9, 2, 12),
                                last_daily_at=_t(2026, 9, 2, 3))
    assert [p.table for p in plans] == ["articles_changes"]


def test_날이_바뀌면_하루1회짜리가_다시_대상():
    plans = warehouse.plans_for(_t(2026, 9, 3, 3),
                                last_daily_at=_t(2026, 9, 2, 3))
    assert {p.table for p in plans} == set(warehouse.TABLES)


def test_변경분은_언제나_대상이다():
    plans = warehouse.plans_for(_t(2026, 9, 2, 21),
                                last_daily_at=_t(2026, 9, 2, 3))
    assert any(p.mode == "changes" for p in plans)


def test_스냅샷_대상_셋과_ops_하나():
    plans = warehouse.plans_for(_t(2026, 9, 2, 3), last_daily_at=None)
    snaps = [p for p in plans if p.mode == "snapshot"]
    assert {p.source for p in snaps} == {"articles", "players", "article_players"}
    assert [p.source for p in plans if p.mode == "append"] == ["ops"]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: `ModuleNotFoundError: No module named 'bullet_in.warehouse'`

- [ ] **Step 3: 최소 구현을 쓴다**

`src/bullet_in/warehouse.py` 를 만든다.

```python
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
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: 5 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 이력 적재 대상 판정"
```

---

## Task 3: MariaDB 컬럼에서 Arrow 스키마를 도출한다

`schema.sql` 에 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 가 계속 붙는다.
컬럼 목록을 손으로 적으면 낡으므로 `information_schema` 에서 읽어 만든다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Modify: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: 없음
- Produces: `arrow_schema(columns)` · `to_arrow(rows, schema)` · `COLUMN_SQL`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_warehouse.py` 끝에 붙인다.

```python
# --- Arrow 스키마 도출 -----------------------------------------------------

import pyarrow as pa


def test_문자열_계열은_전부_string():
    s = warehouse.arrow_schema([("title_ko", "text"), ("url", "varchar"),
                                ("content_hash", "char"), ("images_json", "json")])
    assert [f.type for f in s] == [pa.string()] * 4


def test_정수와_실수와_시각이_제_타입으로_간다():
    s = warehouse.arrow_schema([("id", "bigint"), ("revision", "int"),
                                ("body_level", "tinyint"), ("tier", "float"),
                                ("created_at", "datetime")])
    assert s.field("id").type == pa.int64()
    assert s.field("revision").type == pa.int32()
    assert s.field("body_level").type == pa.int8()
    assert s.field("tier").type == pa.float64()
    assert s.field("created_at").type == pa.timestamp("us", tz="UTC")


def test_모르는_타입은_문자열로_떨어뜨린다():
    # 새 컬럼이 낯선 타입으로 들어와도 적재가 죽지 않아야 한다.
    s = warehouse.arrow_schema([("something", "geometry")])
    assert s.field("something").type == pa.string()


def test_적재시각_컬럼이_스키마_끝에_붙는다():
    s = warehouse.arrow_schema([("id", "bigint")])
    assert s.names == ["id", "_loaded_at"]


def test_행이_없어도_스키마대로_빈_표가_나온다():
    s = warehouse.arrow_schema([("id", "bigint"), ("url", "varchar")])
    t = warehouse.to_arrow([], s, loaded_at=_t(2026, 9, 2))
    assert t.num_rows == 0
    assert t.schema == s


def test_없는_컬럼은_널로_채운다():
    s = warehouse.arrow_schema([("id", "bigint"), ("url", "varchar")])
    t = warehouse.to_arrow([{"id": 1}], s, loaded_at=_t(2026, 9, 2))
    assert t.column("url").to_pylist() == [None]


def test_적재시각이_모든_행에_같은_값으로_들어간다():
    s = warehouse.arrow_schema([("id", "bigint")])
    t = warehouse.to_arrow([{"id": 1}, {"id": 2}], s, loaded_at=_t(2026, 9, 2, 3))
    assert t.column("_loaded_at").to_pylist() == [_t(2026, 9, 2, 3)] * 2
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: `AttributeError: module 'bullet_in.warehouse' has no attribute 'arrow_schema'`

- [ ] **Step 3: 구현을 쓴다**

`warehouse.py` 의 판정 절에 붙인다.
맨 위 import 에 `import pyarrow as pa` 를 더한다.

```python
# information_schema.DATA_TYPE 이 주는 이름에서 Arrow 타입으로.
# 모르는 이름은 문자열로 떨어뜨린다 — 새 컬럼 하나 때문에 적재가 죽으면 안 된다.
_TYPE_MAP = {
    "bigint": pa.int64(), "int": pa.int32(), "mediumint": pa.int32(),
    "smallint": pa.int16(), "tinyint": pa.int8(),
    "float": pa.float64(), "double": pa.float64(), "decimal": pa.float64(),
    "datetime": pa.timestamp("us", tz="UTC"),
    "timestamp": pa.timestamp("us", tz="UTC"),
    "date": pa.timestamp("us", tz="UTC"),
}

# 적재 시각. 원본에 없는 열이라 이름 앞에 밑줄을 둬 원본 컬럼과 갈라 놓는다.
LOADED_AT = "_loaded_at"

COLUMN_SQL = (
    "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS"
    " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
    " ORDER BY ORDINAL_POSITION")


def arrow_schema(columns: list[tuple[str, str]]) -> pa.Schema:
    """(컬럼명, MariaDB DATA_TYPE) 목록에서 Arrow 스키마를 만든다."""
    fields = [pa.field(name, _TYPE_MAP.get(dtype.lower(), pa.string()))
              for name, dtype in columns]
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    return pa.schema(fields)


def to_arrow(rows: list[dict], schema: pa.Schema,
             loaded_at: datetime) -> pa.Table:
    """행 목록을 스키마대로 눕힌다. 없는 컬럼은 널이다."""
    cols = {}
    for f in schema:
        if f.name == LOADED_AT:
            cols[f.name] = pa.array([loaded_at] * len(rows), type=f.type)
        else:
            cols[f.name] = pa.array([r.get(f.name) for r in rows], type=f.type)
    return pa.table(cols, schema=schema)
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: 12 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): MariaDB 컬럼에서 Arrow 스키마 도출"
```

---

## Task 4: 변경분 조회와 워터마크 판정을 만든다

`articles` 의 `updated_at` 이 워터마크다.
경계에서 행을 잃지도 겹치지도 않게 하는 것이 이 태스크의 요점이다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Modify: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: Task 3 의 `arrow_schema`
- Produces: `changes_sql(watermark)` · `snapshot_sql(table)` · `next_watermark(rows)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 변경분 조회 -----------------------------------------------------------

def test_워터마크가_없으면_전량을_가져온다():
    sql, params = warehouse.changes_sql(None)
    assert "WHERE" not in sql.upper()
    assert params == {}


def test_워터마크가_있으면_그보다_큰_것만():
    wm = _t(2026, 9, 2, 3)
    sql, params = warehouse.changes_sql(wm)
    assert "updated_at > :wm" in sql
    assert params == {"wm": wm}


def test_경계는_초과라서_같은_시각_행을_다시_안_가져온다():
    # 겹치면 같은 행이 두 번 쌓인다. 잃는 쪽보다 겹치는 쪽이 흔한 실수라 초과로 둔다.
    sql, _ = warehouse.changes_sql(_t(2026, 9, 2, 3))
    assert ">=" not in sql


def test_다음_워터마크는_가져온_행의_최댓값():
    rows = [{"updated_at": _t(2026, 9, 2, 1)},
            {"updated_at": _t(2026, 9, 2, 5)},
            {"updated_at": _t(2026, 9, 2, 3)}]
    assert warehouse.next_watermark(rows, previous=None) == _t(2026, 9, 2, 5)


def test_가져온_행이_없으면_워터마크가_그대로다():
    prev = _t(2026, 9, 2, 3)
    assert warehouse.next_watermark([], previous=prev) == prev


def test_updated_at_이_빈_행은_워터마크_계산에서_빠진다():
    rows = [{"updated_at": None}, {"updated_at": _t(2026, 9, 2, 5)}]
    assert warehouse.next_watermark(rows, previous=None) == _t(2026, 9, 2, 5)


def test_스냅샷은_표_이름을_그대로_박는다():
    assert warehouse.snapshot_sql("players") == "SELECT * FROM players"


def test_스냅샷_표_이름은_아는_것만_받는다():
    # 이름을 문자열로 이어 붙이는 자리라 바깥 값이 들어오면 안 된다.
    with pytest.raises(ValueError):
        warehouse.snapshot_sql("articles; DROP TABLE players")
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: `AttributeError: ... has no attribute 'changes_sql'`

- [ ] **Step 3: 구현을 쓴다**

```python
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
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: 20 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 변경분 조회와 워터마크 판정"
```

---

## Task 5: 보관 판정 셋을 만든다

무료 구간을 지키는 조건 셋이 전부 순수 판정이다.
GCS 에 붙기 전에 여기서 다 검증한다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Modify: `tests/test_warehouse.py`

**Interfaces:**
- Consumes: Task 2 의 `SNAPSHOT_DAILY_DAYS` · `EXPIRE_SNAPSHOT_DAYS` · `COMPACT_TARGET_BYTES`
- Produces: `snapshot_dates_to_drop(dates, today)` · `expire_before(now)` · `files_to_compact(sizes)`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
# --- 보관 판정 -------------------------------------------------------------

from datetime import date


def test_90일_안쪽_스냅샷은_하나도_안_지운다():
    today = date(2026, 12, 1)
    dates = [today - timedelta(days=n) for n in range(0, 90)]
    assert warehouse.snapshot_dates_to_drop(dates, today) == []


def test_90일_넘은_것_중_월요일은_남는다():
    today = date(2026, 12, 1)
    old_monday = date(2026, 6, 1)      # 월요일
    assert old_monday.isoweekday() == 1
    assert warehouse.snapshot_dates_to_drop([old_monday], today) == []


def test_90일_넘은_것_중_월요일이_아니면_지운다():
    today = date(2026, 12, 1)
    old_tuesday = date(2026, 6, 2)
    assert warehouse.snapshot_dates_to_drop([old_tuesday], today) == [old_tuesday]


def test_지울_날짜는_오름차순으로_돌려준다():
    today = date(2026, 12, 1)
    d1, d2 = date(2026, 6, 2), date(2026, 5, 5)
    assert warehouse.snapshot_dates_to_drop([d1, d2], today) == [d2, d1]


def test_스냅샷_만료_기준은_7일_전():
    now = _t(2026, 9, 10, 3)
    assert warehouse.expire_before(now) == _t(2026, 9, 3, 3)


def test_큰_파일은_컴팩션_대상이_아니다():
    big = warehouse.COMPACT_TARGET_BYTES + 1
    assert warehouse.files_to_compact({"a.parquet": big}) == []


def test_작은_파일이_둘_이상이면_대상():
    small = {"a.parquet": 1000, "b.parquet": 2000}
    assert sorted(warehouse.files_to_compact(small)) == ["a.parquet", "b.parquet"]


def test_작은_파일이_하나면_합칠_것이_없다():
    # 하나를 다시 쓰면 커밋만 늘고 부피는 그대로다.
    assert warehouse.files_to_compact({"a.parquet": 1000}) == []


def test_큰_것과_작은_것이_섞이면_작은_것만_고른다():
    mixed = {"big.parquet": warehouse.COMPACT_TARGET_BYTES + 1,
             "s1.parquet": 10, "s2.parquet": 20}
    assert sorted(warehouse.files_to_compact(mixed)) == ["s1.parquet", "s2.parquet"]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: `AttributeError: ... has no attribute 'snapshot_dates_to_drop'`

- [ ] **Step 3: 구현을 쓴다**

맨 위 import 에 `from datetime import date` 를 더한다.

```python
def snapshot_dates_to_drop(dates: list[date], today: date) -> list[date]:
    """전량 스냅샷 중 지울 날짜.

    90일 안쪽은 매일 남기고, 그보다 오래된 것은 월요일만 남긴다.
    안 지우면 `articles_snapshot` 이 하루 3.0 MiB 씩 쌓여 약 414일에 GCS 무료
    5 GB 를 채운다 (설계 §3.4).
    """
    cutoff = today - timedelta(days=SNAPSHOT_DAILY_DAYS)
    return sorted(d for d in dates
                  if d < cutoff and d.isoweekday() != 1)


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
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: 29 passed

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 스냅샷 보관 · 만료 · 컴팩션 대상 판정"
```

---

## Task 6: 카탈로그에 붙고 테이블을 만든다

여기부터 부수효과다.
로컬에서는 SQL 카탈로그로, 운영에서는 Lakehouse REST 카탈로그로 붙는다.
같은 코드가 둘 다 다뤄야 개발과 운영이 갈리지 않는다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`

**Interfaces:**
- Consumes: Task 3 의 `arrow_schema`
- Produces: `load_catalog()` · `ensure_table(catalog, name, schema)`

- [ ] **Step 1: 구현을 쓴다**

부수효과 절을 새로 열고 붙인다.

```python
# --- 카탈로그 (부수효과) ----------------------------------------------------

def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"환경변수 {name} 가 필요하다")
    return value


def load_catalog():
    """이력 카탈로그에 붙는다.

    `ICEBERG_CATALOG_URI` 가 있으면 그것으로 (운영 = Lakehouse REST), 없으면
    `ICEBERG_LOCAL_WAREHOUSE` 아래 SQLite 카탈로그로 붙는다 (개발 · 테스트).

    이름이 바뀌었지만 주소는 그대로다 — 2026-04-20 에 BigLake 가 Lakehouse 로,
    BigLake metastore 가 Lakehouse runtime catalog 로 이름이 바뀌었고
    API 주소와 IAM 이름은 `biglake` 를 그대로 쓴다.
    """
    from pyiceberg.catalog.rest import RestCatalog
    from pyiceberg.catalog.sql import SqlCatalog

    uri = os.environ.get("ICEBERG_CATALOG_URI")
    if uri:
        # `auth` 는 문자열이 아니라 딕셔너리다 — PyIceberg 가 `auth["type"]` 을 읽는다
        # (`pyiceberg/catalog/rest/__init__.py` 의 `auth_config.get("type")`).
        # 문자열을 주면 AttributeError 로 죽는다.
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


# 테이블 생성 속성. 안 주면 커밋마다 `metadata.json` 이 하나씩 영구히 쌓인다
# (실측 — 켠 테이블은 커밋 10회 뒤 4개가 남고 안 켠 테이블은 41회 뒤 42개가 남았다).
# 하루 8회 커밋이면 한 해에 객체 8,760개가 그냥 늘어난다.
TABLE_PROPERTIES = {
    "write.metadata.delete-after-commit.enabled": "true",
    "write.metadata.previous-versions-max": "5",
}


def ensure_table(catalog, name: str, schema):
    """테이블을 멱등하게 만들고 돌려준다.

    원본에 컬럼이 늘어나는 저장소라 (`schema.sql` 이 ALTER 를 계속 더한다)
    있는 테이블에는 union_by_name 으로 새 컬럼을 붙인다.
    """
    ident = f"{NAMESPACE}.{name}"
    from pyiceberg.exceptions import NoSuchTableError
    try:
        table = catalog.load_table(ident)
    except NoSuchTableError:
        return catalog.create_table(ident, schema=schema,
                                    properties=TABLE_PROPERTIES)
    with table.update_schema() as u:
        u.union_by_name(schema)
    return table
```

맨 위 import 에 `import os` 와 `from pathlib import Path` 를 더한다.

- [ ] **Step 2: 로컬 카탈로그로 스모크를 돌린다**

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-smoke uv run python -c "
from bullet_in import warehouse
import pyarrow as pa
c = warehouse.load_catalog()
warehouse.ensure_namespace(c)
s = warehouse.arrow_schema([('id','bigint'),('url','varchar')])
t = warehouse.ensure_table(c, 'smoke', s)
print('created', t.name())
t2 = warehouse.ensure_table(c, 'smoke', s)
print('idempotent', t2.name())
"
```

기대: `created` 와 `idempotent` 가 각각 찍히고 두 번째가 예외 없이 끝난다.

- [ ] **Step 3: 컬럼이 늘어도 견디는지 본다**

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-smoke uv run python -c "
from bullet_in import warehouse
c = warehouse.load_catalog()
s2 = warehouse.arrow_schema([('id','bigint'),('url','varchar'),('newcol','text')])
t = warehouse.ensure_table(c, 'smoke', s2)
print([f.name for f in t.schema().fields])
"
```

기대: `newcol` 이 목록에 있다.

- [ ] **Step 4: 커밋**

```bash
git add src/bullet_in/warehouse.py
git commit -m "feat(warehouse): 카탈로그 접속과 테이블 멱등 생성"
```

---

## Task 7: 변경분과 스냅샷을 실제로 적재한다

**Files:**
- Modify: `src/bullet_in/warehouse.py`

**Interfaces:**
- Consumes: Task 2 ~ 6 전부
- Produces: `run_load(now)` · `read_watermark(table)` · `columns_of(engine, table)`

- [ ] **Step 1: 구현을 쓴다**

```python
# --- 적재 (부수효과) --------------------------------------------------------

def columns_of(engine, table: str) -> list[tuple[str, str]]:
    """MariaDB 에서 컬럼 이름과 타입을 읽는다."""
    with engine.connect() as c:
        return [(r[0], r[1]) for r in
                c.execute(text(COLUMN_SQL), {"t": table}).all()]


def read_watermark(table) -> datetime | None:
    """이미 쌓인 변경분에서 마지막 `updated_at` 을 읽는다.

    상태 파일을 따로 두지 않는다 — 적재된 결과 자체가 워터마크라 둘이 어긋날 수 없다.
    """
    import pyarrow.compute as pc
    scan = table.scan(selected_fields=("updated_at",)).to_arrow()
    if scan.num_rows == 0:
        return None
    return pc.max(scan.column("updated_at")).as_py()


def _fetch(engine, sql: str, params: dict) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings().all()]


def run_load(now: datetime | None = None) -> None:
    """이번 회차의 적재를 끝낸다."""
    now = now or datetime.now(timezone.utc)
    engine = create_engine(_require_env("MARIADB_URL"))
    catalog = load_catalog()
    ensure_namespace(catalog)

    last_daily = _last_daily_at(catalog)
    for plan in plans_for(now, last_daily):
        if plan.mode == "changes":
            _load_changes(engine, catalog, plan, now)
        elif plan.mode == "snapshot":
            _load_snapshot(engine, catalog, plan, now)
        else:
            _load_ops(engine, catalog, plan, now)


def _load_changes(engine, catalog, plan: LoadPlan, now: datetime) -> None:
    schema = arrow_schema(columns_of(engine, plan.source))
    table = ensure_table(catalog, plan.table, schema)
    wm = read_watermark(table)
    sql, params = changes_sql(wm)
    rows = _fetch(engine, sql, params)
    if not rows:
        log.info("%s — 워터마크 %s 이후 바뀐 행이 없다", plan.table, wm)
        return
    table.append(to_arrow(rows, schema, loaded_at=now))
    log.info("%s — %d행 적재 (워터마크 %s → %s)",
             plan.table, len(rows), wm, next_watermark(rows, wm))


def _load_snapshot(engine, catalog, plan: LoadPlan, now: datetime) -> None:
    schema = arrow_schema(columns_of(engine, plan.source))
    table = ensure_table(catalog, plan.table, schema)
    rows = _fetch(engine, snapshot_sql(plan.source), {})
    arrow = to_arrow(rows, schema, loaded_at=now)
    # 같은 날 두 번 돌아도 그날 파티션만 갈린다 — 이것이 이 적재의 멱등성이다.
    table.overwrite(arrow, overwrite_filter=EqualTo(LOADED_DATE, now.date().isoformat()))
    log.info("%s — 전량 %d행 스냅샷 (%s)", plan.table, len(rows), now.date())
```

`EqualTo` 와 `LOADED_DATE` 가 필요하다.
맨 위에 `from pyiceberg.expressions import EqualTo` 를 더하고, 판정 절에 상수를 더한다.

```python
# 스냅샷 파티션 키. `_loaded_at` 에서 날짜만 떼어 문자열로 둔다 — 파티션 변환을
# 쓰면 카탈로그마다 지원이 갈리므로 열 하나로 단순하게 간다.
LOADED_DATE = "_loaded_date"
```

`arrow_schema` 와 `to_arrow` 에 이 열을 더한다.

```python
    fields.append(pa.field(LOADED_AT, pa.timestamp("us", tz="UTC")))
    fields.append(pa.field(LOADED_DATE, pa.string()))
    return pa.schema(fields)
```

```python
        if f.name == LOADED_AT:
            cols[f.name] = pa.array([loaded_at] * len(rows), type=f.type)
        elif f.name == LOADED_DATE:
            cols[f.name] = pa.array([loaded_at.date().isoformat()] * len(rows),
                                    type=f.type)
```

- [ ] **Step 2: Task 3 의 테스트를 고친다**

`_loaded_date` 가 늘었으므로 두 테스트의 기대값을 고친다.

```python
def test_적재시각_컬럼이_스키마_끝에_붙는다():
    s = warehouse.arrow_schema([("id", "bigint")])
    assert s.names == ["id", "_loaded_at", "_loaded_date"]
```

```python
def test_적재일_컬럼은_날짜_문자열이다():
    s = warehouse.arrow_schema([("id", "bigint")])
    t = warehouse.to_arrow([{"id": 1}], s, loaded_at=_t(2026, 9, 2, 3))
    assert t.column("_loaded_date").to_pylist() == ["2026-09-02"]
```

- [ ] **Step 3: 나머지 부수효과 함수를 쓴다**

```python
def _last_daily_at(catalog) -> datetime | None:
    """하루 1회짜리를 마지막으로 뜬 시각.

    `articles_snapshot` 의 `_loaded_at` 최댓값으로 본다 — 넷이 한 묶음으로 돌아서
    하나만 보면 된다. 테이블이 아직 없으면 한 번도 안 뜬 것이다.
    """
    from pyiceberg.exceptions import NoSuchTableError
    import pyarrow.compute as pc
    try:
        t = catalog.load_table(f"{NAMESPACE}.articles_snapshot")
    except NoSuchTableError:
        return None
    scan = t.scan(selected_fields=(LOADED_AT,)).to_arrow()
    if scan.num_rows == 0:
        return None
    return pc.max(scan.column(LOADED_AT)).as_py()


def _load_ops(engine, catalog, plan: LoadPlan, now: datetime) -> None:
    """`pipeline_runs` 와 `source_freshness` 를 하루 1회 붙인다.

    둘은 삽입만 일어나 원본이 이미 이력이다. 무료 구간을 지키려고 하루 1회로 묶었다.
    """
    for source, key in (("pipeline_runs", "started_at"),
                        ("source_freshness", "checked_at")):
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


def _max_of(table, column: str) -> datetime | None:
    import pyarrow.compute as pc
    scan = table.scan(selected_fields=(column,)).to_arrow()
    if scan.num_rows == 0:
        return None
    return pc.max(scan.column(column)).as_py()
```

`TABLES` 를 실제 만드는 이름과 맞춘다.

```python
TABLES = ("articles_changes", "articles_snapshot", "players_snapshot",
          "article_players_snapshot", "ops_daily")
```

`ops_daily` 는 계획 이름이고 실제 테이블은 `ops_pipeline_runs` 와 `ops_source_freshness` 둘이다.
`_load_ops` 가 둘을 함께 만든다.

맨 위 import 에 `from sqlalchemy import create_engine, text` 를 더한다.

- [ ] **Step 4: 테스트가 여전히 통과하는지 본다**

```bash
uv run pytest tests/test_warehouse.py -q
```

기대: 30 passed

- [ ] **Step 5: 로컬 카탈로그로 실데이터 적재를 돌린다**

운영 DB 를 읽기만 한다.
VM 의 MariaDB 에 SSH 터널을 뚫거나, 로컬 docker 에 백업을 되살려 쓴다.

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-real MARIADB_URL="<로컬 복구본>" \
  uv run python -c "
from bullet_in import warehouse
import logging; logging.basicConfig(level=logging.INFO)
warehouse.run_load()
"
```

기대: 다섯 테이블이 만들어지고 행 수가 로그에 찍힌다.

- [ ] **Step 6: 같은 명령을 한 번 더 돌려 멱등을 확인한다**

기대: 변경분은 「바뀐 행이 없다」 가 찍히고 스냅샷은 같은 날 파티션을 갈아 행 수가 늘지 않는다.

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-real uv run python -c "
from bullet_in import warehouse
c = warehouse.load_catalog()
for n in ('articles_changes','articles_snapshot','players_snapshot'):
    t = c.load_table(f'{warehouse.NAMESPACE}.{n}')
    print(n, t.scan().to_arrow().num_rows)
"
```

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/warehouse.py tests/test_warehouse.py
git commit -m "feat(warehouse): 변경분 · 전량 스냅샷 · 운영 기록 적재"
```

---

## Task 8: 컴팩션을 만든다

PyIceberg 에 없는 기능이라 직접 만든다.
이 안건의 값어치가 여기에 있다.

**Files:**
- Modify: `src/bullet_in/warehouse.py`

**Interfaces:**
- Consumes: Task 5 의 `files_to_compact`
- Produces: `compact(table)` · `run_maintenance(now)`

- [ ] **Step 1: 구현을 쓴다**

```python
# --- 유지보수 (부수효과) ----------------------------------------------------

def compact(table) -> dict:
    """조각난 데이터 파일을 한 파일로 다시 쓴다.

    PyIceberg 는 컴팩션을 제공하지 않는다 (공식 문서 「Compaction is planned」).
    fast append 가 커밋마다 파일 하나를 만들어서, 회차마다 조금씩 쓰면 Parquet
    압축이 안 들어 행당 부피가 6.15배가 된다 (실측 19,430 B 대 3,160 B).

    방법은 단순하다 — 작은 파일들이 담은 행을 전부 읽어서 그 자리를 덮어쓴다.
    Iceberg 의 스냅샷 격리 덕에 이 사이에 읽는 쪽은 옛 스냅샷을 계속 본다.
    """
    sizes = {f.file.file_path: f.file.file_size_in_bytes
             for f in table.scan().plan_files()}
    targets = files_to_compact(sizes)
    if not targets:
        return {"files_before": len(sizes), "compacted": 0}

    before = sum(sizes[p] for p in targets)
    rows = table.scan().to_arrow()
    table.overwrite(rows)
    after = sum(f.file.file_size_in_bytes for f in table.scan().plan_files())
    log.info("컴팩션 — 파일 %d개 %s바이트를 다시 씀 → %s바이트",
             len(targets), f"{before:,}", f"{after:,}")
    return {"files_before": len(sizes), "compacted": len(targets),
            "bytes_before": before, "bytes_after": after}


def expire(table, now: datetime) -> int:
    """오래된 Iceberg 스냅샷을 만료한다.

    부피가 아니라 `metadata.json` 1 MB 한도 때문에 한다.
    안 하면 약 124일에 커밋이 실패한다 (설계 §2.6).

    호출 경로가 `table.maintenance` 아래다 — `table.expire_snapshots()` 는
    PyIceberg 0.11.1 에 없다 (2026-09-02 확인). 인자도 밀리초가 아니라 datetime 이다.
    """
    before = len(table.metadata.snapshots)
    table.maintenance.expire_snapshots().older_than(expire_before(now)).commit()
    table.refresh()
    after = len(table.metadata.snapshots)
    log.info("스냅샷 만료 — %d개에서 %d개로", before, after)
    return before - after


def drop_old_snapshot_dates(table, today: date) -> int:
    """90일 넘은 전량 스냅샷 중 월요일이 아닌 날을 지운다."""
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
        log.info("스냅샷 파티션 %d일치 삭제 (%s ~ %s)",
                 len(drop), drop[0], drop[-1])
    return len(drop)


def run_maintenance(now: datetime | None = None) -> None:
    """컴팩션 · 스냅샷 만료 · 오래된 파티션 솎기를 한 번에."""
    now = now or datetime.now(timezone.utc)
    catalog = load_catalog()
    from pyiceberg.exceptions import NoSuchTableError
    for name in _existing_tables(catalog):
        try:
            table = catalog.load_table(f"{NAMESPACE}.{name}")
        except NoSuchTableError:
            continue
        if name.endswith("_snapshot"):
            drop_old_snapshot_dates(table, now.date())
        compact(table)
        expire(table, now)
        # 남은 스냅샷 수를 남긴다 — 1 MB 한도까지 얼마나 남았는지 보는 눈이다.
        log.info("%s — 남은 스냅샷 %d개", name, len(table.metadata.snapshots))


def _existing_tables(catalog) -> list[str]:
    return [t[-1] for t in catalog.list_tables(NAMESPACE)]
```

- [ ] **Step 2: 컴팩션이 실제로 부피를 줄이는지 잰다**

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-real uv run python -c "
from bullet_in import warehouse
import logging; logging.basicConfig(level=logging.INFO)
c = warehouse.load_catalog()
t = c.load_table(f'{warehouse.NAMESPACE}.articles_changes')
print(warehouse.compact(t))
"
```

기대: `bytes_after` 가 `bytes_before` 보다 작다.
표본이 한 커밋뿐이라 파일이 하나면 `compacted: 0` 이 나온다.
그때는 위 Task 7 Step 5 를 몇 번 더 돌려 조각을 만든 뒤 다시 잰다.

- [ ] **Step 3: 만료가 스냅샷 수를 줄이는지 본다**

```bash
ICEBERG_LOCAL_WAREHOUSE=/tmp/ice-real uv run python -c "
from bullet_in import warehouse
from datetime import datetime, timezone, timedelta
import logging; logging.basicConfig(level=logging.INFO)
c = warehouse.load_catalog()
t = c.load_table(f'{warehouse.NAMESPACE}.articles_changes')
print('before', len(t.metadata.snapshots))
warehouse.expire(t, datetime.now(timezone.utc) + timedelta(days=30))
print('rows', t.scan().to_arrow().num_rows)
"
```

기대: 30일 뒤 시점으로 부르면 스냅샷이 하나만 남고 행 수는 그대로다.
같은 실험을 미리 돌려서 스냅샷 6개가 1개로 줄고 행 6개가 보존되는 것을 확인했다.

- [ ] **Step 4: 커밋**

```bash
git add src/bullet_in/warehouse.py
git commit -m "feat(warehouse): 컴팩션 · 스냅샷 만료 · 오래된 파티션 솎기"
```

---

## Task 9: CLI 와 systemd 유닛을 붙인다

**Files:**
- Modify: `src/bullet_in/warehouse.py`
- Create: `infra/systemd/bullet-in-warehouse.service`
- Create: `infra/systemd/bullet-in-warehouse.timer`
- Create: `infra/systemd/bullet-in-warehouse-maint.service`
- Create: `infra/systemd/bullet-in-warehouse-maint.timer`
- Modify: `infra/systemd/install-units.sh`

**Interfaces:**
- Consumes: Task 7 의 `run_load` · Task 8 의 `run_maintenance`
- Produces: `python -m bullet_in.warehouse load` · `... maint` · `... show`

- [ ] **Step 1: CLI 를 쓴다**

`warehouse.py` 끝에 붙인다.

```python
def run_show() -> None:
    """쌓인 테이블의 행 수와 남은 스냅샷 수를 보여 준다."""
    catalog = load_catalog()
    for name in sorted(_existing_tables(catalog)):
        t = catalog.load_table(f"{NAMESPACE}.{name}")
        files = list(t.scan().plan_files())
        size = sum(f.file.file_size_in_bytes for f in files)
        print(f"{name:28} {t.scan().to_arrow().num_rows:>8,}행  "
              f"파일 {len(files):>3}개  {size:>12,}B  "
              f"스냅샷 {len(t.metadata.snapshots):>3}개")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="운영 마트 이력 적재")
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
```

맨 위 import 에 `import sys` 를 더한다.

- [ ] **Step 2: 적재 유닛을 만든다**

`infra/systemd/bullet-in-warehouse.service`

```ini
[Unit]
Description=bullet-in 운영 마트 이력 적재 (MariaDB -> Iceberg on GCS)
Wants=docker.service
After=docker.service network-online.target
OnFailure=bullet-in-fail-notify@%n.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.warehouse load
TimeoutStartSec=1800
```

`infra/systemd/bullet-in-warehouse.timer`

```ini
[Unit]
Description=bullet-in 이력 적재 3시간 간격 (회차보다 20분 뒤)

[Timer]
OnCalendar=*-*-* 00,03,06,09,12,15,18,21:20:00 UTC
Persistent=true
RandomizedDelaySec=180

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: 유지보수 유닛을 만든다**

`infra/systemd/bullet-in-warehouse-maint.service`

```ini
[Unit]
Description=bullet-in 이력 유지보수 (컴팩션 · 스냅샷 만료 · 파티션 솎기)
After=network-online.target
OnFailure=bullet-in-fail-notify@%n.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.warehouse maint
TimeoutStartSec=3600
```

`infra/systemd/bullet-in-warehouse-maint.timer`

```ini
[Unit]
Description=bullet-in 이력 유지보수 1일 1회 (KST 11:40 · 백업과 회차 사이)

[Timer]
OnCalendar=*-*-* 02:40:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

- [ ] **Step 4: 설치 스크립트에 넷을 더한다**

`infra/systemd/install-units.sh` 의 유닛 목록에 네 파일 이름을 더한다.
기존 목록이 어떤 모양인지 먼저 읽고 그 형식에 맞춘다.

- [ ] **Step 5: 유닛 문법을 검사한다**

```bash
uv run python -c "
from pathlib import Path
for p in sorted(Path('infra/systemd').glob('bullet-in-warehouse*')):
    txt = p.read_text()
    assert '[Unit]' in txt, p
    print(p.name, len(txt.splitlines()), '줄')
"
```

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/warehouse.py infra/systemd/
git commit -m "feat(warehouse): CLI 서브커맨드와 systemd 유닛 넷"
```

---

## Task 10: GCP 프로젝트와 카탈로그를 만든다

여기서 사용자 개입이 필요할 수 있다.
로컬 `gcloud` 가 이미 `benidjor@gmail.com` 으로 인증돼 있어 프로젝트 생성까지는 진행할 수 있다.

**Files:**
- 저장소 변경 없음 (`.env` 는 버전 관리 밖이다)

**Interfaces:**
- Produces: `ICEBERG_CATALOG_URI` · `ICEBERG_WAREHOUSE` 환경변수

- [ ] **Step 1: 프로젝트를 만들고 결제를 잇는다**

```bash
gcloud projects create bullet-in-lakehouse --name="bullet-in lakehouse"
gcloud billing projects link bullet-in-lakehouse \
  --billing-account=01E3C1-098D9D-58E612
```

- [ ] **Step 2: API 를 켠다**

```bash
gcloud services enable biglake.googleapis.com storage.googleapis.com \
  --project=bullet-in-lakehouse
```

- [ ] **Step 3: 버킷을 만든다**

무료 5 GB 가 `us-central1` 에만 적용된다.

```bash
gcloud storage buckets create gs://bullet-in-lakehouse-prod \
  --project=bullet-in-lakehouse --location=us-central1 \
  --uniform-bucket-level-access
```

- [ ] **Step 4: 카탈로그를 만든다**

```bash
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://biglake.googleapis.com/v1/projects/bullet-in-lakehouse/locations/us-central1/catalogs?catalogId=bullet_in" \
  -d '{"type":"CATALOG_TYPE_ICEBERG_REST"}'
```

응답이 이 형태와 다르면 그때 문서를 다시 본다.
API 이름이 `biglake` 그대로인 것은 확인했다 (설계 §2.2).

- [ ] **Step 5: 서비스 계정을 만들고 권한을 준다**

백업이 쓰는 것과 별도로 만든다.
백업 계정에는 삭제 권한이 없는데 이력 유지보수는 파일을 지워야 하기 때문이다.

```bash
gcloud iam service-accounts create bullet-in-lakehouse \
  --project=bullet-in-lakehouse --display-name="bullet-in lakehouse writer"

gcloud projects add-iam-policy-binding bullet-in-lakehouse \
  --member="serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com" \
  --role="roles/biglake.editor"

gcloud storage buckets add-iam-policy-binding gs://bullet-in-lakehouse-prod \
  --member="serviceAccount:bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"
```

- [ ] **Step 6: 키를 만들어 VM 에 둔다**

```bash
gcloud iam service-accounts keys create /tmp/lakehouse-key.json \
  --iam-account=bullet-in-lakehouse@bullet-in-lakehouse.iam.gserviceaccount.com
scp -i ~/.ssh/seoulnow_deploy /tmp/lakehouse-key.json \
  ubuntu@155.248.164.17:/home/ubuntu/bullet-in/lakehouse-key.json
```

키 파일을 만든 뒤 로컬 사본을 지운다.

- [ ] **Step 7: VM 의 `.env` 에 세 줄을 더한다**

```
GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/bullet-in/lakehouse-key.json
ICEBERG_CATALOG_URI=https://biglake.googleapis.com/iceberg/v1/restcatalog
ICEBERG_WAREHOUSE=gs://bullet-in-lakehouse-prod
```

`GOOGLE_APPLICATION_CREDENTIALS` 는 백업도 읽는 이름이다.
백업이 쓰는 자격과 겹치면 백업 계정의 권한이 바뀌므로, 백업 유닛이 다른 이름을 쓰고 있는지 먼저 확인한다.
겹치면 이력 쪽 유닛에서만 `Environment=` 로 덮어쓴다.

- [ ] **Step 8: 접속 스모크를 돌린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "/home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in python -m bullet_in.warehouse show"
```

기대: 테이블이 하나도 없으니 아무 줄도 안 찍히고 오류 없이 끝난다.
인증이나 주소가 틀리면 여기서 드러난다.

---

## Task 11: 운영에서 첫 적재를 돌리고 관측한다

**Files:**
- Create: `docs/runbook/2026-09-02-warehouse-history-load.md`

- [ ] **Step 1: 유닛을 설치하고 손으로 한 번 돌린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "cd /home/ubuntu/bullet-in && sudo bash infra/systemd/install-units.sh"
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl start bullet-in-warehouse.service"
```

- [ ] **Step 2: 결과를 확인한다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "systemctl status bullet-in-warehouse.service --no-pager -l | head -30"
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "/home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in python -m bullet_in.warehouse show"
```

기대: `articles_snapshot` 이 999행 근처, `players_snapshot` 이 556행 근처다.
행 수를 MariaDB 실제 값과 대조한다.

- [ ] **Step 3: 두 번 돌려 멱등을 확인한다**

같은 명령을 한 번 더 돌리고 `show` 의 행 수가 늘지 않는지 본다.
늘면 스냅샷 덮어쓰기가 안 되는 것이므로 여기서 멈추고 원인을 찾는다.

- [ ] **Step 4: 유지보수를 한 번 돌린다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl start bullet-in-warehouse-maint.service"
```

- [ ] **Step 5: 타이머를 켠다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "sudo systemctl enable --now bullet-in-warehouse.timer bullet-in-warehouse-maint.timer"
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "systemctl list-timers --all --no-pager | grep warehouse"
```

- [ ] **Step 6: 런북을 쓴다**

`docs/runbook/2026-09-02-warehouse-history-load.md` 에 담을 것은 이렇다.

- 무엇이 언제 도는가 (타이머 둘의 시각과 회차와의 간격)
- 쌓인 것을 보는 명령 (`show`)
- 적재가 실패했을 때 무엇부터 보는가 (유닛 상태 · 인증 · 카탈로그 접속 순)
- **비용을 어떻게 확인하는가** — GCP 결제 보고서를 서비스와 프로젝트 두 기준으로 각각 보고, `BigLake Table Management` SKU 가 0인지 확인한다
- 남은 스냅샷 수가 늘기만 하면 무엇을 의심하는가 (`metadata.json` 1 MB 한도)

- [ ] **Step 7: 첫 결제 대조 일정을 남긴다**

Class A 실측값이 하한선이라 (설계 §2.3) 첫 주와 첫 달에 결제 보고서로 대조해야 한다.
런북에 날짜를 적고 잔여 안건 메모리에도 남긴다.

- [ ] **Step 8: 커밋**

```bash
git add docs/runbook/2026-09-02-warehouse-history-load.md
git commit -m "docs(runbook): 이력 적재 운영 절차와 비용 확인 방법"
```

---

## Task 12: 전체 검사와 PR

- [ ] **Step 1: 전체 테스트를 돌린다**

```bash
uv run pytest -q
```

기대: 기존 테스트가 하나도 안 깨진다.

- [ ] **Step 2: 회차를 안 건드렸는지 확인한다**

```bash
git diff origin/main --stat -- src/bullet_in/run.py dbt/
```

기대: 출력이 비어 있다.

- [ ] **Step 3: 문서 서식을 검사한다**

```bash
uv run python .claude/hooks/check-doc-format.py < /dev/null || true
```

훅은 저장할 때 자동으로 돈다.
CI 는 파일 전체를 보므로 손댄 문서에 옛 위반이 남아 있지 않은지 함께 본다.

- [ ] **Step 4: PR 본문을 쓰고 검사기를 돌린다**

```bash
uv run python .claude/tools/check-pr-format.py --body /tmp/pr-body.md --title "<제목>"
```

- [ ] **Step 5: humanize-korean 문체 점검을 통과시킨다**

PR 본문과 런북이 대상이다.
변경 금지 목록에 서식 규칙 (§2.2) · 명사형 불릿 · 수치 · 경로를 명시한다.
작업 파일은 스크래치패드에 만든다.

- [ ] **Step 6: push 하고 PR 을 만든다**

머지는 사용자가 한다.

---

## 자체 점검

**설계 항목 대조.**

| 설계 절 | 태스크 |
| --- | --- |
| §3.1 무엇을 언제 적재하는가 | Task 2 · 7 |
| §3.2 스냅샷 대조로 이력 도출 | Task 7 (`_load_snapshot` 의 날짜 파티션 덮어쓰기) |
| §3.3 회차 밖 별도 타이머 | Task 9 |
| §3.4 조건 셋 (만료 · 컴팩션 · 솎기) | Task 5 · 8 |
| §3.5 프로젝트 · 권한 | Task 10 |
| §5 위험 (결제 대조 · SKU 확인) | Task 11 Step 6 · 7 |

**계획서에 적은 PyIceberg 호출을 실물에 대 봤다 (2026-09-02 · 0.11.1 · pyarrow 25.0.1).**
계획서 코드의 결함은 구현까지 살아남아서, 쓰고 나서 한 번 돌려 보았다.
넷이 걸렸고 넷 다 위 태스크에 고쳐 넣었다.

| 처음 쓴 것 | 실제 | 어떻게 알았나 |
| --- | --- | --- |
| `table.expire_snapshots()` | `table.maintenance.expire_snapshots()` | `AttributeError` |
| `expire_snapshots_older_than(밀리초)` | `older_than(datetime)` | 시그니처 조회 |
| `auth="google"` | `auth={"type": "google", ...}` | 카탈로그 소스에서 `auth_config.get("type")` 확인 |
| 테이블 속성 없음 | `write.metadata.delete-after-commit.enabled` 필요 | 커밋 41회에 `metadata.json` 42개가 남는 것을 세어서 |

같은 실험에서 통과한 것도 적어 둔다.
`overwrite(df, overwrite_filter=EqualTo(...))` 로 날짜 파티션만 갈아 끼우는 것, `delete(EqualTo(...))`, `update_schema().union_by_name(pa.Schema)`, `scan(selected_fields=...)`, `plan_files()` 의 `file.file_size_in_bytes` 는 전부 있는 그대로 동작했다.

**아직 답이 없는 것 둘.**

- Task 7 Step 5 가 「로컬 복구본」 을 전제한다.
  운영 DB 에 직접 붙어 읽기만 하는 편이 간단할 수 있는데, 그러면 로컬에서 운영 자격을 쓰게 된다.
  실행자가 이 지점에서 한 번 판단해야 한다.
- Task 10 Step 4 의 카탈로그 생성 API 응답 형태를 확인하지 못했다.
  문서에 콘솔 화면 안내만 있고 REST 예시가 없어서, 실패하면 콘솔로 만들고 그 사실을 런북에 적는다.
