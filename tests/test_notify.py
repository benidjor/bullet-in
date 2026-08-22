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


def _stale_of(records):
    return [r for r in records if r.stale]


def test_build_freshness_alert_title_overview_and_meta():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, targets=_stale_of(records),
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    assert alert["title"] == "🕰️ 신선도 경고 — afcstuff (aggregator) 2.6일째 조용합니다"
    assert alert["description"] == "감시 3소스: stale 1 · 정상 1 · 워터마크 없음 1"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert alert["url"] == notify.RUNBOOK_FRESHNESS
    assert alert["timestamp"] == "2026-07-13T06:00:00+00:00"
    assert alert["footer"] == "bullet-in"


def test_build_freshness_alert_stale_field_detail():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, targets=_stale_of(records),
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    age = _field(alert, "얼마나 오래됐나")
    assert "- ⏳ **61.4h** 경과 (임계 24h)" in age
    epoch = int((checked - timedelta(hours=61.4))
                .replace(tzinfo=timezone.utc).timestamp())
    assert f"- 마지막 수집: <t:{epoch}:R> (<t:{epoch}:f>)" in age
    assert "- 원인 후보: X 쿠키 만료 · 핸들 변경" \
        in _field(alert, "수집 경로는 살아 있나")


def test_build_freshness_alert_common_fields():
    checked, records = _freshness_inputs()
    alert = notify.build_freshness_alert(records, 48, targets=_stale_of(records),
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked)
    assert {"name": "기본 임계", "value": "전역 48h", "inline": True} in alert["fields"]
    assert {"name": "회차", "value": "run 3f2a9c12", "inline": True} in alert["fields"]
    assert [f["name"] for f in alert["fields"] if f["inline"] is False] \
        == ["얼마나 오래됐나", "수집 경로는 살아 있나", "다음 알림"]


def test_build_freshness_alert_fallbacks_unknown_adapter_no_display_name():
    checked = datetime(2026, 7, 13, 6, 0, 0)
    records = [SourceFreshness("mystery", checked - timedelta(hours=50), 48.0, 50.0, True)]
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources={"mystery": {"adapter": "weird"}},
                                         run_id="rrrrrrrrrrrr", checked_at=checked)
    assert "원인 후보" not in str(alert["fields"])
    # 힌트도 후보 계수도 없으면 경로 구획 자체가 안 생긴다
    assert "수집 경로는 살아 있나" not in [f["name"] for f in alert["fields"]]


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


def test_build_anomaly_alert_omits_sequence_for_source_missing_from_history():
    anomalies = [Anomaly("bbc", 30, 9.0, "spike"), Anomaly("ghost", 0, 5.0, "drop")]
    alert = notify.build_anomaly_alert(anomalies, 12, hist=[], sources={},
                                       run_id="rrrrrrrrrrrr")
    spike_field, ghost_field = alert["fields"][0], alert["fields"][1]
    assert spike_field["name"] == "bbc"
    assert "- ▲ 30건 (평소 ~9)" in spike_field["value"]
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
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    path = _field(alert, "수집 경로는 살아 있나")
    assert "- 이번 회차 후보 0건" in path
    assert "수집 끊김 의심" not in path
    assert "- 원인 후보: 셀렉터 드리프트 · 사이트 개편" in path


def test_build_freshness_alert_candidates_present_is_diagnosis_not_suppression():
    # 후보가 있어도 알린다 — 그 계수는 발송 조건이 아니라 진단 재료다 (스펙 §4.1).
    # 종전에는 이 조건이 발송을 막아 x_ornstein 이 13일째 죽어도 침묵했다.
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={"bbc_sport": 4}, fetch_errors={})
    assert alert["title"] == "🕰️ 신선도 경고 — BBC Sport 2.9일째 조용합니다"
    path = _field(alert, "수집 경로는 살아 있나")
    # 판정이 원본 수집으로 옮겨간 뒤로는 stale = 후보가 전부 이미 받은 글이라는 뜻이다.
    # 옛 문안 ("새 글이 없습니다") 은 저장 기준일 때 거짓이었다 (설계 2026-08-20 §3.5).
    assert "- 이번 회차 후보 **4건** — 전부 이미 받은 글입니다" in path
    assert "원인 후보" not in path   # 후보가 있으면 셀렉터 힌트는 근거가 없다


