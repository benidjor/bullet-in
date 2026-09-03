import json
from datetime import datetime
from sqlalchemy import create_engine, text
from bullet_in.run import RUN_INSERT_SQL, RUN_FINISH_SQL, RUN_SELECT_SQL, FetchSummary
from tests.integration.conftest import TEST_URL


def _params(rid="bench-run", fetch=7.5, blocked=0):
    return {"rid": rid, "drid": "test",
            "started": datetime(2026, 7, 14, 3, 0, 0),
            "fetch": fetch,
            "counts": json.dumps({"bbc_sport": 2}),
            "cands": json.dumps({"bbc_sport": 4}),
            "new": 2, "dup": 0, "blocked": blocked, "err": 1, "sr": 0.9,
            "detail": json.dumps({"errors": {"fmkorea": "HTTP 430"},
                                  "funnels": {"fmkorea": {"found": 15}}})}


def test_insert_leaves_finish_columns_empty_and_records_fetch(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params())
        row = c.execute(text(
            "SELECT started_at, fetch_duration_sec, finished_at, duration_sec "
            "FROM pipeline_runs WHERE run_id='bench-run'")).mappings().one()
    assert row["fetch_duration_sec"] == 7.5
    assert row["started_at"] == datetime(2026, 7, 14, 3, 0, 0)
    assert row["finished_at"] is None and row["duration_sec"] is None


def test_finish_sets_utc_finished_at_and_duration(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-finish"))
        c.execute(text(RUN_FINISH_SQL), {"rid": "bench-finish", "dur": 42.0})
        row = c.execute(text(
            "SELECT duration_sec, TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) AS drift "
            "FROM pipeline_runs WHERE run_id='bench-finish'")).mappings().one()
    assert row["duration_sec"] == 42.0
    assert abs(row["drift"]) <= 60


def test_select_roundtrips_fetch_summary(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-select", blocked=15))
        row = c.execute(text(RUN_SELECT_SQL), {"rid": "bench-select"}).mappings().one()
    s = FetchSummary.from_row(row)
    assert s.blocked_count == 15 and s.candidate_counts == {"bbc_sport": 4}
    assert s.errors == {"fmkorea": "HTTP 430"} and s.funnels == {"fmkorea": {"found": 15}}


def test_finished_at_stays_utc_under_kst_session(engine):
    # NOW() 회귀면 finished_at 이 +9h(32400s) 어긋난다 — UTC_TIMESTAMP() 검증
    kst = create_engine(TEST_URL,
                        connect_args={"init_command": "SET time_zone = '+09:00'"})
    with kst.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-kst"))
        c.execute(text(RUN_FINISH_SQL), {"rid": "bench-kst", "dur": 1.0})
        drift = c.execute(text(
            "SELECT TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) "
            "FROM pipeline_runs WHERE run_id='bench-kst'")).scalar_one()
    kst.dispose()
    assert abs(drift) <= 60
