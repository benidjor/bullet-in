from datetime import datetime

from bullet_in.canonical import canonical_url, content_hash
from bullet_in.migrate_url_identity import plan

_SLUG = "https://www.nytimes.com/athletic/7523792/2026/08/20/ethan-nwaneri-arsenal-future"
_BARE = "https://www.nytimes.com/athletic/7523792/2026/08/20"


def _row(url, title="제목", level=1, day=20, h=None):
    return {"content_hash": h or ("h" + str(day) + str(level)), "url": url,
            "source_id": "fmkorea", "title_original": title,
            "created_at": datetime(2026, 8, day), "body_level": level}


def test_plan_migrates_url_and_hash_together():
    # 주소만 고치면 다음 회차가 해시를 갈아 치운다 — 계획에 둘이 함께 들어가야 한다.
    r = _row(_SLUG)
    merges, migrations = plan([r])
    assert merges == []
    assert migrations == [(r["content_hash"], _BARE, content_hash("제목", _BARE))]


def test_plan_is_idempotent_on_already_normalised_rows():
    url = _BARE
    r = _row(url, h=content_hash("제목", url))
    assert plan([r]) == ([], [])


def test_plan_merges_rows_that_collapse_to_one_key():
    keep = _row(_SLUG, level=2, day=20, h="keep")
    drop = _row(_BARE, level=1, day=21, h="drop")
    merges, migrations = plan([keep, drop])
    assert merges == [("keep", ["drop"])]
    # 남는 쪽은 주소 · 해시가 함께 정규화 값으로 간다
    assert migrations == [("keep", _BARE, content_hash("제목", _BARE))]


def test_plan_keeps_earlier_row_when_levels_tie():
    early = _row(_SLUG, level=1, day=20, h="early")
    late = _row(_BARE, level=1, day=21, h="late")
    merges, _ = plan([early, late])
    assert merges == [("early", ["late"])]


def test_plan_leaves_distinct_articles_alone():
    a = _row("https://www.bbc.com/sport/football/articles/aaa", h="a")
    b = _row("https://www.bbc.com/sport/football/articles/bbb", h="b")
    merges, migrations = plan([a, b])
    assert merges == []
    # 주소는 이미 정규형이지만 해시는 저장값이 임의라 이전 대상이 된다
    assert {m[0] for m in migrations} == {"a", "b"}
    assert all(m[1] == canonical_url(m[1]) for m in migrations)


def test_plan_new_hash_matches_what_the_pipeline_would_compute():
    # 이 배치의 잣대가 제품과 같은지 — 파이프라인은 원문 제목과 정규화 주소로 해시를 만든다.
    r = _row(_SLUG, title="Ethan Nwaneri and the cold reality")
    _merges, migrations = plan([r])
    _old, new_url, new_hash = migrations[0]
    assert new_hash == content_hash("Ethan Nwaneri and the cold reality", canonical_url(_SLUG))
