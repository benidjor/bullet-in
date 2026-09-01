"""이력 레이크하우스의 판정 부분 테스트 — 적재 대상 · 워터마크 · 보관."""
from datetime import datetime, timezone

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


def test_시간대_없는_DATETIME_은_UTC_로_읽는다():
    # MariaDB 의 DATETIME 은 시간대 없이 온다. 이 저장소는 UTC 를 저장하므로
    # 그대로 UTC 로 읽는 것이 맞다. 조용히 9시간 어긋날 수 있는 자리라 고정해 둔다.
    s = warehouse.arrow_schema([("created_at", "datetime")])
    naive = datetime(2026, 9, 2, 3, 0, 0)
    t = warehouse.to_arrow([{"created_at": naive}], s, loaded_at=_t(2026, 9, 2))
    assert t.column("created_at").to_pylist() == [_t(2026, 9, 2, 3)]
