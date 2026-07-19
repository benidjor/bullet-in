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
    assert store.seen_map()["https://x.test/a"] == ("h2", 2)
    missing = {r["content_hash"] for r in store.rows_missing_translation()}
    assert "h2" in missing  # translation reset so enrich re-runs


def test_rows_missing_stage_and_set_stage(engine):
    from bullet_in.models import Article
    from datetime import datetime, timezone
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
    store.set_stage("hs", "negotiating")
    assert "hs" not in {r["content_hash"] for r in store.rows_missing_stage()}


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
