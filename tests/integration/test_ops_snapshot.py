import json
from datetime import datetime, timedelta
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.storage.mariadb import MartStore


def _seed_runs(engine, n, base=datetime(2026, 7, 1, 0, 0)):
    rows = [{"rid": f"run-{i:03d}", "t": base + timedelta(hours=6 * i),
             "dur": 60.0 + i,
             "fetch": None if i % 2 == 0 else 4.0 + i,   # NULL 혼재 이력
             # i % 2 회차만 bbc_sport 키 존재 → 희소 표현 (부재 = 0 계약은 뷰모델이 검증)
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


def _seed_players(engine):
    """squad · external · manager 하나씩과 주체 · 언급 귀속."""
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (id,full_name,surname,ko_name,category,status,transfer_status,origin,added_at) "
            "VALUES (:id,:full,:sur,:ko,:cat,'active','none','seed',:at)"),
            [{"id": 1, "full": "Bruno Guimaraes", "sur": "Guimaraes", "ko": "기마랑이스", "cat": "squad", "at": datetime(2026, 7, 1)},
             {"id": 2, "full": "Julian Alvarez", "sur": "Alvarez", "ko": None, "cat": "external", "at": datetime(2026, 7, 1)},
             {"id": 3, "full": "Mikel Arteta", "sur": "Arteta", "ko": "아르테타", "cat": "manager", "at": datetime(2026, 7, 1)}])
        c.execute(text(
            "INSERT INTO article_players (content_hash,player_id,stage,extracted_at,role) "
            "VALUES (:h,:pid,'rumour',:at,:role)"),
            [{"h": "h1", "pid": 1, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h2", "pid": 1, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h3", "pid": 1, "at": datetime(2026, 7, 10), "role": "mention"},
             {"h": "h1", "pid": 2, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h1", "pid": 3, "at": datetime(2026, 7, 10), "role": "subject"}])


def test_ops_snapshot_returns_all_finished_runs_since_epoch_ascending(engine):
    _seed_runs(engine, 35)
    snap = MartStore(engine).ops_snapshot()
    assert len(snap["runs_all"]) == 35                     # 30 으로 안 자른다 (회차 전체)
    assert snap["runs_all"][0]["run_id"] == "run-000"      # 과거 → 최신
    assert snap["runs_all"][-1]["run_id"] == "run-034"
    assert isinstance(snap["runs_all"][1]["source_counts"], dict)
    assert snap["runs_all"][1]["source_counts"] == {"bbc_sport": 3}   # run-001 (홀수)


def test_ops_snapshot_drops_runs_before_first_live_run(engine):
    # 6시간 간격 셋: run-000 06-11 12:00 · run-001 06-11 18:00 · run-002 06-12 00:00 (경계 포함)
    _seed_runs(engine, 3, base=datetime(2026, 6, 11, 12, 0))
    snap = MartStore(engine).ops_snapshot()
    assert [r["run_id"] for r in snap["runs_all"]] == ["run-002"]


def test_ops_snapshot_freshness_window_and_null_age(engine):
    _seed_freshness(engine, 14)
    snap = MartStore(engine).ops_snapshot()
    run_ids = {r["run_id"] for r in snap["freshness"]}
    assert len(run_ids) == 12                             # 최근 12회 창
    assert "run-000" not in run_ids and "run-001" not in run_ids
    assert snap["freshness"][0]["checked_at"] <= snap["freshness"][-1]["checked_at"]
    nulls = [r for r in snap["freshness"] if r["source_id"] == "never_source"]
    assert nulls and all(r["age_hours"] is None for r in nulls)


def test_ops_snapshot_latency_applies_runbook_filters(engine):
    store = MartStore(engine)
    store.upsert([
        _art("h1", "https://x.test/1", published_at=datetime(2026, 7, 20, 0, 0), fetched_at=datetime(2026, 7, 20, 2, 0)),   # 2.0h
        _art("h2", "https://x.test/2", published_at=datetime(2026, 7, 1, 0, 0), fetched_at=datetime(2026, 7, 10, 0, 0)),    # 07-14 이전 수집
        _art("h3", "https://x.test/3", published_at=datetime(2026, 6, 1, 0, 0), fetched_at=datetime(2026, 7, 20, 0, 0)),    # 30일 초과
        _art("h4", "https://x.test/4", published_at=datetime(2026, 7, 21, 0, 0), fetched_at=datetime(2026, 7, 20, 0, 0)),   # 발행이 수집보다 뒤
    ])
    assert store.ops_snapshot()["latency"] == [("bbc_sport", 2.0)]


def test_ops_snapshot_weekly_mix_and_articles_total(engine):
    store = MartStore(engine)
    store.upsert([
        _art("h1", "https://x.test/1", fetched_at=datetime(2026, 7, 20), tier=4, transfer_stage="rumour", journalist="Kim"),
        _art("h2", "https://x.test/2", fetched_at=datetime(2026, 7, 21), tier=4, transfer_stage="rumour", journalist=None),
        _art("h3", "https://x.test/3", fetched_at=datetime(2026, 7, 22), tier=1, transfer_stage=None, journalist=""),
        _art("h4", "https://x.test/4", fetched_at=datetime(2026, 7, 1), tier=1, transfer_stage="done", journalist="Lee"),   # 07-13 이전
    ])
    snap = store.ops_snapshot()
    rows = sorted(snap["weekly_mix"], key=lambda r: (r["tier"], str(r["stage"])))
    assert rows == [{"yw": 202630, "tier": 1.0, "stage": None, "n": 1, "n_byline": 0},
                    {"yw": 202630, "tier": 4.0, "stage": "rumour", "n": 2, "n_byline": 1}]
    assert snap["articles_total"] == 4                      # 총수는 창과 무관


def test_ops_snapshot_player_subjects_counts_subject_rows_of_squad_and_external_only(engine):
    _seed_players(engine)
    rows = sorted(MartStore(engine).ops_snapshot()["player_subjects"], key=lambda r: r["player_id"])
    assert rows == [{"player_id": 1, "ko_name": "기마랑이스", "category": "squad", "n": 2},     # 언급 1건은 안 센다
                    {"player_id": 2, "ko_name": None, "category": "external", "n": 1}]          # 감독 (3) 은 뺀다


def test_ops_snapshot_cold_start_returns_empty_shapes(engine):
    snap = MartStore(engine).ops_snapshot()
    assert snap == {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [],
                    "player_subjects": [], "articles_total": 0, "high_retention": []}


def test_ops_snapshot_includes_fetch_duration_with_nulls(engine):
    _seed_runs(engine, 3)
    snap = MartStore(engine).ops_snapshot()
    # 오름차순: run-000 (NULL) · run-001 (4.0+1=5.0) · run-002 (NULL) — 손 재계산
    assert snap["runs_all"][0]["fetch_duration_sec"] is None
    assert snap["runs_all"][1]["fetch_duration_sec"] == 5.0


def test_ops_snapshot_excludes_unfinished_runs(engine):
    """마감되지 않은 회차 (finished_at IS NULL) 는 스냅샷에서 제외된다."""
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:fetch,:counts,:new,:dup,:err,:sr)"),
            [{"rid": "run-finished", "t": datetime(2026, 7, 1, 0, 0),
              "dur": 60.0, "fetch": 5.0, "counts": json.dumps({}),
              "new": 1, "dup": 2, "err": 0, "sr": 0.9}])
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,"
            "fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:fetch,:counts,:new,:dup,:err,:sr)"),
            [{"rid": "run-unfinished", "t": datetime(2026, 7, 1, 6, 0),
              "fetch": 5.0, "counts": json.dumps({}),
              "new": 1, "dup": 2, "err": 0, "sr": 0.9}])
    run_ids = [r["run_id"] for r in MartStore(engine).ops_snapshot()["runs_all"]]
    assert "run-finished" in run_ids
    assert "run-unfinished" not in run_ids
