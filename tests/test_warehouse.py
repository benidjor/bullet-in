"""이력 레이크하우스의 판정 부분 테스트 — 적재 대상 · 워터마크 · 보관."""
from datetime import date, datetime, timedelta, timezone

import pyarrow as pa
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


# --- Arrow 스키마 도출 -----------------------------------------------------

def test_문자열_계열은_전부_string():
    s = warehouse.arrow_schema([("title_ko", "text"), ("url", "varchar"),
                                ("content_hash", "char"), ("images_json", "json")])
    assert [s.field(n).type for n in
            ("title_ko", "url", "content_hash", "images_json")] == [pa.string()] * 4


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


def test_적재_시각과_날짜_컬럼이_스키마_끝에_붙는다():
    s = warehouse.arrow_schema([("id", "bigint")])
    assert s.names == ["id", "_loaded_at", "_loaded_date"]


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


def test_적재일_컬럼은_날짜_문자열이다():
    # 스냅샷을 날짜로 갈아 끼우는 자리라 파티션 키가 된다.
    s = warehouse.arrow_schema([("id", "bigint")])
    t = warehouse.to_arrow([{"id": 1}], s, loaded_at=_t(2026, 9, 2, 3))
    assert t.column("_loaded_date").to_pylist() == ["2026-09-02"]


def test_변경분_조회에_워터마크가_없으면_전량을_가져온다():
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


def test_시간대_없는_DATETIME_은_UTC_로_읽는다():
    # MariaDB 의 DATETIME 은 시간대 없이 온다. 이 저장소는 UTC 를 저장하므로
    # 그대로 UTC 로 읽는 것이 맞다. 조용히 9시간 어긋날 수 있는 자리라 고정해 둔다.
    s = warehouse.arrow_schema([("created_at", "datetime")])
    naive = datetime(2026, 9, 2, 3, 0, 0)
    t = warehouse.to_arrow([{"created_at": naive}], s, loaded_at=_t(2026, 9, 2))
    assert t.column("created_at").to_pylist() == [_t(2026, 9, 2, 3)]


# --- 보관 판정 -------------------------------------------------------------

def test_90일_안쪽_스냅샷은_하나도_안_지운다():
    today = date(2026, 12, 1)
    dates = [today - timedelta(days=n) for n in range(0, 90)]
    assert warehouse.snapshot_dates_to_drop(dates, today) == []


def test_90일_넘은_것_중_월요일은_남는다():
    today = date(2026, 12, 1)
    old_monday = date(2026, 6, 1)
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


# --- 카탈로그 · 테이블 (로컬 파일시스템) -------------------------------------

@pytest.fixture
def local_catalog(tmp_path, monkeypatch):
    """운영과 같은 코드를 로컬 SQLite 카탈로그로 돌린다."""
    monkeypatch.delenv("ICEBERG_CATALOG_URI", raising=False)
    monkeypatch.setenv("ICEBERG_LOCAL_WAREHOUSE", str(tmp_path / "wh"))
    catalog = warehouse.load_catalog()
    warehouse.ensure_namespace(catalog)
    return catalog


def _schema():
    return warehouse.arrow_schema([("id", "bigint"), ("url", "varchar")])


def test_네임스페이스는_두_번_만들어도_안_죽는다(local_catalog):
    warehouse.ensure_namespace(local_catalog)


def test_테이블_생성이_멱등이다(local_catalog):
    a = warehouse.ensure_table(local_catalog, "t", _schema())
    b = warehouse.ensure_table(local_catalog, "t", _schema())
    assert a.name() == b.name()


def test_원본에_컬럼이_늘면_스키마에_붙는다(local_catalog):
    # schema.sql 이 ALTER 로 컬럼을 계속 더하는 저장소라 이 성질이 필요하다.
    warehouse.ensure_table(local_catalog, "t", _schema())
    wider = warehouse.arrow_schema([("id", "bigint"), ("url", "varchar"),
                                    ("newcol", "text")])
    t = warehouse.ensure_table(local_catalog, "t", wider)
    assert "newcol" in [f.name for f in t.schema().fields]


