from datetime import datetime, timedelta
from bullet_in.quality import (success_rate, volume_anomaly, volume_anomalies,
                               Anomaly, evaluate_freshness, candidate_cliffs)

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


def test_candidate_cliffs_detects_transition_to_zero():
    # fmkorea 가 직전 회차 10건에서 이번 회차 0건으로 떨어진 경우
    previous = {"fmkorea": 10, "goal": 13, "guardian": 8}
    today = {"goal": 14, "guardian": 8}
    assert candidate_cliffs(today, previous) == ["fmkorea"]


def test_candidate_cliffs_ignores_source_that_was_already_zero():
    # arsenal_official 은 직전에도 이번에도 0 — 전이가 아니므로 발화하지 않는다
    previous = {"arsenal_official": 0, "goal": 13}
    today = {"goal": 14}
    assert candidate_cliffs(today, previous) == []


def test_candidate_cliffs_returns_empty_when_no_previous_run():
    # 첫 회차 — 직전 행이 없으면 판정 대상이 없다
    assert candidate_cliffs({"goal": 14}, {}) == []


def test_candidate_cliffs_sorted_for_stable_alert_order():
    previous = {"skysports": 5, "fmkorea": 10}
    assert candidate_cliffs({}, previous) == ["fmkorea", "skysports"]


def test_evaluate_freshness_zero_override_excludes_source():
    # freshness_hours: 0 = 감시 제외 (스펙 2026-08-07 §3.2) — 이벤트 구동 소스는
    # 정상 공백 상한이 없어 유한 임계가 성립하지 않는다 (arsenal_official).
    now = datetime(2026, 8, 7, 6, 0, 0)
    wm = {"arsenal_official": now - timedelta(hours=360), "bbc_sport": now}
    records = evaluate_freshness(wm, now, 48.0, {"arsenal_official": 0.0})
    assert [r.source_id for r in records] == ["bbc_sport"]


def test_filter_miss_suspects_pattern_and_recency():
    # 이적 관련 제목 + 발행 6시간 이내만 — 옛 기사 (lastmod 부활) 와 무관 제목 제외
    from datetime import datetime, timezone
    from bullet_in.quality import filter_miss_suspects
    now = datetime(2026, 8, 6, 0, 0, 0, tzinfo=timezone.utc)
    rejects = [
        {"title": "Christian Norgaard joins Everton", "url": "u1",
         "published": "2026-08-05T21:09:44.542Z", "taxonomies": ["Men", "News"]},
        {"title": "Match Categories", "url": "u2",
         "published": "2026-08-05T22:00:00.000Z", "taxonomies": ["Men", "News"]},
        {"title": "Old signs for Arsenal", "url": "u3",
         "published": "2019-05-20T13:25:27.000Z", "taxonomies": ["Men", "News"]},
        {"title": "Player signs new deal", "url": "u4",
         "published": None, "taxonomies": ["Men", "News"]},
    ]
    assert [s["url"] for s in filter_miss_suspects(rejects, now)] == ["u1"]


def test_filter_miss_suspects_skips_naive_published_without_raising():
    # published 가 오프셋 없는 naive ISO 문자열이면 (now - dt) 가 TypeError —
    # 그 항목만 건너뛰고 나머지는 정상 판정한다 (재현 사례: run.py 관측 루프 전멸 방지)
    from datetime import datetime, timezone
    from bullet_in.quality import filter_miss_suspects
    now = datetime(2026, 8, 7, 6, 0, 0, tzinfo=timezone.utc)
    rejects = [
        {"title": "Player joins Everton", "url": "naive",
         "published": "2026-08-07T01:00:00", "taxonomies": ["Men", "News"]},
        {"title": "Christian Norgaard joins Everton", "url": "aware",
         "published": "2026-08-07T01:00:00.000Z", "taxonomies": ["Men", "News"]},
    ]
    assert [s["url"] for s in filter_miss_suspects(rejects, now)] == ["aware"]


# ── 명단 이적 축 낡음 관측 (스펙 2026-08-10) ─────────────────────────────

