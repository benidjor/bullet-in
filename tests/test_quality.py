from datetime import datetime, timedelta
from bullet_in.quality import (success_rate, volume_anomaly, volume_anomalies,
                               Anomaly, evaluate_freshness, candidate_cliffs,
                               list_signature, responded,
                               evaluate_states, SourceFreshness, broken_alert_split)

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


# ── SLO-5 끊김 신호 (스펙 2026-10-02 §2.2 · §2.3) ─────────────────────────────

def test_list_signature_ignores_order_and_duplicates():
    a = list_signature(["https://x.test/2", "https://x.test/1", "https://x.test/1"])
    b = list_signature(["https://x.test/1", "https://x.test/2"])
    assert a == b and len(a) == 16


def test_list_signature_changes_when_one_link_changes():
    assert list_signature(["https://x.test/1", "https://x.test/2"]) != \
        list_signature(["https://x.test/1", "https://x.test/3"])


def test_list_signature_of_empty_list_is_empty_string():
    assert list_signature([]) == "" and list_signature(["", None]) == ""


def test_responded_error_wins_over_funnel():
    assert responded("html", {"deduped": 9, "titled": 9}, errored=True) == (False, "error")


def test_responded_without_record_is_no_response():
    assert responded("html", {}, errored=False) == (False, "no_record")
    assert responded("x_playwright", None, errored=False) == (False, "no_record")


def test_responded_html_needs_links():
    assert responded("html", {"selected": 0, "deduped": 0, "titled": 0}, False) == (False, "no_links")


def test_responded_html_title_ratio_boundary():
    # 2026-10-01 BBC Sport 실측은 7개 중 1개 (14%) 였다
    assert responded("html", {"deduped": 7, "titled": 1}, False) == (False, "title_ratio")
    assert responded("html", {"deduped": 7, "titled": 3}, False) == (False, "title_ratio")
    assert responded("html", {"deduped": 7, "titled": 4, "list_sig": "s1"}, False) == (True, "")
    assert responded("html", {"deduped": 20, "titled": 20, "list_sig": "s1"}, False) == (True, "")


def test_responded_x_needs_scraped_tweets():
    assert responded("x_playwright", {"scraped": 0, "passed": 0}, False) == (False, "no_tweets")
    assert responded("x_playwright", {"scraped": 30, "passed": 0, "list_sig": "s1"}, False) == (True, "")


def test_responded_fmkorea_partial_failure_still_responds():
    assert responded("fmkorea", {"keywords": 3, "searched": 0, "listed": 0}, False) == (False, "search_failed")
    assert responded("fmkorea", {"keywords": 3, "searched": 1, "listed": 0}, False) == (False, "no_results")
    assert responded("fmkorea", {"keywords": 3, "searched": 1, "listed": 12, "list_sig": "s1"}, False) == (True, "")


def test_responded_unknown_adapter_with_record_responds():
    assert responded("arsenal_api", {"anything": 1}, False) == (True, "")


def test_responded_without_signature_is_no_record():
    # 목록 지문이 없으면 수집 단계 기록이 깨진 것이다 — 세 모니터 어댑터는 응답 조건 미충족
    assert responded("html", {"deduped": 7, "titled": 4}, False) == (False, "no_record")
    assert responded("x_playwright", {"scraped": 30, "passed": 0}, False) == (False, "no_record")
    assert responded("fmkorea", {"keywords": 3, "searched": 1, "listed": 12}, False) == (False, "no_record")


_T0 = datetime(2026, 10, 2, 3, 0)


def _rec(sid="bbc_sport", age=10.0, thr=96.0):
    return SourceFreshness(sid, _T0 - timedelta(hours=age), thr, age, age > thr)


def _judge(rec, ok=True, reason="", sig="s1", prev=None, now=_T0, cap=48.0):
    evaluate_states([rec], {rec.source_id: (ok, reason)}, {rec.source_id: sig},
                    cap, {rec.source_id: prev} if prev else {}, now)
    return rec


