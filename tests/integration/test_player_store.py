import yaml
from pathlib import Path
from sqlalchemy import text
from bullet_in.roster_seed import ROSTER
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


def test_gate_name_map_equals_yaml_name_map(engine):
    # 로더 동등성 (스펙 §9): 마이그레이션 결과 dict = 기존 YAML dict
    store = PlayerStore(engine)
    store.seed(ROSTER)
    expected = yaml.safe_load(Path("config/name_map.yaml").read_text())["names"]
    assert store.gate_name_map() == expected


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
