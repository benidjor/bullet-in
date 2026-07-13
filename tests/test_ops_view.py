from datetime import datetime
from bullet_in.serve.render import build_ops_view, spark_points

NOW = datetime(2026, 7, 14, 9, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"},
           "fmkorea": {"display_name": "fmkorea"},
           "dead_source": {"display_name": "Dead"}}


def _run(rid, t, counts, new=5, dup=2, err=0, sr=1.0, dur=80.0):
    return {"run_id": rid, "started_at": t, "duration_sec": dur,
            "source_counts": counts, "new_count": new, "dup_count": dup,
            "error_count": err, "success_rate": sr}


def _fresh(rid, t, sid, age, stale=0, thr=48.0):
    return {"run_id": rid, "checked_at": t, "source_id": sid,
            "last_fetched_at": t if age is not None else None,
            "age_hours": age, "threshold_hours": thr, "stale": stale}


def _snapshot():
    t = datetime(2026, 7, 13, 0, 0)
    runs = [_run("r3", datetime(2026, 7, 14, 6, 0), {"bbc_sport": 4}, err=1),
            _run("r2", datetime(2026, 7, 14, 0, 0), {}),                    # 부분 부재
            _run("r1", datetime(2026, 7, 13, 18, 0), {"bbc_sport": 2, "fmkorea": 7})]
    fresh = [_fresh("r1", t, "bbc_sport", 5.0),
             _fresh("r2", datetime(2026, 7, 13, 6, 0), "bbc_sport", 11.0),
             _fresh("r3", datetime(2026, 7, 13, 12, 0), "bbc_sport", 26.0, stale=1, thr=24.0),
             _fresh("r3", datetime(2026, 7, 13, 12, 0), "never", None)]
    return {"runs": runs, "freshness": fresh,
            "tier_counts": {1.0: 4, 2.0: 3, 99.0: 1},
            "pending": {"fmkorea": {"translate": 5, "stage": 2}}}


def test_volume_counts_absent_rounds_as_zero_and_shows_dead_sources():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    by_name = {v["display"]: v for v in view["volume"]}
    assert by_name["BBC Sport"]["total"] == 6      # 4 + 0(부재) + 2
    assert by_name["fmkorea"]["total"] == 7        # 0(부재) + 0(부재) + 7
    assert by_name["Dead"]["total"] == 0           # 전 회차 부재도 행 노출


def test_freshness_null_age_is_none_status_and_partial_history_kept():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    rows = {v["display"]: v for v in view["freshness"]}
    assert rows["never"]["status"] == "none"       # 빨강 금지 → 중립
    assert rows["never"]["points"] == ""
    assert rows["BBC Sport"]["status"] == "stale"  # 최신 run(r3) 저장값 그대로
    assert rows["BBC Sport"]["points"]             # 있는 회차만으로 좌표 생성


def test_kpi_from_latest_run_and_pending_total():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=2, now=NOW)
    assert view["kpi"]["new"] == "5" and view["kpi"]["err"] == "1"
    assert view["kpi"]["stale"] == "1"
    assert view["kpi"]["pending"] == "7"           # 5 + 2
    slo6 = [s for s in view["slo"] if s["slo_id"] == "SLO-6"][0]
    assert slo6["value"] == "2"


def test_tier_out_of_range_folds_into_etc():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    etc = [t for t in view["tiers"] if t["label"].startswith("기타")][0]
    assert etc["count"] == 1


def test_slo5_neutral_when_no_freshness_history():
    snap = _snapshot()
    snap["freshness"] = []                      # runs 는 있고 freshness 만 없음
    view = build_ops_view(snap, SOURCES, anomaly_count=0, now=NOW)
    slo5 = [s for s in view["slo"] if s["slo_id"] == "SLO-5"][0]
    assert slo5["value"] == "—" and slo5["status"] == "info"


def test_cold_start_renders_dashes_without_crash():
    empty = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}
    view = build_ops_view(empty, SOURCES, anomaly_count=0, now=NOW)
    assert view["kpi"]["new"] == "—" and view["runs_chart"] == []
    assert view["generated_at"].endswith("UTC")


def test_spark_points_guards_zero_and_single_values():
    assert spark_points([]) == ""
    assert spark_points([0, 0, 0])                 # 전부 0 → 평평, 예외 없음
    assert " " not in spark_points([5.0])          # 단일값 → 점 1개
    pts = spark_points([1.0, 2.0, 3.0])
    assert len(pts.split(" ")) == 3