def test_broken_without_signature_never_reaches_list_unchanged():
    # 두 번 연속 무응답(지문 부재)이면 -> no_response, broken (no_record) 로 끝난다
    # list_unchanged 절대 아님 (목록 서명 없으므로)
    r = _rec()
    # 첫 실행: 지문 없이 응답 시도 → no_record
    ok1, reason1 = responded("html", {"deduped": 7, "titled": 4}, False)
    assert (ok1, reason1) == (False, "no_record")
    evaluate_states([r], {r.source_id: (ok1, reason1)}, {r.source_id: None}, 48.0, {}, _T0)
    assert (r.state, r.miss_streak) == ("no_response", 1)
    # 두 번째 실행: 역시 지문 없음 → 연속 무응답 2회 → broken (이유는 no_record)
    first_prev = {"state": "no_response", "miss_streak": 1, "list_sig": None,
                  "list_changed_at": _T0, "cap_hours": 48.0, "checked_at": _T0}
    ok2, reason2 = responded("html", {"deduped": 7, "titled": 4}, False)
    assert (ok2, reason2) == (False, "no_record")
    evaluate_states([r], {r.source_id: (ok2, reason2)}, {r.source_id: None}, 48.0,
                    {r.source_id: first_prev}, _T0 + timedelta(hours=3))
    assert (r.state, r.miss_streak, r.reason) == ("broken", 2, "no_record")


def test_first_run_never_breaks_even_without_response():
    r = _judge(_rec(), ok=False, reason="title_ratio", sig=None)
    assert (r.state, r.miss_streak, r.list_changed_at) == ("no_response", 1, _T0)


def test_first_run_with_old_row_missing_new_columns_starts_fresh():
    old = {"state": None, "miss_streak": None, "list_sig": None,
           "list_changed_at": None, "cap_hours": None, "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), prev=old)
    assert (r.state, r.miss_streak, r.list_changed_at, r.cap_hours) == ("ok", 0, _T0, 48.0)


def test_two_misses_in_a_row_break():
    prev = {"state": "no_response", "miss_streak": 1, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=3), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), ok=False, reason="title_ratio", sig=None, prev=prev)
    assert (r.state, r.reason, r.miss_streak) == ("broken", "title_ratio", 2)


def test_response_resets_streak():
    prev = {"state": "broken", "miss_streak": 5, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=15), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), sig="s2", prev=prev)
    assert (r.state, r.miss_streak, r.list_changed_at) == ("ok", 0, _T0)


def test_miss_carries_previous_signature_forward():
    # 무응답 실행이 지문을 비우면 다음 응답 실행이 빈 값과 비교해 「바뀜」 으로 오판한다
    changed = _T0 - timedelta(hours=40)
    prev = {"state": "ok", "miss_streak": 0, "list_sig": "s1", "list_changed_at": changed,
            "cap_hours": 48.0, "checked_at": _T0 - timedelta(hours=3)}
    miss = _judge(_rec(), ok=False, reason="error", sig=None, prev=prev)
    assert (miss.list_sig, miss.list_changed_at) == ("s1", changed)
    nxt = {"state": miss.state, "miss_streak": miss.miss_streak, "list_sig": miss.list_sig,
           "list_changed_at": miss.list_changed_at, "cap_hours": 48.0, "checked_at": _T0}
    back = _judge(_rec(), sig="s1", prev=nxt, now=_T0 + timedelta(hours=3))
    assert back.list_changed_at == changed and back.state == "ok"


