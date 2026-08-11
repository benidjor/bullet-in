"""선수 명단 저장소 — 인명 사전의 단일 원천 (스펙 §5)."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

# 게이트 · 서빙 사전 술어 — 후보 (자동 등재) 배제 + archived 잔류 (스펙 §3.2 · §8)
_DICT_WHERE = "status IN ('confirmed','archived') AND ko_name IS NOT NULL"

# 선수 페이지 대상 술어 (스펙 §3.1 + 후보 제외 · 2026-08-03 사용자 확정)
# — 스태프 · 이적 얘기 없는 스쿼드 · 사유 없는 보관 · 미확정 후보가 여기서 빠진다.
_PAGE_WHERE = ("category IN ('squad','external') AND transfer_status <> 'none' "
               "AND status <> 'candidate'")

# 귀속 역할 어휘 (역할 필드 스펙 2026-08-12 §3.1) — article_players.role 의 단일 출처.
# "이 기사의 주인공인가" 를 묻는 축이고, stage 는 "어느 단계인가" 만 맡는다.
# 두 질문을 stage 하나로 답하던 동안 화면 귀속 807건 중 331건이 남의 기사였다.
SUBJECT = "subject"
MENTION = "mention"
ROLES = frozenset({SUBJECT, MENTION})


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

    def match_maps(self) -> tuple[dict[str, int], dict[str, int]]:
        """(접힌 full_name → id, 접힌 surname → id). 동성 복수 인원은 성 매핑에서 뺀다
        — 성 단독 매칭이 다른 선수에게 기사를 붙이는 것을 막는다."""
        from bullet_in.enrich import _fold_latin
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT id, full_name, surname FROM players")).all()
        by_full = {_fold_latin(fn): pid for pid, fn, _ in rows}
        grouped: dict[str, list[int]] = {}
        for pid, _, sn in rows:
            grouped.setdefault(_fold_latin(sn), []).append(pid)
        by_surname = {sn: pids[0] for sn, pids in grouped.items() if len(pids) == 1}
        return by_full, by_surname

    def insert_candidate(self, *, full_name: str, first_name: str | None,
                         surname: str, ko_candidate: str | None,
                         first_seen: str | None) -> int:
        """자동 발굴 후보 등재 (스펙 §4.1) — 호출 전 match_maps 미매칭이 전제.
        transfer_status 기본값은 in_link — 방향은 사람 확정 시 교정한다."""
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO players (full_name,first_name,surname,ko_candidate,"
                "category,status,transfer_status,origin,first_seen,added_at) "
                "VALUES (:fn,:fi,:sn,:ko,'external','candidate','in_link',"
                "'extracted',:seen,:now)"),
                {"fn": full_name, "fi": first_name, "sn": surname,
                 "ko": ko_candidate, "seen": first_seen, "now": _utcnow()})
            return c.execute(text("SELECT id FROM players WHERE full_name=:fn"),
                             {"fn": full_name}).scalar_one()

    def link_article(self, content_hash: str, player_id: int,
                     stage: str | None, role: str | None = None) -> None:
        """추출 쌍 저장 — 재추출 시 단계 · 역할 · 시각만 갱신하는 멱등 upsert.
        역할이 미기입인 쌍은 그대로 NULL 로 남는다."""
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO article_players "
                "(content_hash,player_id,stage,role,extracted_at) "
                "VALUES (:h,:p,:s,:r,:now) ON DUPLICATE KEY UPDATE "
                "stage=VALUES(stage), role=VALUES(role), "
                "extracted_at=VALUES(extracted_at)"),
                {"h": content_hash, "p": player_id, "s": stage, "r": role,
                 "now": _utcnow()})

    def articles_for(self, player_id: int) -> list[str]:
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(text(
                "SELECT content_hash FROM article_players WHERE player_id=:p"),
                {"p": player_id}).all()]

    def ko_name_holder(self, ko_name: str) -> int | None:
        """ko_name 을 이미 보유한 선수 id (candidate 제외) — 중복 승격 충돌 검사."""
        with self.engine.connect() as c:
            return c.execute(text(
                "SELECT id FROM players WHERE ko_name=:ko AND status != 'candidate'"),
                {"ko": ko_name}).scalar()

    def gate_player_id(self, ko_name: str) -> int:
        with self.engine.connect() as c:
            return c.execute(text("SELECT id FROM players WHERE ko_name=:ko"),
                             {"ko": ko_name}).scalar_one()

    def get_player(self, full_name: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM players WHERE full_name=:fn"),
                            {"fn": full_name}).mappings().first()
        return dict(row) if row else None

    def confirmed_ko_names(self) -> set[str]:
        """무관 글 필터 인정 집합 (워치리스트 스펙 §3.2) — confirmed 전체 (스쿼드 포함)."""
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(text(
                "SELECT ko_name FROM players WHERE status='confirmed' "
                "AND ko_name IS NOT NULL")).all()}

    def active_link_players(self) -> list[tuple[int, str]]:
        """워치리스트 로테이션 명단 (스펙 §3.1) — 활성 이적축 · id 순."""
        with self.engine.connect() as c:
            return [(r[0], r[1]) for r in c.execute(text(
                "SELECT id, ko_name FROM players WHERE status='confirmed' "
                "AND transfer_status IN ('in_link','out_link') "
                "AND ko_name IS NOT NULL ORDER BY id")).all()]

    def cycle_pairs(self, hashes: list[str]) -> list[dict]:
        """이번 회차에 만진 기사들의 (확정 선수, 단계) 귀속 — 축 낡음 관측 재료
        (스펙 2026-08-10 §3). 후보 · 보관 선수는 명단 운영 대상이 아니라 뺀다."""
        if not hashes:
            return []
        q = text(
            "SELECT ap.player_id, p.ko_name, p.transfer_status, ap.stage "
            "FROM article_players ap JOIN players p ON p.id = ap.player_id "
            "WHERE ap.content_hash IN :hashes AND p.status = 'confirmed'"
        ).bindparams(bindparam("hashes", expanding=True))   # text() 의 IN 은 expanding 필수
        with self.engine.connect() as c:
            return [dict(r) for r in
                    c.execute(q, {"hashes": hashes}).mappings().all()]

    def recent_stage_counts(self, player_ids: list[int],
                            days: int = 7) -> dict[tuple[int, str], int]:
        """선수별 최근 N일 단계 귀속 계수 (published_at 기준) — 단발 거름용
        (스펙 2026-08-10 §3)."""
        if not player_ids:
            return {}
        q = text(
            "SELECT ap.player_id, ap.stage, COUNT(*) "
            "FROM article_players ap "
            "JOIN articles a ON a.content_hash = ap.content_hash "
            "WHERE ap.player_id IN :pids "
            "AND a.published_at >= UTC_TIMESTAMP() - INTERVAL :days DAY "
            "GROUP BY ap.player_id, ap.stage"
        ).bindparams(bindparam("pids", expanding=True))   # text() 의 IN 은 expanding 필수
        with self.engine.connect() as c:
            return {(r[0], r[1]): r[2] for r in
                    c.execute(q, {"pids": player_ids, "days": days}).all()}

    def page_players(self) -> list[dict]:
        """선수 페이지 대상 (스펙 §3.1) — 귀속 기사가 없는 선수는 뺀다.
        빈 페이지를 만들지 않기 위한 조건이며 page_player_links 와 술어를 공유한다."""
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(text(
                "SELECT id, full_name, surname, ko_name, ko_full_name, "
                "transfer_status "
                f"FROM players WHERE {_PAGE_WHERE} AND EXISTS ("
                "SELECT 1 FROM article_players ap WHERE ap.player_id = players.id) "
                "ORDER BY id")).mappings().all()]

    def page_player_links(self) -> list[dict]:
        """대상 선수의 기사 귀속 전량 — (선수, 기사, 그 기사에서 그 선수의 단계 · 역할)."""
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(text(
                "SELECT ap.player_id, ap.content_hash, ap.stage, ap.role "
                "FROM article_players ap JOIN players p ON p.id = ap.player_id "
                f"WHERE {_PAGE_WHERE}")).mappings().all()]

    def linked_hashes(self) -> set[str]:
        """추출이 한 명이라도 붙인 기사 (ops 추출 누락 표의 여집합 · 스펙 §9).
        대상 술어를 걸지 않는다 — 스태프만 걸린 기사도 추출은 성공한 것이다."""
        with self.engine.connect() as c:
            return {r[0] for r in c.execute(text(
                "SELECT DISTINCT content_hash FROM article_players")).all()}

    def confirm(self, player_id: int, *, ko_name: str,
                category: str | None = None, transfer_status: str | None = None,
                club: str | None = None) -> None:
        """후보 승격 (스펙 §4.3 1단계) — ko_name 기입 · 분류는 지정한 것만 갱신."""
        with self.engine.begin() as c:
            c.execute(text(
                "UPDATE players SET status='confirmed', ko_name=:ko, "
                "confirmed_at=:now, category=COALESCE(:cat, category), "
                "transfer_status=COALESCE(:ts, transfer_status), "
                "club=COALESCE(:club, club) WHERE id=:id"),
                {"ko": ko_name, "now": _utcnow(), "cat": category,
                 "ts": transfer_status, "club": club, "id": player_id})