def test_build_freshness_alert_absorption_line_only_when_storage_lags():
    # 원본보다 기사 표가 뒤처진 소스에만 흡수 한 줄이 붙는다 (설계 2026-08-20 §3.5)
    checked, records = _stale_bbc()
    records[0].stored_fetched_at = checked - timedelta(hours=500)
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    epoch = int((checked - timedelta(hours=500))
                .replace(tzinfo=timezone.utc).timestamp())
    assert f"- 마지막 저장: <t:{epoch}:f> (그 뒤로는 다른 행으로 흡수)" \
        in _field(alert, "얼마나 오래됐나")


def test_build_freshness_alert_no_absorption_line_when_signals_agree():
    # 두 값이 같은 소스 (실측상 일곱 중 여섯) 에는 안 붙인다
    checked, records = _stale_bbc()
    records[0].stored_fetched_at = records[0].last_fetched_at
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    assert "마지막 저장" not in _field(alert, "얼마나 오래됐나")


def test_build_freshness_alert_counts_held_sources_in_description():
    # 재알림 간격이 안 찬 stale 은 필드에서 빠지고 조망 줄에 계수로만 남는다
    checked, records = _stale_bbc()
    records.append(SourceFreshness("x_afcstuff", checked - timedelta(hours=61.4),
                                   24.0, 61.4, True))
    alert = notify.build_freshness_alert(records, 48, targets=records[:1],
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    assert [f["name"] for f in alert["fields"] if f["inline"] is False] \
        == ["얼마나 오래됐나", "수집 경로는 살아 있나", "다음 알림"]
    assert "재알림 대기 1" in alert["description"]


def test_build_freshness_alert_states_realert_interval():
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={}, fetch_errors={})
    assert "- 48시간 더 지나면 다시 알립니다" in _field(alert, "다음 알림")


def test_build_freshness_alert_fetch_error_shows_error_not_hint():
    # 회차 fetch 가 예외로 끝난 소스 — 실제 오류 문구가 원인이고 힌트는 추측이다
    checked, records = _stale_bbc()
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_FRESH_SOURCES,
                                         run_id="3f2a9c12abcd", checked_at=checked,
                                         candidates={},
                                         fetch_errors={"bbc_sport": "HTTP 503"})
    path = _field(alert, "수집 경로는 살아 있나")
    assert "- 이번 회차 fetch 오류: HTTP 503" in path
    assert "원인 후보" not in path
    assert "후보 0건" not in path  # 오류면 후보 수는 미지 — 0 으로 단정 금지


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


def test_build_candidate_alert_shows_duplicate_suspects():
    # 자동 병합을 하지 않으므로 사람이 판단할 근거를 카드 안에 한 줄로 붙인다
    cands = [{"full_name": "Illan Meslier", "ko": "멜리에", "stage": "agreed",
              "title": "Arsenal sign keeper", "url": None, "player_id": 52,
              "dup_suspects": [{"id": 7, "full_name": "Ilan Meslier"}]}]
    alert = build_candidate_alert(cands, run_id="abcd1234-0000")
    body = str(alert["fields"])
    assert "중복 의심" in body and "Ilan Meslier" in body and "id 7" in body


def test_build_candidate_alert_omits_duplicate_line_when_none():
    cands = [{"full_name": "Nico Williams", "ko": "니코 윌리엄스", "stage": "rumour",
              "title": "t", "url": None, "player_id": 41, "dup_suspects": []}]
    assert "중복 의심" not in str(build_candidate_alert(
        cands, run_id="abcd1234-0000")["fields"])


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
    assert "- 찾은 글 추이: 10 → 0 → 10 → 10 → **0 (이번)**" \
        in _field(embed, "평소와 비교")
    assert "검색 실패 **4건** — `HTTP 430` 4건" in _field(embed, "무슨 일이 있었나")
    assert "success_rate 1" in _field(embed, "지금 어떤 상태인가")


