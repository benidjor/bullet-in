import json
from datetime import datetime
from sqlalchemy import create_engine, text
from bullet_in.run import RUN_INSERT_SQL
from tests.integration.conftest import TEST_URL


def _params(rid="bench-run", fetch=7.5):
    return {"rid": rid, "drid": "test",
            "started": datetime(2026, 7, 14, 3, 0, 0),
            "dur": 42.0, "fetch": fetch,
            "counts": json.dumps({"bbc_sport": 2}),
            "new": 2, "dup": 0, "err": 0, "sr": 1.0}


def test_insert_records_fetch_duration_and_started_at_roundtrip(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params())
        row = c.execute(text(
            "SELECT started_at, fetch_duration_sec, "
            "TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) AS drift "
            "FROM pipeline_runs WHERE run_id='bench-run'")).mappings().one()
    assert row["fetch_duration_sec"] == 7.5          # FLOAT 정확 표현값
    assert row["started_at"] == datetime(2026, 7, 14, 3, 0, 0)  # 바인딩 왕복
    assert abs(row["drift"]) <= 60                   # finished_at ≈ UTC now


def test_finished_at_stays_utc_under_kst_session(engine):
    # NOW() 회귀면 finished_at 이 +9h(32400s) 어긋난다 — UTC_TIMESTAMP() 검증
    kst = create_engine(TEST_URL,
                        connect_args={"init_command": "SET time_zone = '+09:00'"})
    with kst.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-kst"))
        drift = c.execute(text(
            "SELECT TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) "
            "FROM pipeline_runs WHERE run_id='bench-kst'")).scalar_one()
    kst.dispose()
    assert abs(drift) <= 60
