from datetime import datetime, timezone
from bullet_in.storage.mariadb import MartStore
from bullet_in.models import Article

def _art(h="h1", url="https://x.test/a", title="T"):
    return Article(content_hash=h, url=url, source_id="guardian",
                   title_original=title, published_at=datetime(2026,5,27,tzinfo=timezone.utc))

def test_upsert_dedup_keeps_single_row(engine):
    store = MartStore(engine)
    store.upsert([_art()]); store.upsert([_art()])
    assert store.count() == 1

def test_upsert_empty_list_is_noop(engine):
    # 신규 없는 회차(6시간마다 흔함)는 빈 배치 → 에러 없이 0 반환해야 한다
    assert MartStore(engine).upsert([]) == 0

def test_watermark_returns_seen_map(engine):
    store = MartStore(engine)
    store.upsert([_art()])
    seen = store.seen_map()
    assert seen["https://x.test/a"][0] == "h1"

def test_set_translation_writes_all_four_fields(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="h9", url="https://x.test/9", title="T")])
    store.set_translation("h9", "제목", "한줄", "①\n②\n③", "전체 본문")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT title_ko,summary_ko,summary3_ko,body_ko "
            "FROM articles WHERE content_hash='h9'")).mappings().one())
    assert r["title_ko"] == "제목" and r["summary_ko"] == "한줄"
    assert r["summary3_ko"] == "①\n②\n③" and r["body_ko"] == "전체 본문"

def test_upsert_persists_image_outlet_team(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hi", url="https://x.test/i", source_id="bbc_sport",
                          title_original="T", outlet="BBC", journalist="Sami Mokbel",
                          image_url="https://img.test/a.jpg", body_source="src", team="arsenal",
                          published_at=datetime(2026,6,29,tzinfo=timezone.utc))])
    from sqlalchemy import text
    with engine.connect() as c:
        r = dict(c.execute(text("SELECT outlet,journalist,image_url,team,body_source "
                                "FROM articles WHERE content_hash='hi'")).mappings().one())
    assert r["outlet"] == "BBC" and r["image_url"] == "https://img.test/a.jpg"
    assert r["team"] == "arsenal" and r["body_source"] == "src"

def test_rows_missing_translation_includes_outlet_and_body_source(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hm", url="https://x.test/m", source_id="fmkorea",
                          title_original="T", outlet="The Athletic", body_source="원문",
                          published_at=datetime(2026,6,29,tzinfo=timezone.utc))])
    row = next(r for r in store.rows_missing_translation() if r["content_hash"] == "hm")
    assert row["outlet"] == "The Athletic" and row["body_source"] == "원문"

def test_changed_url_updates_hash_and_resets_translation(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="g",
                          title_original="Old", published_at=datetime(2026,5,27,tzinfo=timezone.utc))])
    store.set_translation("h1", "옛제목", "옛요약")
    # same url, new hash + title, revision bumped
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="g",
                          title_original="New", revision=2,
                          published_at=datetime(2026,5,27,tzinfo=timezone.utc))])
    assert store.count() == 1
    assert store.seen_map()["https://x.test/a"] == ("h2", 2, "g", 0)
    missing = {r["content_hash"] for r in store.rows_missing_translation()}
    assert "h2" in missing  # translation reset so enrich re-runs


def test_rows_missing_stage_and_set_stage(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([Article(content_hash="hs", url="https://x.test/s",
                          source_id="bbc_sport",
                          title_original="Arsenal close on Gyokeres",
                          summary_ko="요케레스 임박",
                          published_at=datetime(2026, 6, 30, tzinfo=timezone.utc))])
    missing = {r["content_hash"]: r for r in store.rows_missing_stage()}
    assert "hs" in missing
    assert missing["hs"]["title_original"] == "Arsenal close on Gyokeres"
    assert missing["hs"]["summary_ko"] == "요케레스 임박"
    assert missing["hs"]["source_id"] == "bbc_sport"   # 규칙·LLM 분리 판정 입력 (spec §4.1)
    store.set_stage("hs", "negotiating", "in")
    assert "hs" not in {r["content_hash"] for r in store.rows_missing_stage()}
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT transfer_stage, transfer_direction FROM articles "
            "WHERE content_hash='hs'")).one()
    assert tuple(row) == ("negotiating", "in")


def test_upsert_preserves_stage_on_revision_change(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="g",
                          title_original="Old",
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    store.set_stage("h1", "rumour")
    # url 동일, hash · title 변경 (revision++) → 번역은 리셋되지만 단계는 보존
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="g",
                          title_original="New", revision=2,
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    with engine.connect() as c:
        stage = c.execute(text("SELECT transfer_stage FROM articles "
                               "WHERE content_hash='h2'")).scalar_one()
    assert stage == "rumour"


def test_rows_enriched_summaries_returns_only_summarized(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="he", url="https://x.test/e", title="E"),
                  _art(h="hn", url="https://x.test/n", title="N")])
    store.set_translation("he", "제목", "확정했습니다.", "①\n②\n③", "본문")
    pool = {r["content_hash"]: r for r in store.rows_enriched_summaries()}
    assert "he" in pool and "hn" not in pool
    assert pool["he"]["summary_ko"] == "확정했습니다."
    assert pool["he"]["body_ko"] == "본문"
    assert pool["he"]["title_ko"] == "제목"