def test_cliff_alert_omits_failure_line_when_adapter_has_no_codes():
    embed = notify.build_cliff_alert(
        ["guardian"],
        history=[{"guardian": 8}],
        sources={"guardian": {"display_name": "The Guardian", "adapter": "rss"}},
        failure_codes={},
        success_rate=1.0,
        run_id="abcdef01")
    assert "검색 실패" not in str(embed["fields"])
    assert "- 찾은 글 추이: 8 → **0 (이번)**" in _field(embed, "평소와 비교")


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
    assert "검색 실패 **10건** — `HTTP 430` 10건" in body
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
    body = _field(embed, "지금 어떤 상태인가")
    assert "success_rate 0.889" in body
    assert "정상 종료" not in body


def test_build_roster_staleness_alert_embed_shape():
    cases = [{"player_id": 28, "ko_name": "기마랑이스", "transfer_status": "in_link",
              "kind": "finish", "new_stages": {"agreed": 2, "medical": 1},
              "recent_total": 9}]
    embed = notify.build_roster_staleness_alert(cases, run_id="abcdef123456")
    assert "1명" in embed["title"]
    field = embed["fields"][0]
    assert field["name"] == "기마랑이스"
    assert "영입 링크" in field["value"]
    assert "합의 2건" in field["value"] and "메디컬 1건" in field["value"]
    assert "9건" in field["value"]
    assert embed["fields"][-1]["value"] == "run abcdef12"
    assert embed["url"] == notify.RUNBOOK_ROSTER


def test_build_roster_staleness_alert_has_no_cause_speculation():
    # 문구 원칙 (수집 차단 알림과 동일) — 원인 추정 단어를 싣지 않는다
    cases = [{"player_id": 1, "ko_name": "가", "transfer_status": "none",
              "kind": "start", "new_stages": {"interest": 1}, "recent_total": 3}]
    embed = notify.build_roster_staleness_alert(cases, run_id="run12345678")
    text = embed["title"] + embed["description"] + "".join(
        f["value"] for f in embed["fields"])
    for banned in ("차단", "원인", "실패", "오류"):
        assert banned not in text


# ── 디스코드 채널 3분리 (스펙 2026-08-14 §7) ─────────────────────────────────

def _capture_channel_post(monkeypatch) -> dict:
    captured: dict = {}

    class Resp:
        status_code = 204

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return Resp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    return captured