def test_list_unchanged_past_cap_breaks_even_with_candidates():
    # 07-31 함정: 매 실행 응답하고 후보도 있는데 목록이 그대로면 결국 끊김이어야 한다
    prev = {"state": "ok", "miss_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=49), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(age=2.0), sig="s1", prev=prev)
    assert (r.state, r.reason) == ("broken", "list_unchanged")


def test_off_season_silence_is_quiet_not_broken():
    # 목록은 실행마다 바뀌고 새 원본만 2주째 없다
    prev = {"state": "quiet", "miss_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=3), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(age=336.0, thr=96.0), sig="s2", prev=prev)
    assert (r.state, r.stale) == ("quiet", True)


def test_source_without_watermark_still_gets_a_state():
    r = SourceFreshness("new_source", None, 48.0, None, False)
    evaluate_states([r], {"new_source": (True, "")}, {"new_source": "s1"}, 48.0, {}, _T0)
    assert r.state == "ok"


def test_missing_response_entry_counts_as_no_record():
    r = _rec()
    evaluate_states([r], {}, {}, 48.0, {}, _T0)
    assert (r.state, r.reason) == ("no_response", "no_record")


def _broken(miss=0, changed_h=10.0, cap=48.0, now=_T0, sid="bbc_sport"):
    r = _rec(sid)
    r.state, r.miss_streak, r.cap_hours = "broken", miss, cap
    r.list_changed_at = now - timedelta(hours=changed_h)
    r.reason = "title_ratio" if miss >= 2 else "list_unchanged"
    return r


def _prev_of(r, at):
    return {r.source_id: {"state": r.state, "miss_streak": r.miss_streak, "list_sig": r.list_sig,
                          "list_changed_at": r.list_changed_at, "cap_hours": r.cap_hours,
                          "checked_at": at}}


def test_broken_alert_sends_on_first_broken_run():
    send, hold = broken_alert_split([_broken(miss=2)], {}, _T0)
    assert [r.source_id for r in send] == ["bbc_sport"] and hold == []


def test_broken_alert_holds_within_same_interval_then_resends():
    first = _broken(miss=2)
    prev = _prev_of(first, _T0)
    later = _broken(miss=17, now=_T0 + timedelta(hours=45))       # 2 + 15 → 같은 16회 구간
    assert broken_alert_split([later], prev, _T0 + timedelta(hours=45))[0] == []
    again = _broken(miss=18, now=_T0 + timedelta(hours=48))       # 2 + 16 → 다음 구간
    assert len(broken_alert_split([again], prev, _T0 + timedelta(hours=48))[0]) == 1


def test_broken_alert_list_unchanged_realerts_every_48_hours():
    first = _broken(changed_h=49)
    prev = _prev_of(first, _T0)
    same = _broken(changed_h=95, now=_T0 + timedelta(hours=46))
    assert broken_alert_split([same], prev, _T0 + timedelta(hours=46))[0] == []
    nxt = _broken(changed_h=97, now=_T0 + timedelta(hours=48))
    assert len(broken_alert_split([nxt], prev, _T0 + timedelta(hours=48))[0]) == 1


def test_broken_alert_resends_when_reason_kind_changes():
    first = _broken(changed_h=49)                                 # 목록 그대로
    prev = _prev_of(first, _T0)
    now_miss = _broken(miss=2, changed_h=52, now=_T0 + timedelta(hours=3))
    assert len(broken_alert_split([now_miss], prev, _T0 + timedelta(hours=3))[0]) == 1


def test_broken_alert_resends_when_miss_turns_into_list_unchanged():
    first = _broken(miss=2)                                       # 무응답
    prev = _prev_of(first, _T0)
    now_list = _broken(changed_h=52, now=_T0 + timedelta(hours=3))   # 응답은 돌아왔지만 목록 그대로
    assert len(broken_alert_split([now_list], prev, _T0 + timedelta(hours=3))[0]) == 1


def test_list_unchanged_exactly_at_cap_is_not_broken():
    prev = {"state": "ok", "miss_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=48), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(age=2.0), sig="s1", prev=prev)
    assert (r.state, r.reason) == ("ok", "")


def test_quiet_source_that_stops_responding_is_no_response():
    # 새 원본이 임계를 넘은 소스라도 이번 실행 무응답이면 조용함보다 응답 없음이 먼저다
    r = _judge(_rec(age=200.0, thr=96.0), ok=False, reason="title_ratio", sig=None)
    assert (r.stale, r.state, r.reason) == (True, "no_response", "title_ratio")


def test_broken_alert_resends_when_cap_changes():
    first = _broken(changed_h=49)
    prev = _prev_of(first, _T0)
    moved = _broken(changed_h=52, cap=50.0, now=_T0 + timedelta(hours=3))
    assert len(broken_alert_split([moved], prev, _T0 + timedelta(hours=3))[0]) == 1


def test_broken_alert_ignores_non_broken_and_holds_without_watermark():
    quiet = _rec(); quiet.state = "quiet"
    nowm = _broken(miss=2, sid="new_source"); nowm.age_hours = None
    send, hold = broken_alert_split([quiet, nowm], _prev_of(nowm, _T0), _T0)
    assert send == [] and hold[0].source_id == "new_source" and hold[0].age_hours == 0.0


# ── fmkorea 430 차단 (스펙 2026-10-02 §8 · 2026-10-03 개정) ──────────────────

def test_responded_fmkorea_all_430_is_blocked_not_search_failed():
    f = {"keywords": 5, "searched": 0, "listed": 0, "codes": {"430": 5}}
    assert responded("fmkorea", f, False) == (False, "blocked")
    # 코드가 섞이거나 없으면 차단이 아니라 검색 실패다 — 사람이 볼 일이 있다
    assert responded("fmkorea", dict(f, codes={"430": 4, "error": 1}), False) == (False, "search_failed")
    assert responded("fmkorea", dict(f, codes={}), False) == (False, "search_failed")


def _judge_fm(prev, reason="blocked", ok=False, runs=8, now=_T0):
    r = _rec("fmkorea", thr=24.0)
    evaluate_states([r], {"fmkorea": (ok, reason)}, {"fmkorea": "s1" if ok else None},
                    48.0, {"fmkorea": prev} if prev else {}, now, blocked_runs={"fmkorea": runs})
    return r


def _prev_fm(miss, block, changed_h=3.0):
    return {"state": "no_response", "miss_streak": miss, "block_streak": block, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=changed_h), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}


def test_blocked_seven_in_a_row_is_still_no_response():
    r = _judge_fm(_prev_fm(6, 6))
    assert (r.state, r.reason, r.miss_streak, r.block_streak) == ("no_response", "blocked", 7, 7)


def test_blocked_eight_in_a_row_breaks():
    r = _judge_fm(_prev_fm(7, 7))
    assert (r.state, r.reason, r.miss_streak, r.block_streak) == ("broken", "blocked", 8, 8)


def test_other_miss_after_blocks_uses_the_two_run_rule():
    r = _judge_fm(_prev_fm(3, 3), reason="error")
    assert (r.state, r.reason, r.miss_streak, r.block_streak) == ("broken", "error", 4, 0)


def test_block_after_other_miss_is_mixed_and_breaks_at_two():
    r = _judge_fm(_prev_fm(1, 0))
    assert (r.state, r.miss_streak, r.block_streak) == ("broken", 2, 1)


def test_one_response_resets_the_block_streak():
    r = _judge_fm(_prev_fm(7, 7), reason="", ok=True)
    assert (r.state, r.miss_streak, r.block_streak) == ("ok", 0, 0)


def test_source_without_blocked_runs_setting_breaks_at_two_even_when_blocked():
    r = _rec("fmkorea", thr=24.0)
    evaluate_states([r], {"fmkorea": (False, "blocked")}, {"fmkorea": None}, 48.0,
                    {"fmkorea": _prev_fm(1, 1)}, _T0)
    assert (r.state, r.block_streak) == ("broken", 2)


def test_rows_before_block_column_carry_their_misses_into_the_block_streak():
    # 칼럼이 생기기 전 무응답은 이번과 같은 차단으로 이어 센다 — 228회차에서 fmkorea
    # 무응답 사유는 430 뿐이었고, 섞임으로 보면 배포 첫 회차에 알림이 나간다.
    r = _judge_fm(_prev_fm(2, None))
    assert (r.state, r.miss_streak, r.block_streak) == ("no_response", 3, 3)


def _broken_fm(miss, block, now=_T0):
    r = _rec("fmkorea", thr=24.0)
    r.state, r.miss_streak, r.block_streak, r.cap_hours = "broken", miss, block, 48.0
    r.list_changed_at = now - timedelta(hours=3)
    r.reason = "blocked" if block == miss else "error"
    return r


def _prev_fm_of(r, at):
    return {r.source_id: {"state": r.state, "miss_streak": r.miss_streak,
                          "block_streak": r.block_streak, "list_sig": None,
                          "list_changed_at": r.list_changed_at, "cap_hours": r.cap_hours,
                          "checked_at": at}}


def test_blocked_alert_sends_at_eight_holds_then_realerts_after_48_hours():
    first = _broken_fm(8, 8)
    assert len(broken_alert_split([first], {}, _T0, blocked_runs={"fmkorea": 8})[0]) == 1
    prev = _prev_fm_of(first, _T0)
    later = _broken_fm(23, 23, now=_T0 + timedelta(hours=45))     # 8 + 15 → 같은 구간
    assert broken_alert_split([later], prev, _T0 + timedelta(hours=45),
                              blocked_runs={"fmkorea": 8})[0] == []
    again = _broken_fm(24, 24, now=_T0 + timedelta(hours=48))     # 8 + 16 → 다음 구간
    assert len(broken_alert_split([again], prev, _T0 + timedelta(hours=48),
                                  blocked_runs={"fmkorea": 8})[0]) == 1


def test_blocked_alert_resends_when_block_turns_into_other_miss():
    first = _broken_fm(8, 8)
    prev = _prev_fm_of(first, _T0)
    now_err = _broken_fm(9, 0, now=_T0 + timedelta(hours=3))
    assert len(broken_alert_split([now_err], prev, _T0 + timedelta(hours=3),
                                  blocked_runs={"fmkorea": 8})[0]) == 1


def test_new_source_without_previous_row_starts_block_streak_at_one():
    r = _judge_fm(None)
    assert (r.state, r.miss_streak, r.block_streak) == ("no_response", 1, 1)


def test_block_below_threshold_with_list_unchanged_alerts_as_list_kind():
    r = _judge_fm(_prev_fm(4, 4, changed_h=50.0))
    assert (r.state, r.reason, r.block_streak) == ("broken", "list_unchanged", 5)
    send, _ = broken_alert_split([r], {}, _T0, blocked_runs={"fmkorea": 8})
    assert send == [r]
    # 같은 상태가 이어져도 list 종류로 보아 같은 구간이면 보류한다
    prev = _prev_fm_of(r, _T0)
    nxt = _judge_fm(prev["fmkorea"] | {"state": "broken"}, now=_T0 + timedelta(hours=3))
    assert broken_alert_split([nxt], prev, _T0 + timedelta(hours=3),
                              blocked_runs={"fmkorea": 8})[0] == []


def test_pre_column_broken_row_resends_once_when_block_kind_takes_over():
    old = {"state": "broken", "miss_streak": 8, "block_streak": None, "list_sig": None,
           "list_changed_at": _T0 - timedelta(hours=3), "cap_hours": 48.0,
           "checked_at": _T0 - timedelta(hours=3)}
    now = _broken_fm(9, 9)
    assert len(broken_alert_split([now], {"fmkorea": old}, _T0,
                                  blocked_runs={"fmkorea": 8})[0]) == 1


# ── 소스별 「목록 그대로」 상한 (스펙 2026-10-02 §9 · 2026-10-03 개정) ─────────

def test_per_source_cap_keeps_a_quiet_team_page_out_of_broken():
    prev = {"state": "quiet", "miss_streak": 0, "block_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=100), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    sky, gdn = _rec("skysports", age=200.0, thr=120.0), _rec("guardian", age=200.0, thr=192.0)
    evaluate_states([sky, gdn], {"skysports": (True, ""), "guardian": (True, "")},
                    {"skysports": "s1", "guardian": "s1"}, 48.0,
                    {"skysports": prev, "guardian": prev}, _T0, cap_overrides={"skysports": 288.0})
    assert (sky.state, sky.cap_hours) == ("quiet", 288.0)
    assert (gdn.state, gdn.reason, gdn.cap_hours) == ("broken", "list_unchanged", 48.0)


def test_per_source_cap_still_breaks_past_its_own_cap():
    prev = {"state": "quiet", "miss_streak": 0, "block_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=289), "cap_hours": 288.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _rec("skysports", age=300.0, thr=120.0)
    evaluate_states([r], {"skysports": (True, "")}, {"skysports": "s1"}, 48.0,
                    {"skysports": prev}, _T0, cap_overrides={"skysports": 288.0})
    assert (r.state, r.reason, r.cap_hours) == ("broken", "list_unchanged", 288.0)


def test_responded_rss_needs_entries_and_signature():
    ok = {"entries": 24, "deduped": 24, "passed": 5, "list_sig": "abc"}
    assert responded("rss", ok, errored=False) == (True, "")
    assert responded("rss", {**ok, "passed": 0}, errored=False) == (True, "")   # 키워드 0 은 조용함의 몫
    assert responded("rss", {"entries": 0, "deduped": 0, "passed": 0, "list_sig": ""},
                     errored=False) == (False, "no_entries")
    assert responded("rss", {**ok, "list_sig": ""}, errored=False) == (False, "no_record")
    assert responded("rss", ok, errored=True) == (False, "error")
    assert responded("rss", None, errored=False) == (False, "no_record")