def test_메타데이터_정리_속성이_붙는다(local_catalog):
    # 안 붙이면 커밋마다 metadata.json 이 하나씩 영구히 쌓인다 (실측 41회에 42개).
    # 오류가 안 나고 조용히 누적되는 자리라 여기서 고정한다.
    t = warehouse.ensure_table(local_catalog, "t", _schema())
    assert t.properties["write.metadata.delete-after-commit.enabled"] == "true"
    assert int(t.properties["write.metadata.previous-versions-max"]) >= 1


# --- 적재 -------------------------------------------------------------------

@pytest.fixture
def fake_mart(monkeypatch):
    """MariaDB 자리에 메모리 위의 행을 둔다.

    재려는 것은 SQL 이 아니라 적재 경로다 — 워터마크를 어디서 읽고, 무엇을 덧붙이고,
    같은 날 두 번 돌면 어떻게 되는지. Iceberg 쪽은 진짜로 돈다.
    """
    state = {"columns": [("id", "bigint"), ("url", "varchar"),
                         ("updated_at", "datetime")],
             "rows": []}

    def _columns_of(engine, table):
        return state["columns"]

    def _fetch(engine, sql, params):
        rows = state["rows"]
        wm = params.get("wm")
        if wm is not None:
            rows = [r for r in rows if r["updated_at"] > wm]
        return rows

    monkeypatch.setattr(warehouse, "columns_of", _columns_of)
    monkeypatch.setattr(warehouse, "_fetch", _fetch)
    return state


def test_변경분은_워터마크_이후만_가져온다(local_catalog, fake_mart):
    plan = warehouse.LoadPlan("articles_changes", "articles", "changes")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": _t(2026, 9, 2, 1)},
                         {"id": 2, "url": "b", "updated_at": _t(2026, 9, 2, 5)}]
    assert warehouse.load_changes(None, local_catalog, plan, _t(2026, 9, 2, 6)) == 2
    # 원본이 그대로면 두 번째 회차는 가져올 것이 없다.
    assert warehouse.load_changes(None, local_catalog, plan, _t(2026, 9, 2, 7)) == 0


def test_변경분은_새로_바뀐_행만_덧붙인다(local_catalog, fake_mart):
    plan = warehouse.LoadPlan("articles_changes", "articles", "changes")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": _t(2026, 9, 2, 1)}]
    warehouse.load_changes(None, local_catalog, plan, _t(2026, 9, 2, 2))
    fake_mart["rows"].append({"id": 2, "url": "b", "updated_at": _t(2026, 9, 2, 9)})
    assert warehouse.load_changes(None, local_catalog, plan, _t(2026, 9, 2, 10)) == 1
    t = local_catalog.load_table(f"{warehouse.NAMESPACE}.articles_changes")
    assert t.scan().to_arrow().num_rows == 2


def test_스냅샷은_같은_날_두_번_돌려도_행이_안_는다(local_catalog, fake_mart):
    # 이 덮어쓰기가 적재의 멱등성이다.
    plan = warehouse.LoadPlan("players_snapshot", "players", "snapshot")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": None},
                         {"id": 2, "url": "b", "updated_at": None}]
    warehouse.load_snapshot(None, local_catalog, plan, _t(2026, 9, 2, 3))
    warehouse.load_snapshot(None, local_catalog, plan, _t(2026, 9, 2, 9))
    t = local_catalog.load_table(f"{warehouse.NAMESPACE}.players_snapshot")
    assert t.scan().to_arrow().num_rows == 2


def test_스냅샷은_날이_바뀌면_쌓인다(local_catalog, fake_mart):
    plan = warehouse.LoadPlan("players_snapshot", "players", "snapshot")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": None},
                         {"id": 2, "url": "b", "updated_at": None}]
    warehouse.load_snapshot(None, local_catalog, plan, _t(2026, 9, 2, 3))
    warehouse.load_snapshot(None, local_catalog, plan, _t(2026, 9, 3, 3))
    t = local_catalog.load_table(f"{warehouse.NAMESPACE}.players_snapshot")
    assert t.scan().to_arrow().num_rows == 4
    assert set(t.scan().to_arrow().column("_loaded_date").to_pylist()) == {
        "2026-09-02", "2026-09-03"}