def test_set_summary_updates_summary_fields_only(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="ht", url="https://x.test/t", title="T")])
    store.set_translation("ht", "제목", "확정했습니다.", "A입니다.\nB다.\nC다.", "본문")
    store.set_summary("ht", "확정했다.", "A다.\nB다.\nC다.")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT title_ko,summary_ko,summary3_ko,body_ko "
            "FROM articles WHERE content_hash='ht'")).mappings().one())
    assert r["summary_ko"] == "확정했다." and r["summary3_ko"] == "A다.\nB다.\nC다."
    assert r["title_ko"] == "제목" and r["body_ko"] == "본문"

def test_set_summary_without_s3_preserves_existing(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="hp", url="https://x.test/p", title="P")])
    store.set_translation("hp", "제목", "확정했습니다.", "기존3줄", "본문")
    store.set_summary("hp", "확정했다.")
    with engine.connect() as c:
        r = dict(c.execute(text(
            "SELECT summary_ko,summary3_ko FROM articles "
            "WHERE content_hash='hp'")).mappings().one())
    assert r["summary_ko"] == "확정했다." and r["summary3_ko"] == "기존3줄"


def test_seen_map_carries_source_and_body_level(engine):
    # 가드 판정 입력 (spec §5) — body_level 3단 사다리 (0 없음 · 1 게시글 · 2 언론사)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([_art(h="h1", url="https://x.test/a"),
                  Article(content_hash="h2", url="https://x.test/b", source_id="fmkorea",
                          title_original="T", body_source="옮긴 본문", body_level=1,
                          published_at=datetime(2026, 5, 27, tzinfo=timezone.utc))])
    seen = store.seen_map()
    assert seen["https://x.test/a"] == ("h1", 1, "guardian", 0)
    assert seen["https://x.test/b"] == ("h2", 1, "fmkorea", 1)


def test_upsert_upgrade_replaces_source_id(engine):
    # 스텁 업그레이드는 전면 채택 — source_id 까지 교체 (spec §3 사용자 확정)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/a", source_id="x_ornstein",
                          title_original="tweet text",
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    store.upsert([Article(content_hash="h2", url="https://x.test/a", source_id="fmkorea",
                          title_original="전문 제목", body_source="전문", body_level=1,
                          revision=2,
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    assert store.count() == 1
    assert store.seen_map()["https://x.test/a"] == ("h2", 2, "fmkorea", 1)


def test_seen_map_reads_legacy_null_level_as_outlet_body(engine):
    # ALTER 직후 · 백필 전 창 — 등급을 낮게 잡으면 게시글 본문이 언론사 원문을 덮는다
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="hl", url="https://x.test/legacy")])
    with engine.begin() as c:
        c.execute(text("UPDATE articles SET body_source='원문 본문', body_level=NULL "
                       "WHERE content_hash='hl'"))
    assert store.seen_map()["https://x.test/legacy"][3] == 2


def test_upsert_upgrade_raises_body_level(engine):
    # 1 → 2 승격은 body_level 도 함께 올라야 한다 (안 오르면 다음 회차가 다시 열린다)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="h1", url="https://x.test/u", source_id="fmkorea",
                          title_original="퍼온 제목", body_source="옮긴 본문", body_level=1,
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    store.upsert([Article(content_hash="h2", url="https://x.test/u", source_id="bbc_sport",
                          title_original="Arsenal sign X", body_source="full body",
                          body_level=2, revision=2,
                          published_at=datetime(2026, 7, 26, tzinfo=timezone.utc))])
    assert store.seen_map()["https://x.test/u"] == ("h2", 2, "bbc_sport", 2)


def test_rows_missing_translation_includes_body_level(engine):
    # 라우팅 입력 (스펙 §4.2) — 등급이 없으면 재작성 · 번역을 가를 수 없다
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([Article(content_hash="hb", url="https://x.test/bl", source_id="fmkorea",
                          title_original="퍼온 제목", body_source="옮긴 본문", body_level=1,
                          published_at=datetime(2026, 7, 27, tzinfo=timezone.utc))])
    row = next(r for r in store.rows_missing_translation() if r["content_hash"] == "hb")
    assert row["body_level"] == 1


