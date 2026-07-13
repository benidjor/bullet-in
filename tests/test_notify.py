import logging
import pytest
from bullet_in import notify
from bullet_in.quality import Anomaly


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


def test_build_freshness_alert_formats_lines_and_threshold_field():
    from datetime import datetime, timedelta
    from bullet_in.quality import SourceFreshness

    now = datetime(2026, 7, 13, 12, 0, 0)
    breaches = [
        SourceFreshness("x_afcstuff", now - timedelta(hours=61.4), 24.0, 61.4, True),
        SourceFreshness("bbc_sport", now - timedelta(hours=72), 48.0, 72.0, True)]
    alert = notify.build_freshness_alert(breaches, default_hours=48)
    assert alert["title"] == "🕰️ 신선도 경고 — 오래된 소스"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert "⏳ x_afcstuff: 61.4h 경과 (임계 24h)" in alert["description"]
    assert "⏳ bbc_sport: 72.0h 경과 (임계 48h)" in alert["description"]
    assert alert["fields"][0] == {"name": "기본 임계", "value": "전역 48h",
                                  "inline": True}
