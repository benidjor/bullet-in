import logging
from datetime import datetime, timedelta, timezone
import pytest
from bullet_in import notify
from bullet_in.quality import Anomaly, SourceFreshness


def test_send_alert_warns_when_webhook_unset(monkeypatch, caplog):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    calls = []
    monkeypatch.setattr(notify.httpx, "post", lambda *a, **k: calls.append((a, k)))
    with caplog.at_level(logging.WARNING):
        notify.send_alert("제목", "설명", color=notify.COLOR_ANOMALY)
    assert calls == []
    assert "제목" in caplog.text


def test_send_alert_posts_embed_when_webhook_set(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    captured = {}

    class Resp:
        status_code = 204

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return Resp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    notify.send_alert("제목", "설명", color=0x123456,
                      fields=[{"name": "F", "value": "V", "inline": True}])
    assert captured["url"] == "https://discord.test/webhook"
    embed = captured["json"]["embeds"][0]
    assert embed["title"] == "제목"
    assert embed["description"] == "설명"
    assert embed["color"] == 0x123456
    assert embed["fields"] == [{"name": "F", "value": "V", "inline": True}]


def test_send_alert_swallows_post_error(monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")

    def boom(*a, **k):
        raise notify.httpx.HTTPError("network down")

    monkeypatch.setattr(notify.httpx, "post", boom)
    with caplog.at_level(logging.WARNING):
        notify.send_alert("제목", "설명", color=notify.COLOR_FAILURE)
    assert "제목" in caplog.text




def test_build_failure_alert_maps_context():
    from types import SimpleNamespace

    ti = SimpleNamespace(dag_id="bullet_in_daily", task_id="run_pipeline",
                         try_number=2, hostname="host.local", duration=12.0,
                         log_url="http://localhost:8080/log")
    ctx = {"task_instance": ti, "run_id": "manual__2026-07-13",
           "exception": ValueError("boom")}
    alert = notify.build_failure_alert(ctx)
    assert alert["color"] == notify.COLOR_FAILURE
    assert "run_pipeline" in alert["title"]
    names = {f["name"]: f["value"] for f in alert["fields"]}
    assert names["DAG / Task"] == "bullet_in_daily / run_pipeline"
    assert names["Try"] == "2"
    assert names["Duration"] == "12s"
    assert names["Host"] == "host.local"
    assert "열기" in names["로그"] and "http://localhost:8080/log" in names["로그"]
    assert "boom" in alert["description"]


def test_send_alert_swallows_non_httperror(monkeypatch, caplog):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")

    def boom(*a, **k):
        raise ValueError("unexpected")

    monkeypatch.setattr(notify.httpx, "post", boom)
    with caplog.at_level(logging.WARNING):
        notify.send_alert("제목", "설명", color=notify.COLOR_FAILURE)
    assert "제목" in caplog.text


_FRESH_SOURCES = {
    "x_afcstuff": {"display_name": "afcstuff (aggregator)", "adapter": "x_playwright"},
    "bbc_sport": {"display_name": "BBC Sport", "adapter": "html"},
    "new_source": {"adapter": "html"},
}


def _freshness_inputs():
    checked = datetime(2026, 7, 13, 6, 0, 0)
    records = [
        SourceFreshness("x_afcstuff", checked - timedelta(hours=61.4), 24.0, 61.4, True),
        SourceFreshness("bbc_sport", checked - timedelta(hours=10), 48.0, 10.0, False),
        SourceFreshness("new_source", None, 48.0, None, False)]
    return checked, records


def test_build_freshness_alert_title_overview_and_meta():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    assert alert["title"] == "🕰️ 신선도 경고 — 오래된 소스 1건"
    assert alert["description"] == "감시 3소스: stale 1 · 정상 1 · 워터마크 없음 1"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert alert["url"] == notify.RUNBOOK_FRESHNESS
    assert alert["timestamp"] == "2026-07-13T06:00:00+00:00"
    assert alert["footer"] == "bullet-in"


def test_build_freshness_alert_stale_field_detail():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    [field] = [f for f in alert["fields"] if f["name"].startswith("afcstuff")]
    assert field["name"] == "afcstuff (aggregator) (x_afcstuff)"
    assert field["inline"] is False
    assert "- ⏳ 61.4h 경과 (임계 24h)" in field["value"]
    epoch = int((checked - timedelta(hours=61.4))
                .replace(tzinfo=timezone.utc).timestamp())
    assert f"- 마지막 수집: <t:{epoch}:R> (<t:{epoch}:f>)" in field["value"]
    assert "- 원인 후보: X 쿠키 만료 · 핸들 변경" in field["value"]


def test_build_freshness_alert_common_fields():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    assert {"name": "기본 임계", "value": "전역 48h", "inline": True} in alert["fields"]
    assert {"name": "회차", "value": "run 3f2a9c12", "inline": True} in alert["fields"]
    assert len([f for f in alert["fields"] if f["inline"] is False]) == 1  # stale 1건만


def test_build_freshness_alert_fallbacks_unknown_adapter_no_display_name():
    checked = datetime(2026, 7, 13, 6, 0, 0)
    records = [SourceFreshness("mystery", checked - timedelta(hours=50), 48.0, 50.0, True)]
    alert = notify.build_freshness_alert(records, 48,
                                         sources={"mystery": {"adapter": "weird"}},
                                         run_id="rrrrrrrrrrrr", checked_at=checked)
    field = alert["fields"][0]
    assert field["name"] == "mystery"
    assert "원인 후보" not in field["value"]


class _Resp:
    status_code = 204


def _capture_post(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    return captured


def test_send_alert_maps_url_timestamp_footer(monkeypatch):
    captured = _capture_post(monkeypatch)
    notify.send_alert("제목", "설명", color=0x1, url="https://runbook.test",
                      timestamp="2026-07-13T06:29:00+00:00", footer="bullet-in")
    embed = captured["json"]["embeds"][0]
    assert embed["url"] == "https://runbook.test"
    assert embed["timestamp"] == "2026-07-13T06:29:00+00:00"
    assert embed["footer"] == {"text": "bullet-in"}


def test_send_alert_omits_optional_keys_by_default(monkeypatch):
    captured = _capture_post(monkeypatch)
    notify.send_alert("제목", "설명", color=0x1)
    embed = captured["json"]["embeds"][0]
    assert "url" not in embed
    assert "timestamp" not in embed
    assert "footer" not in embed


def test_discord_ts_renders_utc_epoch():
    dt = datetime(2026, 7, 13, 6, 0, 0)  # naive UTC
    assert notify._discord_ts(dt, "R") == "<t:1783922400:R>"
    assert notify._discord_ts(dt, "f") == "<t:1783922400:f>"


_HIST = [{"fmkorea": 14, "bbc": 9}, {"fmkorea": 13}, {"fmkorea": 15},
         {"fmkorea": 12, "bbc": 8}, {"fmkorea": 14}, {"fmkorea": 11}]  # 최신순


def test_build_anomaly_alert_drop_field_sequence_and_hint():
    anomalies = [Anomaly("fmkorea", 0, 14.0, "drop")]
    srcs = {"fmkorea": {"display_name": "fmkorea 축구 소식통", "adapter": "fmkorea"}}
    alert = notify.build_anomaly_alert(anomalies, 12, hist=_HIST, sources=srcs,
                                       run_id="3f2a9c12abcd")
    assert alert["title"] == "⚠️ 수집량 이상 — 1건 (드롭 1 · 스파이크 0)"
    assert alert["description"] == "최근 12회 대비 소스별 수집량 이상"
    assert alert["url"] == notify.RUNBOOK_ANOMALY
    field = alert["fields"][0]
    assert field["name"] == "fmkorea 축구 소식통 (fmkorea)"
    assert field["inline"] is False
    assert "- ▼ 0건 (평소 ~14)" in field["value"]
    assert "- 최근: 14 → 12 → 15 → 13 → 14 → (오늘) 0" in field["value"]
    assert "- 원인 후보: 검색 URL 변경 · 429 차단" in field["value"]
    assert alert["fields"][-1] == {"name": "회차",
                                   "value": "최근 12회 기준 · run 3f2a9c12",
                                   "inline": True}


def test_build_anomaly_alert_spike_hint_and_missing_hist_source():
    anomalies = [Anomaly("bbc", 30, 9.0, "spike"), Anomaly("ghost", 0, 5.0, "drop")]
    alert = notify.build_anomaly_alert(anomalies, 12, hist=[], sources={},
                                       run_id="rrrrrrrrrrrr")
    assert alert["title"] == "⚠️ 수집량 이상 — 2건 (드롭 1 · 스파이크 1)"
    spike_field, ghost_field = alert["fields"][0], alert["fields"][1]
    assert spike_field["name"] == "bbc"
    assert "- ▲ 30건 (평소 ~9)" in spike_field["value"]
    assert "- 원인 후보: 중복 유입 · 파싱 회귀 의심" in spike_field["value"]
    assert "최근:" not in ghost_field["value"]      # hist 에 없음 → 시퀀스 생략
    assert "원인 후보" not in ghost_field["value"]  # 미지 어댑터 드롭 → 힌트 생략


def test_build_anomaly_alert_sequence_counts_absent_rounds_as_zero():
    # 직전 회차에 이미 0건(키 부재)이던 소스 — 부재를 생략하면 추세가 미화된다
    hist = [{}, {"fmkorea": 14}, {"fmkorea": 14}, {"fmkorea": 14}, {"fmkorea": 14}]
    alert = notify.build_anomaly_alert([Anomaly("fmkorea", 0, 11.2, "drop")], 12,
                                       hist=hist, sources={}, run_id="rrrrrrrrrrrr")
    assert "- 최근: 14 → 14 → 14 → 14 → 0 → (오늘) 0" in alert["fields"][0]["value"]


def _stale_bbc():
    checked = datetime(2026, 7, 30, 6, 0, 0)
    records = [SourceFreshness("bbc_sport", checked - timedelta(hours=69), 48.0,
                               69.0, True)]
    return checked, records


def test_build_freshness_alert_zero_candidates_keeps_hint():
    # 후보 0건은 관측 사실만 적는다 — 원인 추정 (수집 끊김 의심) 은 스펙
    # 2026-08-07 §3.2 로 제거 (arsenal_official 오진 사례). 힌트 줄은 유지.
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    field = alert["fields"][0]
    assert "- 이번 회차 후보 0건" in field["value"]
    assert "수집 끊김 의심" not in field["value"]
    assert "- 원인 후보: 셀렉터 드리프트 · 사이트 개편" in field["value"]


def test_build_freshness_alert_candidates_present_omits_field():
    # 후보는 있으나 전부 기존 기사 = 경로 정상 — 조치 신호가 아니라 필드에서 뺀다
    # (2026-07-31 guardian 사례: 문구만 바꾸니 같은 알림이 하루 8회 반복됐다)
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={"bbc_sport": 4}, fetch_errors={})
    assert alert["title"] == "🕰️ 신선도 경고 — 오래된 소스 0건"
    assert "경로 정상 생략 1" in alert["description"]
    assert not [f for f in alert["fields"] if f["name"].startswith("BBC")]


def test_freshness_alert_targets_only_actionable():
    # 알림 발송 판단용 — 후보 0건 · fetch 오류만 대상, 경로 정상 stale 은 제외
    checked, records = _stale_bbc()
    assert notify.freshness_alert_targets(records, {"bbc_sport": 4}, {}) == []
    assert [b.source_id for b in
            notify.freshness_alert_targets(records, {}, {})] == ["bbc_sport"]
    assert [b.source_id for b in
            notify.freshness_alert_targets(records, {"bbc_sport": 4},
                                           {"bbc_sport": "HTTP 503"})] == ["bbc_sport"]


def test_freshness_alert_targets_legacy_returns_all_stale():
    # candidates 미전달 (종전 호출) — stale 전부가 대상
    checked, records = _freshness_inputs()
    assert [b.source_id for b in
            notify.freshness_alert_targets(records, None, None)] == ["x_afcstuff"]


def test_build_freshness_alert_fetch_error_shows_error_not_hint():
    # 회차 fetch 가 예외로 끝난 소스 — 실제 오류 문구가 원인이고 힌트는 추측이다
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={},
                                         fetch_errors={"bbc_sport": "HTTP 503"})
    field = alert["fields"][0]
    assert "- 이번 회차 fetch 오류: HTTP 503" in field["value"]
    assert "원인 후보" not in field["value"]
    assert "후보 0건" not in field["value"]  # 오류면 후보 수는 미지 — 0 으로 단정 금지


from bullet_in.notify import build_coverage_alert, COLOR_ANOMALY

def test_build_coverage_alert_embed_shape():
    kwargs = build_coverage_alert(
        ["no_men_tag"], {"candidates": 12, "men_tagged": 0, "accepted": 0},
        run_id="abcdef12-0000")
    assert kwargs["color"] == COLOR_ANOMALY
    assert "arsenal_official" in kwargs["title"]
    names = [f["name"] for f in kwargs["fields"]]
    assert "Men 태그 소멸" in names
    funnel = next(f for f in kwargs["fields"] if f["name"] == "퍼널")
    assert funnel["value"] == "후보 12 · Men 0 · accept 0"


from bullet_in.notify import build_candidate_alert


def test_build_candidate_alert_lists_each_candidate():
    cands = [{"full_name": "Nico Williams", "ko": "니코 윌리엄스", "stage": "rumour",
              "title": "Arsenal eye Williams", "url": "https://x.test/a", "player_id": 41}]
    alert = build_candidate_alert(cands, run_id="abcd1234-0000")
    assert "1명" in alert["title"]
    body = str(alert["fields"])
    assert "니코 윌리엄스" in body and "rumour" in body and "https://x.test/a" in body


def test_build_candidate_alert_caps_fields():
    cands = [{"full_name": f"P {i}", "ko": None, "stage": "rumour",
              "title": "t", "url": None, "player_id": i} for i in range(15)]
    alert = build_candidate_alert(cands, run_id="abcd1234-0000")
    assert "15명" in alert["title"]
    assert len(alert["fields"]) <= 12        # 후보 10 + 넘침 요약 + 회차


def test_cliff_alert_shows_transition_and_recent_sequence():
    embed = notify.build_cliff_alert(
        ["fmkorea"],
        history=[{"fmkorea": 10, "goal": 13}, {"fmkorea": 10}, {"fmkorea": 0},
                 {"fmkorea": 10}],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통",
                             "adapter": "fmkorea"}},
        failure_codes={"fmkorea": {430: 4}},
        success_rate=1.0,
        run_id="3259230a-1111-2222-3333-444444444444")
    assert "수집 0건" in embed["title"]
    body = embed["fields"][0]["value"]
    assert "직전 회차 10건 → 이번 회차 0건" in body
    assert "10 → 0 → 10 → 10 → 0 (이번)" in body
    assert "검색 실패 4건 — HTTP 430 4건" in body
    assert "success_rate 1" in body


