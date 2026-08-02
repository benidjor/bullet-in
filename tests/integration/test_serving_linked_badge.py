"""SERVING_SELECT_SQL 의 링크 선수 라벨 판별 (linked_player) — 아스날 소속 제외 조건.

라벨 취지 (2026-08-02 사용자 확정): 아스날 소속이 아닌 링크 선수의, 아스날과
무관해 보이는 기사를 설명하는 배지다. 아스날 소속 (squad · manager · director)
확정 인물이 함께 연결된 기사는 그 자체로 아스날 글이라 배지 대상이 아니다.
"""
from sqlalchemy import text
from bullet_in.run import SERVING_SELECT_SQL
from bullet_in.storage.players import PlayerStore

_H_TARGET = "a" * 64
_H_MIXED = "b" * 64
_H_SQUAD = "c" * 64

_PLAYERS = [
    {"full_name": "Target Guy", "first_name": "Target", "surname": "Guy",
     "ko_name": "타깃", "club": "PSG", "category": "external",
     "transfer_status": "in_link"},
    {"full_name": "Squad Man", "first_name": "Squad", "surname": "Man",
     "ko_name": "스쿼드맨", "club": "Arsenal", "category": "squad",
     "transfer_status": "none"},
    {"full_name": "Boss Man", "first_name": "Boss", "surname": "Bossman",
     "ko_name": "보스맨", "club": "Arsenal", "category": "manager",
     "transfer_status": "none"},
]


def _pid(engine, full_name):
    with engine.connect() as c:
        return c.execute(text("SELECT id FROM players WHERE full_name=:f"),
                         {"f": full_name}).scalar_one()


def _setup(engine, links):
    """선수 시드 + 기사 · 연결 삽입. links = {hash: [full_name, ...]}"""
    PlayerStore(engine).seed(_PLAYERS)
    with engine.begin() as c:
        for i, (h, names) in enumerate(links.items()):
            c.execute(text("INSERT INTO articles (content_hash, url, source_id) "
                           "VALUES (:h, :u, 'fmkorea')"),
                      {"h": h, "u": f"https://ex.test/{i}"})
            for n in names:
                c.execute(text("INSERT INTO article_players "
                               "(content_hash, player_id, extracted_at) "
                               "VALUES (:h, :p, NOW())"),
                          {"h": h, "p": _pid(engine, n)})


def _linked_flags(engine):
    with engine.connect() as c:
        return {r["content_hash"]: bool(r["linked_player"])
                for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()}


def test_badge_on_when_only_external_in_link_connected(engine):
    _setup(engine, {_H_TARGET: ["Target Guy"]})
    assert _linked_flags(engine)[_H_TARGET] is True


def test_badge_off_when_squad_member_also_connected(engine):
    # 링크 선수 + 스쿼드 선수가 같이 연결된 기사 = 아스날 글 — 배지 제외
    _setup(engine, {_H_MIXED: ["Target Guy", "Squad Man"]})
    assert _linked_flags(engine)[_H_MIXED] is False


def test_badge_off_when_manager_connected(engine):
    # 감독 (manager) 연결도 아스날 소속 — 배지 제외 (실측: 아르테타 제목 노이즈)
    _setup(engine, {_H_MIXED: ["Target Guy", "Boss Man"]})
    assert _linked_flags(engine)[_H_MIXED] is False


def test_badge_off_when_only_squad_connected(engine):
    # 링크 선수 연결이 없으면 기존대로 배지 없음 (회귀 가드)
    _setup(engine, {_H_SQUAD: ["Squad Man"]})
    assert _linked_flags(engine)[_H_SQUAD] is False