# --- 유지보수 (컴팩션 · 만료 · 솎기) ----------------------------------------

def _many_commits(catalog, fake_mart, n: int):
    """회차마다 조금씩 쓰는 실제 모양을 만든다 — 커밋 하나에 파일 하나."""
    plan = warehouse.LoadPlan("articles_changes", "articles", "changes")
    for i in range(n):
        fake_mart["rows"] = [{"id": i, "url": f"u{i}",
                              "updated_at": _t(2026, 9, 2) + timedelta(hours=i)}]
        warehouse.load_changes(None, catalog, plan, _t(2026, 9, 2))
    return catalog.load_table(f"{warehouse.NAMESPACE}.articles_changes")


def test_컴팩션이_조각_파일을_하나로_합친다(local_catalog, fake_mart):
    t = _many_commits(local_catalog, fake_mart, 5)
    assert len(list(t.scan().plan_files())) == 5
    result = warehouse.compact(t)
    t.refresh()
    assert result["compacted"] == 5
    assert len(list(t.scan().plan_files())) == 1


def test_컴팩션이_행을_잃지_않는다(local_catalog, fake_mart):
    t = _many_commits(local_catalog, fake_mart, 5)
    before = t.scan().to_arrow().num_rows
    warehouse.compact(t)
    t.refresh()
    assert t.scan().to_arrow().num_rows == before


def test_합칠_것이_없으면_커밋하지_않는다(local_catalog, fake_mart):
    t = _many_commits(local_catalog, fake_mart, 1)
    snapshots_before = len(t.metadata.snapshots)
    assert warehouse.compact(t)["compacted"] == 0
    t.refresh()
    assert len(t.metadata.snapshots) == snapshots_before


def test_만료가_스냅샷을_줄이고_행은_남긴다(local_catalog, fake_mart):
    t = _many_commits(local_catalog, fake_mart, 5)
    rows_before = t.scan().to_arrow().num_rows
    assert len(t.metadata.snapshots) == 5
    # 만료 기준을 넘기려고 한참 뒤 시점으로 부른다.
    warehouse.expire(t, _t(2026, 10, 1))
    t.refresh()
    assert len(t.metadata.snapshots) == 1
    assert t.scan().to_arrow().num_rows == rows_before


def test_오래된_스냅샷_파티션을_솎는다(local_catalog, fake_mart):
    plan = warehouse.LoadPlan("players_snapshot", "players", "snapshot")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": None}]
    # 90일 넘은 화요일 하나와 월요일 하나, 그리고 최근 하루.
    for day in (datetime(2026, 6, 2, tzinfo=timezone.utc),
                datetime(2026, 6, 1, tzinfo=timezone.utc),
                datetime(2026, 11, 30, tzinfo=timezone.utc)):
        warehouse.load_snapshot(None, local_catalog, plan, day)
    t = local_catalog.load_table(f"{warehouse.NAMESPACE}.players_snapshot")
    dropped = warehouse.drop_old_snapshot_dates(t, date(2026, 12, 1))
    t.refresh()
    assert dropped == 1
    left = set(t.scan().to_arrow().column("_loaded_date").to_pylist())
    assert left == {"2026-06-01", "2026-11-30"}


def test_하루1회_판정이_스냅샷_적재를_따라간다(local_catalog, fake_mart):
    # 스냅샷을 뜬 날에는 그날 다시 불러도 변경분만 대상이 된다.
    plan = warehouse.LoadPlan("articles_snapshot", "articles", "snapshot")
    fake_mart["rows"] = [{"id": 1, "url": "a", "updated_at": None}]
    assert warehouse._last_daily_at(local_catalog) is None
    warehouse.load_snapshot(None, local_catalog, plan, _t(2026, 9, 2, 3))
    assert warehouse._last_daily_at(local_catalog) == _t(2026, 9, 2, 3)
    plans = warehouse.plans_for(_t(2026, 9, 2, 12),
                                warehouse._last_daily_at(local_catalog))
    assert [p.table for p in plans] == ["articles_changes"]