def test_cliff_alert_omits_failure_line_when_adapter_has_no_codes():
    embed = notify.build_cliff_alert(
        ["guardian"],
        history=[{"guardian": 8}],
        sources={"guardian": {"display_name": "The Guardian", "adapter": "rss"}},
        failure_codes={},
        success_rate=1.0,
        run_id="abcdef01")
    body = embed["fields"][0]["value"]
    assert "검색 실패" not in body
    assert "직전 회차 8건 → 이번 회차 0건" in body


def test_cliff_alert_has_no_cause_speculation():
    """원인 추정 문구 금지 (스펙 §5.3) — 어댑터 힌트가 새어들면 안 된다."""
    embed = notify.build_cliff_alert(
        ["fmkorea"],
        history=[{"fmkorea": 10}],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통",
                             "adapter": "fmkorea"}},
        failure_codes={"fmkorea": {430: 4}},
        success_rate=1.0,
        run_id="abcdef01")
    rendered = embed["description"] + "".join(f["value"] for f in embed["fields"])
    assert "원인 후보" not in rendered
    assert "의심" not in rendered
    for hint in notify.ADAPTER_HINTS.values():
        assert hint not in rendered


def test_watchlist_blackout_alert_reports_counts_and_codes():
    embed = notify.build_watchlist_blackout_alert(
        searched=10,
        failure_codes={430: 10},
        last_contact=datetime(2026, 8, 3, 10, 34))
    assert "전원" in embed["title"]
    body = "".join(f["value"] for f in embed["fields"])
    assert "검색 10명" in body
    assert "검색 실패 10건 — HTTP 430 10건" in body
    assert "다시 시도" in embed["description"]


