"""SERVING_SELECT_SQL 의 링크 선수 라벨 판별 (linked_player).

라벨 취지 (2026-08-02 사용자 확정): 아스날 소속이 아닌 링크 선수의,
이적 기사가 아니면서 아스날과 무관해 보이는 기사 (예: 링크 선수의 부상 소식)
를 설명하는 배지다. 두 조건이 판별을 이룬다.

- 소속 제외 (#195): 아스날 소속 (squad · manager · director) 확정 인물이
  함께 연결된 기사는 그 자체로 아스날 글이라 배지 대상이 아니다.
- 비이적 한정 (조건 ② · #194 소급 재분류 수렴 후): 이적 기사 (루머~오피셜)
  는 링크 자체가 문맥이라 배지가 불필요하다 — 비이적 (other) 만 배지.
"""
from sqlalchemy import text
from bullet_in.run import SERVING_SELECT_SQL
from bullet_in.storage.players import PlayerStore

_H_A = "a" * 64
_H_B = "b" * 64

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
    """선수 시드 + 기사 · 연결 삽입. links = {hash: (stage, [full_name, ...])}"""
    PlayerStore(engine).seed(_PLAYERS)
    with engine.begin() as c:
        for i, (h, (stage, names)) in enumerate(links.items()):
            c.execute(text("INSERT INTO articles (content_hash, url, source_id, "
                           "transfer_stage) VALUES (:h, :u, 'fmkorea', :s)"),
                      {"h": h, "u": f"https://ex.test/{i}", "s": stage})
            for n in names:
                c.execute(text("INSERT INTO article_players "
                               "(content_hash, player_id, extracted_at) "
                               "VALUES (:h, :p, NOW())"),
                          {"h": h, "p": _pid(engine, n)})


def _linked_flags(engine):
    with engine.connect() as c:
        return {r["content_hash"]: bool(r["linked_player"])
                for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()}


def test_badge_on_nontransfer_article_with_external_in_link(engine):
    # 비이적 (other) + 외부 링크 선수만 연결 = 배지의 존재 이유 (부상 소식류)
    _setup(engine, {_H_A: ("other", ["Target Guy"])})
    assert _linked_flags(engine)[_H_A] is True


def test_badge_off_on_transfer_article(engine):
    # 이적 기사 (negotiating) 는 링크 자체가 문맥 — 배지 제외 (조건 ②)
    _setup(engine, {_H_A: ("negotiating", ["Target Guy"])})
    assert _linked_flags(engine)[_H_A] is False


def test_badge_off_before_stage_classified(engine):
    # 분류 전 (stage NULL) 은 판정 보류 — 다음 회차 분류 후 붙는다
    _setup(engine, {_H_A: (None, ["Target Guy"])})
    assert _linked_flags(engine)[_H_A] is False


def test_badge_off_when_squad_member_also_connected(engine):
    # 스쿼드 선수 동반 연결 = 아스날 글 — 비이적이어도 배지 제외 (#195)
    _setup(engine, {_H_A: ("other", ["Target Guy", "Squad Man"])})
    assert _linked_flags(engine)[_H_A] is False


def test_badge_off_when_manager_connected(engine):
    # 감독 (manager) 연결도 아스날 소속 — 배지 제외 (#195)
    _setup(engine, {_H_A: ("other", ["Target Guy", "Boss Man"])})
    assert _linked_flags(engine)[_H_A] is False


def test_badge_off_when_only_squad_connected(engine):
    # 링크 선수 연결이 없으면 배지 없음 (회귀 가드)
    _setup(engine, {_H_B: ("other", ["Squad Man"])})
    assert _linked_flags(engine)[_H_B] is False
