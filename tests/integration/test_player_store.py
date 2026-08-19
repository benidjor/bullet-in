import pytest
from sqlalchemy import text
from bullet_in.roster_seed import ROSTER
from bullet_in.roster import normalize_pairs, record_article_players
from bullet_in.storage.players import PlayerStore

# 역할 규칙 입력 — 이름이 없는 기사라 규칙은 mention 을 낸다
_ARTICLE = {"title_ko": "아스날 이적시장 소식", "title_original": "Arsenal news",
            "body_ko": "본문"}


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
    store.link_article(h, pid, "interest", "subject")
    store.link_article(h, pid, "agreed", "subject")     # 재추출 — 단계만 갱신
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
    created1 = record_article_players(store, h1, pairs, _ARTICLE)
    created2 = record_article_players(store, h2, pairs, _ARTICLE)  # 같은 선수 재등장
    assert len(created1) == 1 and created2 == []          # 중복 후보 없음
    pid = created1[0]["player_id"]
    assert sorted(store.articles_for(pid)) == sorted([h1, h2])


def test_record_article_players_links_existing_by_surname(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Gyokeres", "ko": "요케레스",
                              "stage": "agreed"}])       # 성만 온 출력
    created = record_article_players(store, "d" * 64, pairs, _ARTICLE)
    assert created == []                                  # 기존 요케레스에 링크, 후보 미생성


def test_record_article_players_two_word_unmatched_gets_no_surname_fallback(engine):
    # ROSTER 에 성 White (Ben White) 가 있어도, 풀네임 두 단어 출력이 by_full 미스면
    # 성 폴백 없이 신규 후보로 등재돼야 한다 (동성 타인의 조용한 오연결 방지).
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Harvey White", "ko": "하비 화이트",
                              "stage": "rumour"}])
    created = record_article_players(store, "e" * 64, pairs, _ARTICLE)
    assert len(created) == 1                              # 신규 후보 생성
    ben_white_id = store.gate_player_id("화이트")
    assert created[0]["player_id"] != ben_white_id         # 기존 화이트와 다른 id
    assert store.articles_for(ben_white_id) == []          # 기존 화이트엔 링크 안 됨


def test_confirm_promotes_candidate(engine):
    store = PlayerStore(engine)
    pid = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                 surname="Williams", ko_candidate="니코 윌리엄스",
                                 first_seen=None)
    store.confirm(pid, ko_name="니코 윌리엄스", category="external",
                  transfer_status="in_link", club="Athletic Club")
    p = store.get_player("Nico Williams")
    assert p["status"] == "confirmed" and p["confirmed_at"] is not None
    assert store.gate_name_map()["니코 윌리엄스"] == "Williams"   # 확정 즉시 사전 편입


def test_ko_name_holder_blocks_duplicate_promotion(engine):
    # 같은 ko_name 으로 두 번째 선수를 확정하면 사전 dict 가 조용히 덮인다 (PR 1 리뷰 이월) —
    # confirm 호출 전 ko_name_holder 로 선점 여부를 확인해 차단하는 것이 확정 CLI 의 책임.
    store = PlayerStore(engine)
    pid1 = store.insert_candidate(full_name="Nico Williams", first_name="Nico",
                                  surname="Williams", ko_candidate="니코 윌리엄스",
                                  first_seen=None)
    store.confirm(pid1, ko_name="니코 윌리엄스", category="external",
                  transfer_status="in_link", club="Athletic Club")
    assert store.ko_name_holder("니코 윌리엄스") == pid1

    pid2 = store.insert_candidate(full_name="Inaki Williams", first_name="Inaki",
                                  surname="Williams", ko_candidate="이냐키 윌리엄스",
                                  first_seen=None)
    holder = store.ko_name_holder("니코 윌리엄스")
    assert holder is not None and holder != pid2   # 확정 CLI 가 여기서 차단해야 함

    assert store.ko_name_holder("존재하지않음") is None