def test_set_rewrite_retention_and_high_retention_list(engine):
    # 게이트를 넘긴 채 채택된 행은 ops 로 올려 사람이 확인한다 (스펙 §7)
    from bullet_in.models import Article
    from datetime import datetime, timezone
    store = MartStore(engine)
    store.upsert([
        Article(content_hash="hr1", url="https://x.test/r1", source_id="fmkorea",
                title_original="T1", outlet="The Athletic", body_source="본문",
                body_level=1, published_at=datetime(2026, 7, 27, tzinfo=timezone.utc)),
        Article(content_hash="hr2", url="https://x.test/r2", source_id="fmkorea",
                title_original="T2", outlet="The Times", body_source="본문",
                body_level=1, published_at=datetime(2026, 7, 27, tzinfo=timezone.utc)),
    ])
    store.set_rewrite_retention("hr1", 0.93)
    store.set_rewrite_retention("hr2", 0.41)
    high = store.ops_snapshot()["high_retention"]
    assert [r["content_hash"] for r in high] == ["hr1"]
    assert high[0]["outlet"] == "The Athletic"
    assert round(high[0]["retention"], 2) == 0.93


def test_rows_for_hashes_and_clear_translation(engine):
    store = MartStore(engine)
    store.upsert([_art(h="h1", url="https://x.test/1"), _art(h="h2", url="https://x.test/2")])
    store.set_translation("h1", "제목", "요약", "3줄", "본문")
    rows = store.rows_for_hashes(["h1"])
    assert [r["content_hash"] for r in rows] == ["h1"]
    assert rows[0]["title_ko"] == "제목"
    assert store.clear_translation(["h1"]) == 1
    assert {r["content_hash"] for r in store.rows_missing_translation()} >= {"h1", "h2"}


def _attach_player(engine, content_hash, player_id=1, role="subject"):
    """기사에 선수 귀속을 붙인다 — 고아 판정의 재료."""
    from sqlalchemy import text
    with engine.begin() as c:
        c.execute(text(
            "INSERT IGNORE INTO players (id, full_name, surname, category, status,"
            " transfer_status, origin, added_at, ko_name)"
            " VALUES (:pid, :fn, 'Tester', 'squad', 'active', 'none', 'manual', NOW(), '검사용')"),
            {"pid": player_id, "fn": f"Test Player {player_id}"})
        c.execute(text(
            "INSERT INTO article_players (content_hash, player_id, role, extracted_at)"
            " VALUES (:h, :pid, :role, NOW())"),
            {"h": content_hash, "pid": player_id, "role": role})


def _orphan_count(engine):
    from sqlalchemy import text
    with engine.connect() as c:
        return c.execute(text(
            "SELECT COUNT(*) FROM article_players ap"
            " LEFT JOIN articles a ON a.content_hash = ap.content_hash"
            " WHERE a.content_hash IS NULL")).scalar()


def test_upsert_moves_attributions_when_hash_is_rewritten(engine):
    """같은 주소인데 원문 제목이 바뀌면 upsert 가 해시를 갈아 치운다.

    그때 선수 귀속을 함께 옮기지 않으면 그 자리에서 고아가 된다 (2026-08-31 운영 실측
    — 고아를 0으로 만든 다음 회차에 2쌍이 생겼다). 트윗 본문이 회차마다 다르게 읽히는
    것이 주 방아쇠다.
    """
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="old_hash", url="https://x.test/tweet", title="짧게 잘린 원문")])
    _attach_player(engine, "old_hash")

    store.upsert([_art(h="new_hash", url="https://x.test/tweet", title="전문으로 다시 읽힌 원문")])

    assert _orphan_count(engine) == 0
    with engine.connect() as c:
        moved = c.execute(text(
            "SELECT content_hash FROM article_players WHERE player_id = 1")).scalars().all()
    assert moved == ["new_hash"]
    assert store.count() == 1


def test_upsert_leaves_attributions_alone_when_hash_is_unchanged(engine):
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="same_hash", url="https://x.test/stable", title="그대로")])
    _attach_player(engine, "same_hash", player_id=2)

    store.upsert([_art(h="same_hash", url="https://x.test/stable", title="그대로")])

    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT content_hash FROM article_players WHERE player_id = 2")).scalars().all()
    assert rows == ["same_hash"]
    assert _orphan_count(engine) == 0


def test_upsert_hash_move_keeps_one_row_when_player_already_on_new_hash(engine):
    """같은 선수가 옛 해시와 새 해시 양쪽에 있으면 남는 쪽만 남는다 (PK 충돌)."""
    from sqlalchemy import text
    store = MartStore(engine)
    store.upsert([_art(h="dup_old", url="https://x.test/dup", title="이전")])
    _attach_player(engine, "dup_old", player_id=3)
    _attach_player(engine, "dup_new", player_id=3, role="mention")

    store.upsert([_art(h="dup_new", url="https://x.test/dup", title="이후")])

    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT content_hash FROM article_players WHERE player_id = 3")).scalars().all()
    assert rows == ["dup_new"]
    assert _orphan_count(engine) == 0
