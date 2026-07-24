from datetime import datetime, timedelta
from bullet_in.quality import (success_rate, volume_anomaly, volume_anomalies,
                               Anomaly, evaluate_freshness)

def test_success_rate_excludes_errored_sources():
    assert success_rate(total_sources=5, errored=1) == 0.8

def test_volume_anomaly_flags_drop_beyond_threshold():
    assert volume_anomaly(today=2, history=[20, 22, 18, 21], sigma=2.0) is True

def test_volume_anomaly_ok_within_band():
    assert volume_anomaly(today=20, history=[20, 22, 18, 21], sigma=2.0) is False


def _hist(*dicts):
    return list(dicts)


def test_volume_anomalies_flags_only_dropped_source():
    today = {"a": 20, "b": 0}
    history = _hist({"a": 20, "b": 18}, {"a": 21, "b": 19},
                    {"a": 19, "b": 20}, {"a": 20, "b": 18})
    result = volume_anomalies(today, history)
    assert [a.source_id for a in result] == ["b"]
    assert result[0].direction == "drop"
    assert result[0].today == 0


def test_volume_anomalies_flags_source_absent_today():
    today = {"a": 20}  # b 가 today 에서 사라짐
    history = _hist({"a": 20, "b": 18}, {"a": 21, "b": 19},
                    {"a": 19, "b": 20}, {"a": 20, "b": 18})
    result = volume_anomalies(today, history)
    assert [a.source_id for a in result] == ["b"]
    assert result[0].today == 0


def test_volume_anomalies_skips_low_baseline_source():
    today = {"c": 0}  # 평균 1.5 < min_baseline 3.0 → skip
    history = _hist({"c": 2}, {"c": 1}, {"c": 2}, {"c": 1})
    assert volume_anomalies(today, history) == []


def test_volume_anomalies_no_detection_with_thin_history():
    today = {"a": 0}
    history = _hist({"a": 20})  # history 1 개 → 무탐지
    assert volume_anomalies(today, history) == []


def test_volume_anomalies_quiet_when_within_band():
    today = {"a": 20, "b": 19}
    history = _hist({"a": 20, "b": 18}, {"a": 21, "b": 19},
                    {"a": 19, "b": 20}, {"a": 20, "b": 18})
    assert volume_anomalies(today, history) == []


_NOW = datetime(2026, 7, 13, 12, 0, 0)


def _wm(hours_ago: float):
    return _NOW - timedelta(hours=hours_ago)


def test_evaluate_freshness_flags_source_over_default_threshold():
    [r] = evaluate_freshness({"bbc_sport": _wm(50)}, _NOW, default_hours=48)
    assert r.stale is True
    assert r.age_hours == 50.0
    assert r.threshold_hours == 48.0
    assert r.last_fetched_at == _wm(50)


def test_evaluate_freshness_quiet_within_threshold():
    [r] = evaluate_freshness({"bbc_sport": _wm(10)}, _NOW, default_hours=48)
    assert r.stale is False


def test_evaluate_freshness_applies_source_override():
    [r] = evaluate_freshness({"x_afcstuff": _wm(30)}, _NOW, default_hours=48,
                             overrides={"x_afcstuff": 24})
    assert r.stale is True
    assert r.threshold_hours == 24.0


def test_evaluate_freshness_null_watermark_recorded_but_not_stale():
    [r] = evaluate_freshness({"new_source": None}, _NOW, default_hours=48)
    assert r.last_fetched_at is None
    assert r.age_hours is None
    assert r.stale is False


def test_evaluate_freshness_exact_threshold_not_stale():
    [r] = evaluate_freshness({"bbc_sport": _wm(48)}, _NOW, default_hours=48)
    assert r.age_hours == 48.0
    assert r.stale is False


def test_evaluate_freshness_empty_input():
    assert evaluate_freshness({}, _NOW, default_hours=48) == []


def test_evaluate_freshness_returns_all_sources_sorted():
    records = evaluate_freshness({"b": _wm(1), "a": None}, _NOW, default_hours=48)
    assert [r.source_id for r in records] == ["a", "b"]


from bullet_in.quality import evaluate_coverage

def test_evaluate_coverage_no_candidates():
    assert evaluate_coverage({"candidates": 0, "men_tagged": 0,
                              "accepted": 0}) == ["no_candidates"]

def test_evaluate_coverage_men_vanished():
    assert evaluate_coverage({"candidates": 12, "men_tagged": 0,
                              "accepted": 0}) == ["no_men_tag"]

def test_evaluate_coverage_quiet_window_is_normal():
    # accept 0 은 비수기 정상 — 알림 축이 아니다 (spec §5)
    assert evaluate_coverage({"candidates": 12, "men_tagged": 5,
                              "accepted": 0}) == []

def test_evaluate_coverage_empty_dict_is_normal():
    assert evaluate_coverage({}) == []