def test_confirmed_ko_names_excludes_archived_and_candidate(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET status='archived' WHERE full_name='Leandro Trossard'"))
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_candidate,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "('New Guy','Guy','뉴가이','external','candidate','in_link','extracted',NOW())"))
    names = store.confirmed_ko_names()
    assert "트로사르" not in names        # archived 제외 (필터 인정 집합은 confirmed 전체)
    assert "뉴가이" not in names          # 후보 미공급
    assert "사카" in names


def test_active_link_players_only_links_ordered_by_id(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET transfer_status='in_link' WHERE full_name='Bukayo Saka'"))
        c.execute(text("UPDATE players SET transfer_status='out_link' WHERE full_name='William Saliba'"))
    rows = store.active_link_players()
    names = [n for _, n in rows]
    # ROSTER 에 이미 in_link/out_link 확정 선수가 있어 (2026-07-31 후보 확정 운영) 전체가
    # 사카·살리바 둘만은 아니다 — 이번에 지정한 둘이 seed 순서상 id 최소라 맨 앞에 온다.
    assert names[:2] == ["사카", "살리바"]
    assert [pid for pid, _ in rows] == sorted(pid for pid, _ in rows)


def test_active_link_players_excludes_archived_link(engine):
    store = PlayerStore(engine)
    store.seed(ROSTER)
    with engine.begin() as c:
        c.execute(text("UPDATE players SET transfer_status='in_link', status='archived' "
                       "WHERE full_name='Bukayo Saka'"))
    names = [n for _, n in store.active_link_players()]
    assert "사카" not in names   # archived 는 활성 이적축에서 제외


def _add_player(engine, *, full_name, surname, ko_name, category, status,
                transfer_status):
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (full_name,surname,ko_name,category,status,"
            "transfer_status,origin,added_at) VALUES "
            "(:fn,:sn,:ko,:cat,:st,:ts,'curated',NOW())"),
            {"fn": full_name, "sn": surname, "ko": ko_name, "cat": category,
             "st": status, "ts": transfer_status})
        return c.execute(text("SELECT id FROM players WHERE full_name=:fn"),
                         {"fn": full_name}).scalar_one()


def test_page_players_applies_target_condition(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Target One", surname="One",
                       ko_name="타깃", category="external", status="confirmed",
                       transfer_status="in_link")
    staff = _add_player(engine, full_name="Boss Man", surname="Man",
                        ko_name="보스", category="manager", status="confirmed",
                        transfer_status="in_link")
    no_axis = _add_player(engine, full_name="Squad Guy", surname="Guy",
                          ko_name="스쿼드", category="squad", status="confirmed",
                          transfer_status="none")
    cand = _add_player(engine, full_name="Cand Idate", surname="Idate",
                       ko_name="후보", category="external", status="candidate",
                       transfer_status="in_link")
    archived_kept = _add_player(engine, full_name="Gone Elsewhere", surname="Elsewhere",
                                ko_name="타클럽", category="external",
                                status="archived", transfer_status="other_club")
    orphan = _add_player(engine, full_name="No Articles", surname="Articles",
                         ko_name="무기사", category="external", status="confirmed",
                         transfer_status="in_link")
    for pid in (keep, staff, no_axis, cand, archived_kept):
        store.link_article("a" * 64, pid, "interest", "subject")
    ids = {p["id"] for p in store.page_players()}
    assert keep in ids
    assert archived_kept in ids       # 사유가 값에 남은 보관 선수는 노출 (스펙 §3.1)
    assert staff not in ids           # 스태프 제외
    assert no_axis not in ids         # 이적 축 없음 제외
    assert cand not in ids            # 후보 제외 (승인된 이탈)
    assert orphan not in ids          # 귀속 기사 0건 제외


def test_page_player_links_shares_the_same_predicate(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Link Target", surname="Target",
                       ko_name="대상", category="external", status="confirmed",
                       transfer_status="in_link")
    staff = _add_player(engine, full_name="Link Boss", surname="Boss",
                        ko_name="감독", category="manager", status="confirmed",
                        transfer_status="in_link")
    store.link_article("b" * 64, keep, "agreed", "subject")
    store.link_article("b" * 64, staff, "agreed", "subject")
    links = store.page_player_links()
    assert {l["player_id"] for l in links} == {keep}
    assert links[0]["stage"] == "agreed"
    assert links[0]["content_hash"] == "b" * 64


