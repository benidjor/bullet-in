import json
from datetime import datetime, timedelta
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.storage.mariadb import MartStore


def _seed_runs(engine, n, base=datetime(2026, 7, 1, 0, 0)):
    rows = [{"rid": f"run-{i:03d}", "t": base + timedelta(hours=6 * i),
             "dur": 60.0 + i,
             "fetch": None if i % 2 == 0 else 4.0 + i,   # NULL 혼재 이력
             # i % 2 회차만 bbc_sport 키 존재 → 희소 표현 (부재 = 0 계약은 Task 2 가공에서 검증)
             "counts": json.dumps({"bbc_sport": 3} if i % 2 else {}),
             "new": i % 3, "dup": 2, "err": 1 if i == n - 1 else 0, "sr": 0.9}
            for i in range(n)]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:fetch,:counts,:new,:dup,:err,:sr)"), rows)


def _seed_freshness(engine, n_runs, base=datetime(2026, 7, 1, 0, 0)):
    rows = []
    for i in range(n_runs):
        at = base + timedelta(hours=6 * i)
        rows.append({"rid": f"run-{i:03d}", "at": at, "sid": "bbc_sport",
                     "wm": at, "age": float(i), "thr": 48.0, "stale": 0})
        # never_source 는 워터마크 없음 → age NULL · stale=0 (판정 계층 계약)
        rows.append({"rid": f"run-{i:03d}", "at": at, "sid": "never_source",
                     "wm": None, "age": None, "thr": 48.0, "stale": 0})
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO source_freshness (run_id,checked_at,source_id,"
            "last_fetched_at,age_hours,threshold_hours,stale) "
            "VALUES (:rid,:at,:sid,:wm,:age,:thr,:stale)"), rows)


def _art(h, url, **kw):
    base = dict(content_hash=h, url=url, source_id="bbc_sport",
                title_original="T", published_at=datetime(2026, 7, 10),
                fetched_at=datetime(2026, 7, 10), tier=2)
    base.update(kw)
    return Article(**base)


def test_ops_snapshot_limits_runs_newest_first_and_parses_counts(engine):
    _seed_runs(engine, 35)
    snap = MartStore(engine).ops_snapshot()
    assert len(snap["runs"]) == 30
    assert snap["runs"][0]["run_id"] == "run-034"        # 최신 우선
    assert isinstance(snap["runs"][1]["source_counts"], dict)
    assert snap["runs"][1]["source_counts"] == {"bbc_sport": 3}  # run-033 (홀수)


def test_ops_snapshot_freshness_window_and_null_age(engine):
    _seed_freshness(engine, 14)
    snap = MartStore(engine).ops_snapshot()
    run_ids = {r["run_id"] for r in snap["freshness"]}
    assert len(run_ids) == 12                             # 최근 12회 창
    assert "run-000" not in run_ids and "run-001" not in run_ids
    assert snap["freshness"][0]["checked_at"] <= snap["freshness"][-1]["checked_at"]
    nulls = [r for r in snap["freshness"] if r["source_id"] == "never_source"]
    assert nulls and all(r["age_hours"] is None for r in nulls)


def test_ops_snapshot_tier_counts_and_pending(engine):
    store = MartStore(engine)
    store.upsert([_art("h1", "https://x.test/1", title_ko="번역됨", transfer_stage="rumor"),
                  _art("h2", "https://x.test/2"),
                  _art("h3", "https://x.test/3", tier=3)])
    snap = store.ops_snapshot()
    assert snap["tier_counts"] == {2.0: 2, 3.0: 1}
    # rows_missing_translation (title_ko IS NULL) · rows_missing_stage 와 동일 술어
    assert snap["pending"]["bbc_sport"] == {"translate": 2, "stage": 2}


def test_ops_snapshot_cold_start_returns_empty_shapes(engine):
    snap = MartStore(engine).ops_snapshot()
    assert snap == {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}


def test_ops_snapshot_includes_fetch_duration_with_nulls(engine):
    _seed_runs(engine, 3)
    snap = MartStore(engine).ops_snapshot()
    # 최신순: run-002 (i=2, NULL) · run-001 (i=1, 4.0+1=5.0) · run-000 (NULL) — 손 재계산
    assert snap["runs"][0]["fetch_duration_sec"] is None
    assert snap["runs"][1]["fetch_duration_sec"] == 5.0