def _pair(pid, name, status, stage):
    return {"player_id": pid, "ko_name": name,
            "transfer_status": status, "stage": stage}


def test_roster_staleness_fires_on_completion_signal_for_link_player():
    # 기마랑이스형 — in_link 인데 합의 확정 보도가 붙는다
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(28, "기마랑이스", "in_link", "agreed")],
        {(28, "agreed"): 5})
    assert len(cases) == 1
    assert cases[0]["kind"] == "finish"
    assert cases[0]["new_stages"] == {"agreed": 1}
    assert cases[0]["recent_total"] == 5


def test_roster_staleness_fires_on_progress_for_none_player():
    # 비니시우스형 — 축 값 none 인데 링크 단계 보도가 쌓인다
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(15, "비니시우스", "none", "interest"),
         _pair(15, "비니시우스", "none", "negotiating")],
        {(15, "interest"): 1, (15, "negotiating"): 1})
    assert len(cases) == 1
    assert cases[0]["kind"] == "start"
    assert cases[0]["recent_total"] == 2


def test_roster_staleness_silent_on_completion_echo_for_done_player():
    # 완결 직후 후속 보도의 메아리 — in_done + agreed 는 방아쇠가 아니다
    from bullet_in.quality import roster_axis_staleness
    assert roster_axis_staleness(
        [_pair(28, "기마랑이스", "in_done", "agreed")],
        {(28, "agreed"): 50}) == []


def test_roster_staleness_new_saga_on_done_player_counts_early_only():
    # 완료 축 선수의 새 이적 건 — 초기 단계는 방아쇠 · 누적에 완결 메아리는 안 섞임
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(7, "마두에케", "in_done", "interest")],
        {(7, "interest"): 2, (7, "agreed"): 40})
    assert len(cases) == 1
    assert cases[0]["recent_total"] == 2


def test_roster_staleness_silent_below_recent_threshold():
    # 단발 루머 1건 — 최근 7일 누적 2건 미만이면 침묵
    from bullet_in.quality import roster_axis_staleness
    assert roster_axis_staleness(
        [_pair(99, "아무개", "none", "rumour")], {(99, "rumour"): 1}) == []


def test_roster_staleness_ignores_other_stage_and_closed_axis():
    # other 귀속과 종결 축 (other_club 등) 은 판정 대상이 아니다
    from bullet_in.quality import roster_axis_staleness
    assert roster_axis_staleness(
        [_pair(1, "가", "none", "other"),
         _pair(2, "나", "other_club", "agreed")],
        {(1, "other"): 9, (2, "agreed"): 9}) == []


def test_roster_staleness_sorted_by_name_for_stable_alert_order():
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(2, "나", "in_link", "agreed"), _pair(1, "가", "in_link", "medical")],
        {(1, "medical"): 2, (2, "agreed"): 2})
    assert [c["ko_name"] for c in cases] == ["가", "나"]


def test_roster_staleness_fires_on_done_stage_for_link_player():
    # 단계 재정의 (스펙 2026-08-10 §4) 로 완결 딜이 done 으로 붙는다 — 침묵하면 안 된다
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(122, "뇌르고르", "out_link", "done")], {(122, "done"): 4})
    assert len(cases) == 1 and cases[0]["kind"] == "finish"


def test_roster_staleness_fires_on_collapsed_stage_for_link_player():
    # 무산도 축을 정리해야 하는 종결이다 (link_dropped · other_club 전이)
    from bullet_in.quality import roster_axis_staleness
    cases = roster_axis_staleness(
        [_pair(31, "알바레스", "in_link", "collapsed")], {(31, "collapsed"): 3})
    assert len(cases) == 1 and cases[0]["kind"] == "finish"


def test_roster_staleness_silent_on_closing_stage_for_axisless_player():
    # 축이 없는 선수 (지난 창 정리 완료) 에게 붙는 종결 단계는 회고 보도라 갱신할 것이 없다
    from bullet_in.quality import roster_axis_staleness
    assert roster_axis_staleness(
        [_pair(27, "요케레스", "none", "done")], {(27, "done"): 6}) == []