def test_link_article_stores_role_and_page_links_return_it(engine):
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="Role Target", surname="RoleTarget",
                       ko_name="역할대상", category="external", status="confirmed",
                       transfer_status="in_link")
    h = "d" * 64
    store.link_article(h, keep, "other", "mention")
    store.link_article(h, keep, "interest", "subject")   # 재추출 — 역할도 갱신된다
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT stage, role FROM article_players WHERE content_hash=:h"),
            {"h": h}).all() == [("interest", "subject")]
    assert [l["role"] for l in store.page_player_links()
            if l["content_hash"] == h] == ["subject"]


def test_link_article_rejects_a_missing_role(engine):
    # 역할 미기입은 저장 단계에서 막는다 — 서빙이 그 값을 임의로 읽으면 화면이
    # 조용히 틀어진다 (안건 f-③ · role NOT NULL).
    store = PlayerStore(engine)
    keep = _add_player(engine, full_name="No Role", surname="NoRole",
                       ko_name="역할없음", category="external", status="confirmed",
                       transfer_status="in_link")
    with pytest.raises(Exception):
        store.link_article("e" * 64, keep, "interest", None)


def test_linked_hashes_ignores_the_target_condition(engine):
    store = PlayerStore(engine)
    staff = _add_player(engine, full_name="Only Staff", surname="Staff",
                        ko_name="스태프", category="manager", status="confirmed",
                        transfer_status="none")
    store.link_article("c" * 64, staff, "rumour", "subject")
    # 추출은 됐으나 페이지 대상이 아닌 선수만 걸린 기사도 "추출 누락" 이 아니다
    assert "c" * 64 in store.linked_hashes()


def test_record_article_players_stores_computed_role(engine):
    # 모델이 역할을 안 내도 규칙이 값을 만든다 — 제목에 이름이 있으면 subject
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Bruno Guimaraes", "ko": "기마랑이스",
                              "stage": "agreed"}])
    h = "f" * 64
    record_article_players(store, h, pairs, {
        "title_ko": "아스날, 기마랑이스 영입 합의",
        "title_original": "Arsenal agree deal", "body_ko": "본문"})
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT role FROM article_players WHERE content_hash=:h"),
            {"h": h}).scalar_one() == "subject"


def test_record_article_players_uses_roster_form_for_role(engine):
    # 모델이 낸 표기가 흔들려도 명단 표기가 제목과 직접 일치하면 subject 다
    store = PlayerStore(engine)
    store.seed(ROSTER)
    pairs = normalize_pairs([{"full_name": "Bruno Guimaraes", "ko": "기마랑스",
                              "stage": "agreed"}])
    h = "0" * 64
    record_article_players(store, h, pairs, {
        "title_ko": "아스날, 기마랑이스 영입 합의",
        "title_original": "Arsenal agree deal", "body_ko": "본문"})
    with engine.connect() as c:
        assert c.execute(text(
            "SELECT role FROM article_players WHERE content_hash=:h"),
            {"h": h}).scalar_one() == "subject"


def test_record_article_players_reports_duplicate_suspects(engine):
    # 성이 같고 이름이 비슷한 기존 선수를 알리기만 한다 — 병합은 사람 몫 (스펙 §8.5)
    store = PlayerStore(engine)
    store.insert_candidate(full_name="Ilan Meslier", first_name="Ilan",
                           surname="Meslier", ko_candidate="일란 메슬리에",
                           first_seen=None)
    pairs = normalize_pairs([{"full_name": "Illan Meslier", "ko": "멜리에",
                              "stage": "agreed"}])
    created = record_article_players(store, "1" * 64, pairs, _ARTICLE)
    assert len(created) == 1                       # 자동 병합하지 않는다
    assert [s["full_name"] for s in created[0]["dup_suspects"]] == ["Ilan Meslier"]
