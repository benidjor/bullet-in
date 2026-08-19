"""SERVING_SELECT_SQL 의 링크 선수 배지 입력 (linked_players).

배지 취지 (2026-08-02 사용자 확정): 아스날 소속이 아닌 링크 선수의,
이적 기사가 아니면서 아스날과 무관해 보이는 기사 (예: 링크 선수가 걸린
감독 사임 소식) 가 왜 피드에 있는지 이름으로 설명하는 배지다.

- 소속 제외 (#195): 아스날 소속 (squad · manager · director) 확정 인물이
  함께 연결된 기사는 그 자체로 아스날 글이라 배지 대상이 아니다.
- 비이적 한정 (#196): 이적 기사는 링크되어 있다는 사실 자체가 맥락이라
  배지가 불필요하다 — 비이적 (other) 만 배지.
- 이름 공급 (본 변경): 조건을 통과한 기사에 연결된 영입 링크 선수의 ko_name 을
  id 순으로 넘겨, 렌더가 "누구 관련" 인지 적는다.
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
    {"full_name": "Second Guy", "first_name": "Second", "surname": "Guy2",
     "ko_name": "세컨드", "club": "Lyon", "category": "external",
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
                # role 은 NOT NULL 이다 — 배지 판정과 무관하므로 주역으로 채운다
                c.execute(text("INSERT INTO article_players "
                               "(content_hash, player_id, role, extracted_at) "
                               "VALUES (:h, :p, 'subject', NOW())"),
                          {"h": h, "p": _pid(engine, n)})


def _linked_names(engine):
    with engine.connect() as c:
        return {r["content_hash"]: r["linked_players"]
                for r in c.execute(text(SERVING_SELECT_SQL)).mappings().all()}


def test_names_supplied_for_nontransfer_article(engine):
    # 비이적 (other) + 외부 링크 선수 연결 = 배지 대상 · 이름을 넘긴다
    _setup(engine, {_H_A: ("other", ["Target Guy"])})
    assert _linked_names(engine)[_H_A] == "타깃"


def test_multiple_names_joined_in_id_order(engine):
    # 여럿이면 id 순으로 이어 붙인다 (렌더가 첫 이름 + 나머지 인원으로 접는다)
    _setup(engine, {_H_A: ("other", ["Second Guy", "Target Guy"])})
    assert _linked_names(engine)[_H_A] == "타깃|세컨드"


def test_no_names_on_transfer_article(engine):
    # 이적 기사 (negotiating) 는 링크 자체가 맥락 — 배지 제외 (#196)
    _setup(engine, {_H_A: ("negotiating", ["Target Guy"])})
    assert _linked_names(engine)[_H_A] is None


def test_no_names_before_stage_classified(engine):
    # 분류 전 (stage NULL) 은 판정 보류 — 다음 회차 분류 후 붙는다
    _setup(engine, {_H_A: (None, ["Target Guy"])})
    assert _linked_names(engine)[_H_A] is None


def test_no_names_when_squad_member_also_connected(engine):
    # 스쿼드 선수 동반 연결 = 아스날 글 — 비이적이어도 배지 제외 (#195)
    _setup(engine, {_H_A: ("other", ["Target Guy", "Squad Man"])})
    assert _linked_names(engine)[_H_A] is None


def test_no_names_when_manager_connected(engine):
    # 감독 (manager) 연결도 아스날 소속 — 배지 제외 (#195)
    _setup(engine, {_H_A: ("other", ["Target Guy", "Boss Man"])})
    assert _linked_names(engine)[_H_A] is None


def test_no_names_when_only_squad_connected(engine):
    # 링크 선수 연결이 없으면 배지 없음 (회귀 가드)
    _setup(engine, {_H_B: ("other", ["Squad Man"])})
    assert _linked_names(engine)[_H_B] is None