def test_send_alert_posts_to_channel_webhook(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/default")
    monkeypatch.setenv("DISCORD_WEBHOOK_INCIDENT", "https://discord.test/incident")
    captured = _capture_channel_post(monkeypatch)
    notify.send_alert("제목", "설명", color=0x1, channel=notify.CHANNEL_INCIDENT)
    assert captured["url"] == "https://discord.test/incident"


def test_send_alert_falls_back_to_default_webhook_when_channel_unset(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/default")
    monkeypatch.delenv("DISCORD_WEBHOOK_TREND", raising=False)
    captured = _capture_channel_post(monkeypatch)
    notify.send_alert("제목", "설명", color=0x1, channel=notify.CHANNEL_TREND)
    assert captured["url"] == "https://discord.test/default"


def test_send_alert_keeps_channel_out_of_embed(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/default")
    captured = _capture_channel_post(monkeypatch)
    notify.send_alert("제목", "설명", color=0x1, channel=notify.CHANNEL_REVIEW)
    assert "channel" not in captured["json"]["embeds"][0]


def _sample_payloads() -> dict:
    """9종 알림 payload 를 한 번에 만든다 — 채널 배정 확인용 최소 입력."""
    from types import SimpleNamespace
    now = datetime(2026, 8, 22, 6, 0, 0)
    ti = SimpleNamespace(dag_id="d", task_id="t", try_number=1, hostname="h",
                         duration=1.0, log_url="http://log")
    records = [SourceFreshness("x_ornstein", now - timedelta(hours=291), 120.0,
                               291.0, True)]
    return {
        "failure": notify.build_failure_alert(
            {"task_instance": ti, "run_id": "r", "exception": ValueError("boom")}),
        "cliff": notify.build_cliff_alert(
            ["fmkorea"], history=[{"fmkorea": 12}], sources={},
            failure_codes={}, success_rate=1.0, run_id="run12345678"),
        "blackout": notify.build_watchlist_blackout_alert(
            searched=5, failure_codes={430: 5}, last_contact=now),
        "candidate": notify.build_candidate_alert(
            [{"ko": "사카", "full_name": "Bukayo Saka", "stage": "rumour"}],
            run_id="run12345678"),
        "filter_miss": notify.build_filter_miss_alert(
            [{"title": "t", "taxonomies": [], "url": "http://a"}],
            run_id="run12345678"),
        "roster": notify.build_roster_staleness_alert(
            [{"ko_name": "사카", "transfer_status": "none",
              "new_stages": {"rumour": 1}, "recent_total": 3}],
            run_id="run12345678"),
        "anomaly": notify.build_anomaly_alert(
            [Anomaly("fmkorea", 0, 11.2, "drop")], 12, hist=[{"fmkorea": 11}],
            sources={}, run_id="run12345678"),
        "freshness": notify.build_freshness_alert(
            records, 48, targets=records, sources={}, run_id="run12345678",
            checked_at=now),
        "coverage": notify.build_coverage_alert(
            ["no_candidates"], {"candidates": 0}, run_id="run12345678"),
    }


def test_incident_alerts_carry_incident_channel():
    p = _sample_payloads()
    assert [p[k]["channel"] for k in ("failure", "cliff", "blackout")] \
        == [notify.CHANNEL_INCIDENT] * 3


def test_review_alerts_carry_review_channel():
    p = _sample_payloads()
    assert [p[k]["channel"] for k in ("candidate", "filter_miss", "roster")] \
        == [notify.CHANNEL_REVIEW] * 3


def test_trend_alerts_carry_trend_channel():
    p = _sample_payloads()
    assert [p[k]["channel"] for k in ("anomaly", "freshness", "coverage")] \
        == [notify.CHANNEL_TREND] * 3


# ── 문안 개편 · 신선도 (스펙 2026-08-14 §6.1 · §6.3) ──────────────────────────

_ORNSTEIN = {"x_ornstein": {"display_name": "David Ornstein (X)",
                            "adapter": "x_playwright"},
             "skysports": {"display_name": "Sky Sports", "adapter": "html"}}


def _ornstein_records(checked):
    return [SourceFreshness("x_ornstein", checked - timedelta(hours=291), 120.0,
                            291.0, True),
            SourceFreshness("skysports", checked - timedelta(hours=200), 96.0,
                            200.0, True)]


def test_freshness_title_names_the_source_and_days_silent():
    checked = datetime(2026, 8, 22, 6, 0, 0)
    records = _ornstein_records(checked)
    alert = notify.build_freshness_alert(records, 48, targets=records[:1],
                                         sources=_ORNSTEIN, run_id="run12345678",
                                         checked_at=checked)
    assert alert["title"] == "🕰️ 신선도 경고 — David Ornstein (X) 12.1일째 조용합니다"


def test_freshness_title_counts_the_rest_when_several_sources():
    checked = datetime(2026, 8, 22, 6, 0, 0)
    records = _ornstein_records(checked)
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_ORNSTEIN, run_id="run12345678",
                                         checked_at=checked)
    assert alert["title"] == "🕰️ 신선도 경고 — David Ornstein (X) 외 1개 소스가 오래됐습니다"


def _field(alert, name):
    return next(f["value"] for f in alert["fields"] if f["name"] == name)


def test_freshness_field_groups_lines_into_sections():
    checked = datetime(2026, 8, 22, 6, 0, 0)
    records = _ornstein_records(checked)[:1]
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources=_ORNSTEIN, run_id="run12345678",
                                         checked_at=checked, candidates={"x_ornstein": 5})
    assert [f["name"] for f in alert["fields"] if f["inline"] is False] \
        == ["얼마나 오래됐나", "수집 경로는 살아 있나", "다음 알림"]


def test_freshness_omits_the_path_section_when_nothing_observed():
    checked = datetime(2026, 8, 22, 6, 0, 0)
    records = [SourceFreshness("new_source", checked - timedelta(hours=99), 48.0,
                               99.0, True)]
    alert = notify.build_freshness_alert(records, 48, targets=records,
                                         sources={"new_source": {}},
                                         run_id="run12345678", checked_at=checked)
    assert "수집 경로는 살아 있나" not in [f["name"] for f in alert["fields"]]


# ── 문안 개편 · 수집량 이상 (스펙 2026-08-14 §6.1 · §6.4) ────────────────────

_FM = {"fmkorea": {"display_name": "fmkorea 축구 소식통", "adapter": "fmkorea"},
       "bbc_sport": {"display_name": "BBC Sport", "adapter": "html"}}


def test_anomaly_title_names_the_source_with_its_numbers():
    alert = notify.build_anomaly_alert([Anomaly("fmkorea", 0, 14.0, "drop")], 12,
                                       hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd")
    assert alert["title"] == "⚠️ 수집량 드롭 — fmkorea 축구 소식통 0건 (평소 ~14)"


def test_anomaly_title_counts_the_rest_when_several_sources():
    anomalies = [Anomaly("fmkorea", 0, 14.0, "drop"),
                 Anomaly("bbc_sport", 30, 9.0, "spike")]
    alert = notify.build_anomaly_alert(anomalies, 12, hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd")
    assert alert["title"] == \
        "⚠️ 수집량 이상 — fmkorea 축구 소식통 외 1개 소스 (드롭 1 · 스파이크 1)"


def test_anomaly_description_says_what_the_count_means():
    alert = notify.build_anomaly_alert([Anomaly("fmkorea", 0, 14.0, "drop")], 12,
                                       hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd")
    assert alert["description"] == (
        "최근 12회 대비 소스별 수집량 이상 — 「수집량」 은 중복 · 필터를 지나 "
        "이번 회차에 새로 담은 글 수입니다")


def test_anomaly_drop_keeps_adapter_hint_when_no_candidates():
    # 후보 0건 = 발견 자체가 끊겼다 — 이때만 셀렉터 · 차단 힌트에 근거가 있다
    alert = notify.build_anomaly_alert([Anomaly("fmkorea", 0, 14.0, "drop")], 12,
                                       hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd", candidates={})
    value = alert["fields"][0]["value"]
    assert "- 이번 회차 후보 0건 중 새로 담은 글 0건" in value
    assert "- 원인 후보: 검색 URL 변경 · 429 차단" in value


def test_anomaly_drop_omits_adapter_hint_when_candidates_found():
    # 후보가 있는데 적재가 줄었다 = 발견은 살아 있고 중복 · 필터에서 걸린 것이다
    alert = notify.build_anomaly_alert([Anomaly("fmkorea", 2, 14.0, "drop")], 12,
                                       hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd",
                                       candidates={"fmkorea": 12})
    value = alert["fields"][0]["value"]
    assert "- 이번 회차 후보 12건 중 새로 담은 글 2건" in value
    assert "원인 후보" not in value


def test_anomaly_spike_states_counts_instead_of_guessing_cause():
    # 근거 없는 「중복 유입 · 파싱 회귀 의심」 을 걷어내고 관측 사실만 적는다
    alert = notify.build_anomaly_alert([Anomaly("bbc_sport", 30, 9.0, "spike")], 12,
                                       hist=_HIST, sources=_FM,
                                       run_id="3f2a9c12abcd",
                                       candidates={"bbc_sport": 33})
    value = alert["fields"][0]["value"]
    assert "- 이번 회차 후보 33건 중 새로 담은 글 30건" in value
    assert "원인 후보" not in value
    assert not hasattr(notify, "SPIKE_HINT")


# ── 문안 개편 · 후보 절벽 (스펙 2026-08-14 §6.1 · §6.2) ──────────────────────

_FM_CFG = {"fmkorea": {"display_name": "fmkorea 축구 소식통", "adapter": "fmkorea",
                       "config": {"search_keywords": [
                           {"keyword": "아스날", "target": "title"},
                           {"keyword": '"de roche"', "target": "title_content"}]}},
           "guardian": {"display_name": "The Guardian", "adapter": "html"}}


def _fm_cliff(**kw):
    args = {"history": [{"fmkorea": 12}, {"fmkorea": 12}], "sources": _FM_CFG,
            "failure_codes": {"fmkorea": {430: 2}}, "success_rate": 1.0,
            "run_id": "3f2a9c12abcd"}
    args.update(kw)
    return notify.build_cliff_alert(["fmkorea"], **args)


def test_cliff_title_names_the_source_and_the_failed_searches():
    assert _fm_cliff()["title"] == \
        "🚨 fmkorea 축구 소식통 수집 0건 — 검색 2건이 전부 실패했습니다"


def test_cliff_title_states_only_the_zero_when_no_failure_codes():
    alert = notify.build_cliff_alert(
        ["guardian"], history=[{"guardian": 8}], sources=_FM_CFG,
        failure_codes={}, success_rate=1.0, run_id="3f2a9c12abcd")
    assert alert["title"] == "🚨 The Guardian 수집 0건"


def test_cliff_title_counts_the_rest_when_several_sources():
    alert = notify.build_cliff_alert(
        ["fmkorea", "guardian"], history=[{"fmkorea": 12, "guardian": 8}],
        sources=_FM_CFG, failure_codes={}, success_rate=1.0,
        run_id="3f2a9c12abcd")
    assert alert["title"] == "🚨 이번 회차 수집 0건 — fmkorea 축구 소식통 외 1개 소스"


def test_cliff_lists_the_search_keywords_from_config():
    value = _field(_fm_cliff(), "무슨 일이 있었나")
    assert "- 검색 키워드 **2개가 전부 실패**했습니다" in value
    assert "  - `아스날` — 제목" in value
    assert '  - `"de roche"` — 제목·본문' in value


def test_cliff_names_the_bot_block_behind_the_response_code():
    assert "- 검색 실패 **2건** — `HTTP 430` 2건 *(자동 수집 차단 응답)*" \
        in _field(_fm_cliff(), "무슨 일이 있었나")


def test_cliff_says_what_the_found_count_counts():
    value = _field(_fm_cliff(), "평소와 비교")
    assert "- 찾은 글 추이: 12 → 12 → **0 (이번)**" in value
    assert "- *「찾은 글」 은 중복을 포함한 발견 결과 수이고 저장된 글 수가 아닙니다*" in value


def test_cliff_explains_why_no_failure_alert_was_sent():
    value = _field(_fm_cliff(), "지금 어떤 상태인가")
    assert "- 회차는 실패로 끝나지 않았습니다 (`success_rate 1`)" in value
    assert "- *어댑터가 예외를 던지지 않아 실패 알림이 따로 가지 않았습니다*" in value


def test_cliff_advises_waiting_only_when_the_block_code_is_present():
    with_block = _field(_fm_cliff(), "무엇을 하나")
    without = _field(_fm_cliff(failure_codes={"fmkorea": {503: 2}}), "무엇을 하나")
    assert "- 차단은 보통 저절로 풀립니다 — 지금은 조치하지 않습니다" in with_block
    assert "차단은 보통 저절로 풀립니다" not in without
    assert "- 회차가 계속 0이면 런북 (제목 클릭) 의 절차를 따릅니다" in without


def test_cliff_omits_the_what_happened_section_without_keywords_or_codes():
    alert = notify.build_cliff_alert(
        ["guardian"], history=[{"guardian": 8}], sources=_FM_CFG,
        failure_codes={}, success_rate=1.0, run_id="3f2a9c12abcd")
    assert [f["name"] for f in alert["fields"]][0] == "평소와 비교"


# ── 디스코드 렌더 (실물 화면에서 줄이 붙어 버린 자리) ────────────────────────

def test_single_source_puts_each_section_in_its_own_field():
    # 필드 이름은 디스코드가 직접 굵게 · 여백까지 그려 주는 자리다 (2026-08-23 실물 비교)
    names = [f["name"] for f in _fm_cliff()["fields"]]
    assert names == ["무슨 일이 있었나", "평소와 비교", "지금 어떤 상태인가",
                     "무엇을 하나", "회차"]


def test_sections_are_spaced_apart_except_the_last_one():
    # 디스코드 필드 간격은 고정이라 폭 없는 공백 한 줄로 띄운다
    fields = [f for f in _fm_cliff()["fields"] if not f.get("inline")]
    assert all(f["value"].endswith("\n\u200b") for f in fields[:-1])
    assert not fields[-1]["value"].endswith("\u200b")


def test_several_sources_fall_back_to_one_field_each():
    # 구획을 필드로 펼치면 소스 일곱 곳이 동시에 끊길 때 상한 (25) 을 넘겨
    # 알림이 발송에 실패한다 — 하필 전면 장애 때 알림을 잃는다
    alert = notify.build_cliff_alert(
        ["fmkorea", "guardian"], history=[{"fmkorea": 12, "guardian": 8}],
        sources=_FM_CFG, failure_codes={}, success_rate=1.0, run_id="3f2a9c12abcd")
    names = [f["name"] for f in alert["fields"]]
    assert names == ["fmkorea 축구 소식통 (fmkorea)", "The Guardian (guardian)", "회차"]
    assert "**▸ 무슨 일이 있었나**" not in names[0]
    assert "**▸ 평소와 비교**" in alert["fields"][0]["value"]


def test_each_search_keyword_gets_its_own_line():
    # 이어붙인 줄은 디스코드가 앞 불릿에 흡수한다 — 키워드마다 중첩 항목으로 낸다
    value = _field(_fm_cliff(), "무슨 일이 있었나")
    kw_lines = [ln for ln in value.splitlines() if ln.startswith("  - `")]
    assert len(kw_lines) == 2


def test_cliff_states_the_count_plainly_without_history():
    alert = notify.build_cliff_alert(
        ["fmkorea"], history=[], sources=_FM_CFG,
        failure_codes={}, success_rate=1.0, run_id="3f2a9c12abcd")
    assert "- 찾은 글: **0건** (이번 회차)" in _field(alert, "평소와 비교")


# ── 발견 퍼널 4단을 알림에 싣는다 (스펙 2026-08-14 §8.2) ─────────────────────

_FUNNEL = {"selected": 13, "deduped": 13, "titled": 7, "passed": 3}


def test_cliff_shows_the_discovery_funnel_when_the_adapter_counts_it():
    alert = _fm_cliff(funnels={"fmkorea": _FUNNEL})
    value = _field(alert, "무슨 일이 있었나")
    assert "- 발견 퍼널: 목록 13 → URL 13 → 제목 7 → 키워드 3" in value
    assert "*단마다 남은 수" in value


def test_cliff_omits_the_funnel_when_the_adapter_does_not_count_it():
    # 계수를 안 내놓는 어댑터 (rss · x_playwright) 는 그 줄이 빠진다
    assert "발견 퍼널" not in str(_fm_cliff()["fields"])


def test_freshness_shows_the_discovery_funnel_in_the_path_section():
    # 신선도 알림은 셀렉터 드리프트를 「원인 후보」 로 추측해 왔다 — 퍼널이 그 자리를
    # 관측으로 바꾼다 (목록이 0이면 셀렉터, 키워드만 0이면 원문이 조용한 것)
    checked = datetime(2026, 8, 23, 6, 0, 0)
    records = [SourceFreshness("bbc_sport", checked - timedelta(hours=99), 72.0,
                               99.0, True)]
    alert = notify.build_freshness_alert(
        records, 48, targets=records, sources=_FRESH_SOURCES, run_id="3f2a9c12abcd",
        checked_at=checked, candidates={}, funnels={"bbc_sport": _FUNNEL})
    assert "- 발견 퍼널: 목록 13 → URL 13 → 제목 7 → 키워드 3" \
        in _field(alert, "수집 경로는 살아 있나")
