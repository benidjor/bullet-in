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
