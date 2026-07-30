"""선수 명단 저장소 — 인명 사전의 단일 원천 (스펙 §5)."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.engine import Engine

# 게이트 · 서빙 사전 술어 — 후보 (자동 등재) 배제 + archived 잔류 (스펙 §3.2 · §8)
_DICT_WHERE = "status IN ('confirmed','archived') AND ko_name IS NOT NULL"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlayerStore:
    """players · article_players 저장소 — 인명 사전의 단일 원천 (스펙 §5)."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def seed(self, rows: list[dict]) -> int:
        """큐레이션 명단 멱등 이관 — full_name UNIQUE 로 기존 행은 건드리지 않는다."""
        now = _utcnow()
        params = [{**r, "now": now} for r in rows]
        with self.engine.begin() as c:
            res = c.execute(text(
                "INSERT IGNORE INTO players (full_name,first_name,surname,ko_name,"
                "club,category,status,transfer_status,origin,added_at,confirmed_at) "
                "VALUES (:full_name,:first_name,:surname,:ko_name,:club,:category,"
                "'confirmed',:transfer_status,'curated',:now,:now)"), params)
        return res.rowcount

    def gate_name_map(self) -> dict[str, str]:
        """게이트 검출 사전 {ko_name: surname} — ko_candidate 는 공급하지 않는다."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                f"SELECT ko_name, surname FROM players WHERE {_DICT_WHERE}")).all()
        return {ko: sn for ko, sn in rows}

    def serving_names(self) -> list[str]:
        """서빙 사건 사전용 ko_name 목록 (스펙 §8) — 정렬은 서빙 로더 책임."""
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(text(
                f"SELECT ko_name FROM players WHERE {_DICT_WHERE}")).all()]
