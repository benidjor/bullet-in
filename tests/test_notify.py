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


def test_build_anomaly_alert_formats_lines_and_fields():
    anomalies = [Anomaly("fmkorea", 0, 14.0, "drop"),
                 Anomaly("bbc", 30, 9.0, "spike")]
    alert = notify.build_anomaly_alert(anomalies, history_count=12)
    assert alert["title"] == "⚠️ 수집량 이상"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert "▼ fmkorea: 0건 (평소 ~14)" in alert["description"]
    assert "▲ bbc: 30건 (평소 ~9)" in alert["description"]
    assert alert["fields"][0]["value"] == "최근 12회 기준"


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
    assert "⏳ 61.4h 경과 (임계 24h)" in field["value"]
    epoch = int((checked - timedelta(hours=61.4))
                .replace(tzinfo=timezone.utc).timestamp())
    assert f"마지막 수집: <t:{epoch}:R> (<t:{epoch}:f>)" in field["value"]
    assert "원인 후보: X 쿠키 만료 · 핸들 변경" in field["value"]


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
