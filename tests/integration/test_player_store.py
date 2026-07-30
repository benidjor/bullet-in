from sqlalchemy import text
from bullet_in.roster_seed import ROSTER
from bullet_in.roster import normalize_pairs, record_article_players
from bullet_in.storage.players import PlayerStore


def test_ensure_schema_creates_player_tables(engine):
    # engine 픽스처가 schema.sql 을 적용하므로 테이블 존재 = DDL 반영 증거
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM players")).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM article_players")).scalar_one() == 0


def test_seed_is_idempotent(engine):
    store = PlayerStore(engine)
    assert store.seed(ROSTER) == len(ROSTER)
    assert store.seed(ROSTER) == 0          # 재실행 시 신규 0 (INSERT IGNORE)


def test_gate_name_map_equals_seed_roster(engine):
    # YAML 폐지 후의 회귀 가드 — 술어 (후보 배제) 가 이관분을 깎지 않는지 고정
    store = PlayerStore(engine)
    store.seed(ROSTER)
    assert store.gate_name_map() == {r["ko_name"]: r["surname"] for r in ROSTER}


def test_gate_name_map_excludes_candidate_and_blank_ko(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_candidate,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "('New Guy','Guy','뉴가이','external','candidate','in_link','extracted',NOW())"))
        c.execute(text("UPDATE players SET status='archived' WHERE full_name='Leandro Trossard'"))
    m = store.gate_name_map()
    assert "뉴가이" not in m                  # 후보 미공급 (스펙 §3.2)
    assert m.get("트로사르") == "Trossard"    # archived 잔류 (스펙 §6 · §8)


def test_serving_names_matches_gate_keys(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    assert set(store.serving_names()) == set(store.gate_name_map())


def test_insert_candidate_and_match(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pid = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                 surname="Williams", ko_candidate="니코 윌리엄스",
                                 first_seen="h" * 64)
    by_full, by_surname = store.match_maps()
    assert by_full["nico williams"] == pid
    assert by_surname["williams"] == pid


def test_match_maps_drop_ambiguous_surname(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    store.insert_candidate(full_name="Brennan Johnson", first_name="Brennan",
                           surname="Johnson", ko_candidate=None, first_seen=None)
    store.insert_candidate(full_name="Ben Johnson", first_name="Ben",
                           surname="Johnson", ko_candidate=None, first_seen=None)
    _, by_surname = store.match_maps()
    assert "johnson" not in by_surname       # 동성 2명 — 성 단독 매칭은 모호해 제외


def test_link_article_upsert_is_idempotent(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pid = store.gate_player_id("기마랑이스")
    h = "a" * 64
    store.link_article(h, pid, "interest")
    store.link_article(h, pid, "agreed")     # 재추출 — 단계만 갱신
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT stage FROM article_players WHERE content_hash=:h"), {"h": h}).all()
    assert rows == [("agreed",)]
    assert store.articles_for(pid) == [h]


def test_record_article_players_candidate_idempotent(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Nico Williams", "ko": "니코 윌리엄스",
                              "stage": "rumour"}])
    h1, h2 = "b" * 64, "c" * 64
    created1 = record_article_players(store, h1, pairs)
    created2 = record_article_players(store, h2, pairs)   # 같은 선수 재등장
    assert len(created1) == 1 and created2 == []          # 중복 후보 없음
    pid = created1[0]["player_id"]
    assert sorted(store.articles_for(pid)) == sorted([h1, h2])


def test_record_article_players_links_existing_by_surname(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Gyokeres", "ko": "요케레스",
                              "stage": "agreed"}])       # 성만 온 출력
    created = record_article_players(store, "d" * 64, pairs)
    assert created == []                                  # 기존 요케레스에 링크, 후보 미생성
