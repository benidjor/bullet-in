from __future__ import annotations
import logging, os
import httpx
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

COLOR_ANOMALY = 0xF2A600
COLOR_FAILURE = 0xE01E5A
COLOR_CANDIDATE = 0x3BA55D

ADAPTER_HINTS = {
    "x_playwright": "X 쿠키 만료 · 핸들 변경",
    "x_backtrack": "X 쿠키 만료 · 핸들 변경",
    "html": "셀렉터 드리프트 · 사이트 개편",
    "playwright": "셀렉터 · 동의창 드리프트",
    "rss": "피드 URL 변경",
    "fmkorea": "검색 URL 변경 · 429 차단",
}
SPIKE_HINT = "중복 유입 · 파싱 회귀 의심"
RUNBOOK_FRESHNESS = ("https://github.com/benidjor/bullet-in/blob/main/"
                     "docs/runbook/2026-07-13-freshness-watermark-ops.md")
RUNBOOK_ANOMALY = ("https://github.com/benidjor/bullet-in/blob/main/"
                   "docs/runbook/2026-07-13-collection-alerts-ops.md")


def _discord_ts(dt: datetime, style: str) -> str:
    """naive UTC datetime → Discord 시각 마크업 (R=상대 · f=절대)."""
    return f"<t:{int(dt.replace(tzinfo=timezone.utc).timestamp())}:{style}>"


def send_alert(title: str, description: str, *, color: int,
               fields: list[dict] | None = None, url: str | None = None,
               timestamp: str | None = None, footer: str | None = None) -> None:
    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    if url:
        embed["url"] = url
    if timestamp:
        embed["timestamp"] = timestamp
    if footer:
        embed["footer"] = {"text": footer}
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        logger.warning("알림 (webhook 미설정): %s — %s", title, description)
        return
    try:
        resp = httpx.post(webhook, json={"embeds": [embed]}, timeout=10)
        if resp.status_code >= 300:
            logger.warning("알림 발송 실패 (status %s): %s", resp.status_code, title)
    except Exception as e:
        logger.warning("알림 발송 오류: %s (%s)", title, e)


def build_anomaly_alert(anomalies, history_count: int, *,
                        hist: list[dict], sources: dict, run_id: str) -> dict:
    drops = sum(1 for a in anomalies if a.direction == "drop")
    fields = []
    for a in anomalies:
        arrow = "▼" if a.direction == "drop" else "▲"
        lines = [f"{arrow} {a.today}건 (평소 ~{a.baseline:g})"]
        if any(a.source_id in h for h in hist):
            recent = [h.get(a.source_id, 0) for h in hist[:5]]
            seq = " → ".join(str(n) for n in reversed(recent))
            lines.append(f"최근: {seq} → (오늘) {a.today}")
        hint = (ADAPTER_HINTS.get((sources.get(a.source_id) or {}).get("adapter"))
                if a.direction == "drop" else SPIKE_HINT)
        if hint:
            lines.append(f"원인 후보: {hint}")
        fields.append({"name": _source_field_name(a.source_id, sources),
                       "value": "\n".join(f"- {ln}" for ln in lines),
                       "inline": False})
    fields.append({"name": "회차",
                   "value": f"최근 {history_count}회 기준 · run {run_id[:8]}",
                   "inline": True})
    return {"title": (f"⚠️ 수집량 이상 — {len(anomalies)}건 "
                      f"(드롭 {drops} · 스파이크 {len(anomalies) - drops})"),
            "description": f"최근 {history_count}회 대비 소스별 수집량 이상",
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ANOMALY}


def _source_field_name(source_id: str, sources: dict) -> str:
    name = (sources.get(source_id) or {}).get("display_name")
    return f"{name} ({source_id})" if name else source_id