def test_watchlist_blackout_alert_without_last_contact():
    embed = notify.build_watchlist_blackout_alert(
        searched=10, failure_codes={"error": 10}, last_contact=None)
    body = "".join(f["value"] for f in embed["fields"])
    assert "연결 오류 10건" in body
    assert "마지막" not in body


def test_webhook_url_redacted_in_httpx_log(caplog):
    """웹훅 주소는 그 자체가 인증 수단 — httpx INFO 로그에 토큰이 남으면 안 된다."""
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info('HTTP Request: POST https://discord.com/api/webhooks/1526/TOKENSECRET '
                    '"HTTP/1.1 204 No Content"')
    assert "TOKENSECRET" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_non_webhook_httpx_log_untouched(caplog):
    """다른 요청 로그는 그대로 남는다 — 수집 진단에 쓰이는 정보다."""
    logger = logging.getLogger("httpx")
    with caplog.at_level(logging.INFO, logger="httpx"):
        logger.info('HTTP Request: GET https://www.fmkorea.com/10167419258 "HTTP/1.1 200 OK"')
    assert "10167419258" in caplog.text
    assert "[REDACTED]" not in caplog.text


def test_build_filter_miss_alert_embed_shape():
    # 관측 사실만 싣는다 — 원인 추정 · 내부 용어 금지 (스펙 2026-08-07 §3.3)
    suspects = [{"title": "Christian Norgaard joins Everton",
                 "url": "https://www.arsenal.com/news/x-a7fZT9g6dECY",
                 "published": "2026-08-05T21:09:44.542Z",
                 "taxonomies": ["Men", "News", "Main"]}]
    alert = notify.build_filter_miss_alert(suspects, run_id="3f2a9c12abcd")
    assert "1건" in alert["title"]
    f = alert["fields"][0]
    assert f["name"] == "Christian Norgaard joins Everton"
    assert "- 태그: Men · News · Main" in f["value"]
    assert "[기사](https://www.arsenal.com/news/x-a7fZT9g6dECY)" in f["value"]
    assert "의심" not in alert["description"]   # 원인 추정 어휘 금지
    assert alert["fields"][-1]["value"] == "run 3f2a9c12"


def test_cliff_alert_reports_cycle_outcome_without_claiming_normal():
    """success_rate 가 1 미만인데 '정상 종료' 라고 쓰면 숫자와 말이 어긋난다."""
    embed = notify.build_cliff_alert(
        ["fmkorea"], history=[{"fmkorea": 10}],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통"}},
        failure_codes={}, success_rate=0.889, run_id="abcdef01")
    body = embed["fields"][0]["value"]
    assert "success_rate 0.889" in body
    assert "정상 종료" not in body
