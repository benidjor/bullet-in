from bullet_in.backfill_tweet_full_text import plan
from bullet_in.canonical import content_hash

URL = "https://x.com/afcstuff/status/1"
SHORT = "Ornstein: “Alvarez has"
FULL = SHORT + " shown no indication of wanting to join.”  [TNT]"


def test_plan_migrates_identity_when_the_full_text_is_longer():
    rows = [{"content_hash": content_hash(SHORT, URL), "url": URL,
             "title_original": SHORT}]
    texts = {rows[0]["content_hash"]: FULL}
    apply_, skip = plan(rows, texts, existing=set())
    assert not skip
    assert apply_[0]["full"] == FULL
    assert apply_[0]["new_hash"] == content_hash(FULL, URL)
    assert apply_[0]["new_hash"] != rows[0]["content_hash"]


def test_plan_is_idempotent_once_the_full_text_is_stored():
    # 두 번째 실행에서는 저장값이 이미 전문이라 더 길지 않다.
    h = content_hash(FULL, URL)
    rows = [{"content_hash": h, "url": URL, "title_original": FULL}]
    apply_, skip = plan(rows, {h: FULL}, existing={h})
    assert not apply_
    assert skip[0]["why"].startswith("전문이 더 길지 않음")


def test_plan_skips_when_the_new_hash_belongs_to_another_row():
    # 그 자리로 옮기면 남의 행을 덮는다 — 옮기지 않는다.
    old = content_hash(SHORT, URL)
    new = content_hash(FULL, URL)
    rows = [{"content_hash": old, "url": URL, "title_original": SHORT}]
    apply_, skip = plan(rows, {old: FULL}, existing={old, new})
    assert not apply_
    assert "이미 있음" in skip[0]["why"]


def test_plan_skips_rows_without_a_fetched_full_text():
    rows = [{"content_hash": "aa", "url": URL, "title_original": SHORT}]
    apply_, skip = plan(rows, {}, existing=set())
    assert not apply_ and skip[0]["why"] == "전문 없음"