def build_freshness_alert(records, default_hours: float, *,
                          sources: dict, run_id: str,
                          checked_at: datetime,
                          candidates: dict | None = None,
                          fetch_errors: dict | None = None) -> dict:
    """전체 판정 레코드를 받아 stale 소스만 필드로 펼친다 (stale=True 는 age_hours 존재).

    candidates 는 이번 회차에 어댑터가 찾은 소스별 후보 건수 (dedup 전) — 키 부재 = 0건.
    후보 0건일 때만 어댑터 힌트를 붙인다: 후보가 있으면 수집 경로는 정상이고
    전부 기존 기사라 신규가 없는 것이라 셀렉터 드리프트 추측은 오진이다
    (2026-07-30 실측, docs/troubleshooting/2026-07-30-silent-drops-and-blind-alerts.md §4).
    candidates=None 이면 계수 없이 종전대로 힌트만 붙인다."""
    breaches = [r for r in records if r.stale]
    no_wm = sum(1 for r in records if r.last_fetched_at is None)
    ok = len(records) - len(breaches) - no_wm
    fields = []
    for b in breaches:
        lines = [f"⏳ {b.age_hours:.1f}h 경과 (임계 {b.threshold_hours:g}h)",
                 f"마지막 수집: {_discord_ts(b.last_fetched_at, 'R')} "
                 f"({_discord_ts(b.last_fetched_at, 'f')})"]
        hint = ADAPTER_HINTS.get((sources.get(b.source_id) or {}).get("adapter"))
        if (fetch_errors or {}).get(b.source_id):
            lines.append(f"이번 회차 fetch 오류: {fetch_errors[b.source_id][:120]}")
        elif candidates is not None:
            n = candidates.get(b.source_id, 0)
            if n == 0:
                lines.append("이번 회차 후보 0건 — 수집 끊김 의심")
                if hint:
                    lines.append(f"원인 후보: {hint}")
            else:
                lines.append(f"이번 회차 후보 {n}건 — 수집 경로 정상 · 신규 없음")
        elif hint:
            lines.append(f"원인 후보: {hint}")
        fields.append({"name": _source_field_name(b.source_id, sources),
                       "value": "\n".join(f"- {ln}" for ln in lines),
                       "inline": False})
    fields.append({"name": "기본 임계", "value": f"전역 {default_hours:g}h",
                   "inline": True})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": f"🕰️ 신선도 경고 — 오래된 소스 {len(breaches)}건",
            "description": (f"감시 {len(records)}소스: stale {len(breaches)} · "
                            f"정상 {ok} · 워터마크 없음 {no_wm}"),
            "color": COLOR_ANOMALY, "fields": fields,
            "url": RUNBOOK_FRESHNESS,
            "timestamp": checked_at.replace(tzinfo=timezone.utc).isoformat(),
            "footer": "bullet-in"}


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


COVERAGE_BREACH_FIELDS = {
    "no_candidates": ("창 후보 0", "sitemap 경로 변경 · 발견 경로 장애 의심"),
    "no_men_tag": ("Men 태그 소멸", "taxonomy 어휘 변경 — 필터 기아 재발 위험"),
}

def build_coverage_alert(breaches: list[str], coverage: dict, *, run_id: str) -> dict:
    fields = []
    for b in breaches:
        name, hint = COVERAGE_BREACH_FIELDS[b]
        fields.append({"name": name, "value": f"- 원인 후보: {hint}", "inline": False})
    fields.append({"name": "퍼널",
                   "value": (f"후보 {coverage.get('candidates', 0)} · "
                             f"Men {coverage.get('men_tagged', 0)} · "
                             f"accept {coverage.get('accepted', 0)}"),
                   "inline": True})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": "🏟️ 공홈 커버리지 경고 — arsenal_official",
            "description": "수집 창 퍼널 불변식 위반 — 조용한 기아 신호",
            "color": COLOR_ANOMALY, "fields": fields}


def build_candidate_alert(candidates: list[dict], *, run_id: str) -> dict:
    """enrich 자동 발굴 후보 등재 알림 (스펙 §4.2) — 후속 액션은 확정 CLI.
    Discord embed 필드 상한 (25) 안에서 10명까지 펼치고 나머지는 건수로 접는다."""
    fields = []
    for c in candidates[:10]:
        name = f"{c.get('ko') or '?'} ({c['full_name']})"
        lines = [f"단계: {c['stage']}", f"근거: {(c.get('title') or '-')[:200]}"]
        if c.get("url"):
            lines.append(f"[기사]({c['url']})")
        fields.append({"name": name,
                       "value": "\n".join(f"- {ln}" for ln in lines), "inline": False})
    if len(candidates) > 10:
        fields.append({"name": "그 외",
                       "value": f"- 후보 {len(candidates) - 10}명 추가 — DB 확인",
                       "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": f"🆕 링크 선수 후보 {len(candidates)}명 등재",
            "description": "확정 전에는 게이트 · 서빙 사전에 실리지 않는다 — 확정 CLI 로 승격",
            "color": COLOR_CANDIDATE, "fields": fields}
