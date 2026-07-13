from __future__ import annotations
import logging, os
import httpx

logger = logging.getLogger(__name__)

COLOR_ANOMALY = 0xF2A600
COLOR_FAILURE = 0xE01E5A


def send_alert(title: str, description: str, *, color: int,
               fields: list[dict] | None = None) -> None:
    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        logger.warning("알림 (webhook 미설정): %s — %s", title, description)
        return
    try:
        resp = httpx.post(url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code >= 300:
            logger.warning("알림 발송 실패 (status %s): %s", resp.status_code, title)
    except Exception as e:
        logger.warning("알림 발송 오류: %s (%s)", title, e)


def build_anomaly_alert(anomalies, history_count: int) -> dict:
    lines = "\n".join(
        f"{'▼' if a.direction == 'drop' else '▲'} {a.source_id}: "
        f"{a.today}건 (평소 ~{a.baseline:g})"
        for a in anomalies)
    return {"title": "⚠️ 수집량 이상", "description": lines,
            "color": COLOR_ANOMALY,
            "fields": [{"name": "회차", "value": f"최근 {history_count}회 기준",
                        "inline": True}]}


def build_freshness_alert(breaches, default_hours: float) -> dict:
    lines = "\n".join(
        f"⏳ {b.source_id}: {b.age_hours:.1f}h 경과 (임계 {b.threshold_hours:g}h)"
        for b in breaches)
    return {"title": "🕰️ 신선도 경고 — 오래된 소스", "description": lines,
            "color": COLOR_ANOMALY,
            "fields": [{"name": "기본 임계", "value": f"전역 {default_hours:g}h",
                        "inline": True}]}


def build_failure_alert(context) -> dict:
    ti = context["task_instance"]
    exc = context.get("exception")
    dur = getattr(ti, "duration", None)
    fields = [
        {"name": "DAG / Task", "value": f"{ti.dag_id} / {ti.task_id}", "inline": True},
        {"name": "Run", "value": str(context.get("run_id", "-")), "inline": True},
        {"name": "Try", "value": str(ti.try_number), "inline": True},
        {"name": "Duration",
         "value": f"{dur:.0f}s" if dur is not None else "-", "inline": True},
        {"name": "Host", "value": str(getattr(ti, "hostname", "-") or "-"),
         "inline": True},
        {"name": "로그", "value": f"[열기]({ti.log_url})", "inline": True},
    ]
    return {"title": "❌ 파이프라인 실패 — run_pipeline",
            "description": f"수집 파이프라인이 예외로 중단되었습니다.\n```\n{str(exc)[:400]}\n```",
            "color": COLOR_FAILURE, "fields": fields}
