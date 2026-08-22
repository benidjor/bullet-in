from __future__ import annotations
import logging, os, re
import httpx
from datetime import datetime, timezone

from bullet_in.quality import FRESHNESS_REALERT_HOURS

logger = logging.getLogger(__name__)


class _WebhookRedactFilter(logging.Filter):
    """httpx INFO 로그의 Discord 웹훅 주소를 가린다.

    웹훅 주소는 그 자체가 인증 수단이라 저널 읽기 권한이 곧 발송 권한이 된다.
    httpx 로거를 통째로 올리지 않는 이유는 나머지 요청 로그가 수집 진단에 쓰이기 때문이다
    (소스별 본문 요청 수를 세는 근거)."""
    _RE = re.compile(r"(api/webhooks/)\S+")

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "api/webhooks/" in msg:
            record.msg = self._RE.sub(r"\1[REDACTED]", msg)
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_WebhookRedactFilter())

# 알림 채널 (스펙 2026-08-14 §7) — 급한 것이 안 급한 것에 묻히지 않게 셋으로 가른다.
# 장애 = 고쳐야 하는 것 · 관측 = 결정해야 하는 것 · 경향 = 당장 할 일이 없을 때가 많은 것.
CHANNEL_INCIDENT = "incident"
CHANNEL_REVIEW = "review"
CHANNEL_TREND = "trend"
CHANNEL_ENV = {CHANNEL_INCIDENT: "DISCORD_WEBHOOK_INCIDENT",
               CHANNEL_REVIEW: "DISCORD_WEBHOOK_REVIEW",
               CHANNEL_TREND: "DISCORD_WEBHOOK_TREND"}

COLOR_ANOMALY = 0xF2A600
COLOR_FAILURE = 0xE01E5A
COLOR_CANDIDATE = 0x3BA55D
COLOR_BLOCK = 0xD9534F

# 후보 0건일 때만 붙는 추측 줄이다 — 응답 코드 같은 관측값은 여기 적지 않는다.
# _failure_code_line 이 서버가 준 코드를 따로 싣고, 두 자리에 같은 값을 두면
# 한쪽이 낡는다 (fmkorea 힌트가 「429」 로 남아 있었고 실제 차단 응답은 430 이다).
ADAPTER_HINTS = {
    "x_playwright": "X 쿠키 만료 · 핸들 변경",
    "x_backtrack": "X 쿠키 만료 · 핸들 변경",
    "html": "셀렉터 드리프트 · 사이트 개편",
    "playwright": "셀렉터 · 동의창 드리프트",
    "rss": "피드 URL 변경",
    "fmkorea": "검색 URL 변경 · 자동 수집 차단",
}
RUNBOOK_FRESHNESS = ("https://github.com/benidjor/bullet-in/blob/main/"
                     "docs/runbook/2026-07-13-freshness-watermark-ops.md")
RUNBOOK_ANOMALY = ("https://github.com/benidjor/bullet-in/blob/main/"
                   "docs/runbook/2026-07-13-collection-alerts-ops.md")
RUNBOOK_ROSTER = ("https://github.com/benidjor/bullet-in/blob/main/"
                  "docs/runbook/2026-07-31-player-roster-ops.md")


def _discord_ts(dt: datetime, style: str) -> str:
    """naive UTC datetime → Discord 시각 마크업 (R=상대 · f=절대)."""
    return f"<t:{int(dt.replace(tzinfo=timezone.utc).timestamp())}:{style}>"


def send_alert(title: str, description: str, *, color: int,
               fields: list[dict] | None = None, url: str | None = None,
               timestamp: str | None = None, footer: str | None = None,
               channel: str | None = None) -> None:
    """channel 이 가리키는 웹훅으로 보내고, 그 변수가 없으면 기존 웹훅으로 떨어뜨린다.

    폴백이 이 설계의 안전장치다 — 웹훅 셋을 만들기 전에 배포해도 알림이 사라지지
    않는다 (스펙 2026-08-14 §7)."""
    embed: dict = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    if url:
        embed["url"] = url
    if timestamp:
        embed["timestamp"] = timestamp
    if footer:
        embed["footer"] = {"text": footer}
    webhook = (os.environ.get(CHANNEL_ENV.get(channel or "", ""))
               or os.environ.get("DISCORD_WEBHOOK_URL"))
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
                        hist: list[dict], sources: dict, run_id: str,
                        candidates: dict | None = None) -> dict:
    """소스별 수집량 드롭 · 스파이크 알림.

    candidates 는 이번 회차 후보 계수 (dedup 전) — 발견이 살아 있는지를 가른다.
    후보가 있는데 적재가 줄었으면 발견은 도는 것이므로 어댑터 힌트 (셀렉터 드리프트 ·
    차단) 는 근거가 없다 (스펙 2026-08-14 §6.4). candidates=None 이면 계수를 모르므로
    종전처럼 드롭에 힌트를 붙인다.
    스파이크에는 원인 후보를 붙이지 않는다 — 「중복 유입 · 파싱 회귀 의심」 은 관측이
    아니라 추측이었고, 같은 함정으로 SLO-5 를 두 번 고쳤다 (#169 · #174)."""
    drops = sum(1 for a in anomalies if a.direction == "drop")
    fields = []
    for a in anomalies:
        arrow = "▼" if a.direction == "drop" else "▲"
        lines = [f"{arrow} {a.today}건 (평소 ~{a.baseline:g})"]
        if any(a.source_id in h for h in hist):
            recent = [h.get(a.source_id, 0) for h in hist[:5]]
            seq = " → ".join(str(c) for c in reversed(recent))
            lines.append(f"최근: {seq} → (오늘) {a.today}")
        found = None if candidates is None else candidates.get(a.source_id, 0)
        if found is not None:
            lines.append(f"이번 회차 후보 {found}건 중 새로 담은 글 {a.today}건")
        hint = ADAPTER_HINTS.get((sources.get(a.source_id) or {}).get("adapter"))
        if a.direction == "drop" and hint and not found:
            lines.append(f"원인 후보: {hint}")
        fields.append({"name": _source_field_name(a.source_id, sources),
                       "value": "\n".join(f"- {ln}" for ln in lines),
                       "inline": False})
    fields.append({"name": "회차",
                   "value": f"최근 {history_count}회 기준 · run {run_id[:8]}",
                   "inline": True})
    subject = _title_subject([_source_label(a.source_id, sources)
                              for a in anomalies])
    head = anomalies[0]
    return {"title": (f"⚠️ 수집량 {'드롭' if head.direction == 'drop' else '스파이크'} — "
                      f"{subject} {head.today}건 (평소 ~{head.baseline:g})"
                      if len(anomalies) == 1 else
                      f"⚠️ 수집량 이상 — {subject} "
                      f"(드롭 {drops} · 스파이크 {len(anomalies) - drops})"),
            "description": (f"최근 {history_count}회 대비 소스별 수집량 이상 — "
                            "「수집량」 은 중복 · 필터를 지나 이번 회차에 새로 담은 "
                            "글 수입니다"),
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ANOMALY,
            "channel": CHANNEL_TREND}


def _source_field_name(source_id: str, sources: dict) -> str:
    name = (sources.get(source_id) or {}).get("display_name")
    return f"{name} ({source_id})" if name else source_id


def _source_label(source_id: str, sources: dict) -> str:
    """제목용 짧은 이름 — 설정의 display_name, 없으면 source_id."""
    return (sources.get(source_id) or {}).get("display_name") or source_id


def _title_subject(labels: list[str]) -> str:
    """제목에 올릴 소스 이름 — 여럿이면 첫 이름과 나머지 계수 (스펙 2026-08-14 §6.1)."""
    rest = len(labels) - 1
    return f"{labels[0]} 외 {rest}개 소스" if rest else labels[0]


SPACER = "\u200b"   # 폭 없는 공백 — 이 한 줄이 구획 사이의 여백이 된다


def _section_fields(sections: list[tuple[str, list[str]]]) -> list[dict]:
    """구획을 embed 필드로 낸다 — 필드 이름이 디스코드가 직접 그리는 제목이다.

    마크다운 굵기와 달리 크기 · 여백까지 디스코드가 붙여 주고, 렌더가 보장된다
    (2026-08-23 실물 비교에서 세 서식 중 이것이 이겼다).
    필드 간격은 고정이라 마지막을 뺀 구획 끝에 폭 없는 공백 한 줄을 더해 띄운다.
    줄이 없는 구획은 빠진다."""
    kept = [(name, lines) for name, lines in sections if lines]
    out = []
    for i, (name, lines) in enumerate(kept):
        value = "\n".join(f"- {ln}" for ln in lines)
        if i < len(kept) - 1:
            value += "\n" + SPACER
        out.append({"name": name, "value": value, "inline": False})
    return out


def _sectioned(sections: list[tuple[str, list[str]]]) -> str:
    """구획 제목과 줄 목록을 필드 값으로 엮는다 — 줄이 없는 구획은 빠진다.

    「그래서 어떤 상태인가」 와 「무엇을 하나」 를 눈으로 가르기 위한 것이다 (§6.1).
    구획 제목을 굵게 내는 이유는 디스코드가 굵기 없이는 불릿과 같은 무게로 그리기
    때문이다 (2026-08-22 실물 화면)."""
    out: list[str] = []
    for name, lines in sections:
        if not lines:
            continue
        out.append(f"**▸ {name}**")
        out.extend(f"- {ln}" for ln in lines)
    return "\n".join(out)


def build_freshness_alert(records, default_hours: float, *,
                          targets: list, sources: dict, run_id: str,
                          checked_at: datetime,
                          candidates: dict | None = None,
                          fetch_errors: dict | None = None,
                          funnels: dict | None = None) -> dict:
    """전체 판정 레코드를 받아 이번 회차 발송 대상만 필드로 펼친다.

    targets 는 quality.freshness_alert_split 이 고른 발송분이다 — stale 전부가 아니라
    임계를 새로 넘었거나 재알림 간격이 돌아온 소스다. 나머지 stale 은 설명의 대기
    계수로만 남긴다.
    candidates 는 이번 회차에 어댑터가 찾은 소스별 후보 건수 (dedup 전) — 키 부재 = 0건.
    후보 계수는 발송 조건이 아니라 진단 재료다 (스펙 2026-08-14 §4.1): 후보가 있으면
    경로는 응답한다는 사실을 적고, 어댑터 힌트 (셀렉터 드리프트 등) 는 후보 0건일 때만
    근거가 있다 (2026-07-30 실측, docs/troubleshooting/
    2026-07-30-silent-drops-and-blind-alerts.md §4).
    candidates=None 이면 계수 없이 힌트만 붙인다."""
    breaches = [r for r in records if r.stale]
    waiting = len(breaches) - len(targets)
    no_wm = sum(1 for r in records if r.last_fetched_at is None)
    ok = len(records) - len(breaches) - no_wm
    per_source: list[tuple[str, list[tuple[str, list[str]]]]] = []
    for b in targets:
        age = [f"⏳ **{b.age_hours:.1f}h** 경과 (임계 {b.threshold_hours:g}h)",
               f"마지막 수집: {_discord_ts(b.last_fetched_at, 'R')} "
               f"({_discord_ts(b.last_fetched_at, 'f')})"]
        # 기사 표가 원본보다 뒤처진 소스에만 붙인다 — 받기는 받았는데 그 뒤로는
        # 다른 행에 흡수돼 행이 안 남았다는 뜻이다 (설계 2026-08-20 §3.5).
        if (b.stored_fetched_at is not None
                and b.stored_fetched_at < b.last_fetched_at):
            age.append(f"마지막 저장: {_discord_ts(b.stored_fetched_at, 'f')} "
                       "(그 뒤로는 다른 행으로 흡수)")
        hint = ADAPTER_HINTS.get((sources.get(b.source_id) or {}).get("adapter"))
        path: list[str] = []
        if (fetch_errors or {}).get(b.source_id):
            path.append(f"이번 회차 fetch 오류: {fetch_errors[b.source_id][:120]}")
        else:
            n = None if candidates is None else candidates.get(b.source_id, 0)
            if n:
                path.append(f"이번 회차 후보 **{n}건** — 전부 이미 받은 글입니다")
            elif n is not None:
                path.append("이번 회차 후보 0건")
            if hint and not n:
                path.append(f"원인 후보: {hint}")
        path += _funnel_lines((funnels or {}).get(b.source_id))
        per_source.append((b.source_id, [
            ("얼마나 오래됐나", age),
            ("수집 경로는 살아 있나", path),
            ("다음 알림",
             [f"{FRESHNESS_REALERT_HOURS:g}시간 더 지나면 다시 알립니다"])]))
    # 절벽 알림과 같은 규칙 — 소스가 하나면 구획을 필드로 펼치고 여럿이면 접는다.
    if len(per_source) == 1:
        fields = _section_fields(per_source[0][1])
    else:
        fields = [{"name": _source_field_name(sid, sources),
                   "value": _sectioned(sections), "inline": False}
                  for sid, sections in per_source]
    fields.append({"name": "기본 임계", "value": f"전역 {default_hours:g}h",
                   "inline": True})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    subject = _title_subject([_source_label(b.source_id, sources) for b in targets])
    return {"title": (f"🕰️ 신선도 경고 — {subject} "
                      f"{targets[0].age_hours / 24:.1f}일째 조용합니다"
                      if len(targets) == 1
                      else f"🕰️ 신선도 경고 — {subject}가 오래됐습니다"),
            "description": (f"감시 {len(records)}소스: stale {len(breaches)} · "
                            f"정상 {ok} · 워터마크 없음 {no_wm}"
                            + (f" · 재알림 대기 {waiting}" if waiting else "")),
            "color": COLOR_ANOMALY, "fields": fields,
            "url": RUNBOOK_FRESHNESS,
            "timestamp": checked_at.replace(tzinfo=timezone.utc).isoformat(),
            "footer": "bullet-in", "channel": CHANNEL_TREND}


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
            "color": COLOR_FAILURE, "fields": fields,
            "channel": CHANNEL_INCIDENT}


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
            "color": COLOR_ANOMALY, "fields": fields,
            "channel": CHANNEL_TREND}


def build_filter_miss_alert(suspects: list[dict], *, run_id: str) -> dict:
    """공홈 창 후보 중 이적 관련 제목인데 수집되지 않은 기사 알림 (스펙 2026-08-07 §3.3).

    실측 사례 (2026-08-05 Norgaard): 이적 발표에 Transfer news 태그가 빠져
    태그 기준 수집에서 빠졌다. 원인 추정 없이 제목 · 태그 · 링크만 싣는다."""
    fields = []
    for s in suspects:
        lines = [f"- 태그: {' · '.join(s.get('taxonomies') or []) or '-'}"]
        pub = s.get("published")
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                lines.append(f"- 발행: {_discord_ts(dt.replace(tzinfo=None), 'R')}")
            except ValueError:
                pass
        if s.get("url"):
            lines.append(f"- [기사]({s['url']})")
        fields.append({"name": s.get("title") or "(제목 없음)",
                       "value": "\n".join(lines), "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": (f"🔍 공홈 이적 관련 기사 미수집 — {len(suspects)}건"),
            "description": ("arsenal.com 새 기사 제목에 이적 관련 표현이 있는데 "
                            "이번 회차에 수집되지 않았습니다.\n"
                            "현재 수집 기준은 기사 태그 (Transfer news · Contract news) 입니다."),
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ANOMALY,
            "channel": CHANNEL_REVIEW}


def build_candidate_alert(candidates: list[dict], *, run_id: str) -> dict:
    """enrich 자동 발굴 후보 등재 알림 (스펙 §4.2) — 후속 액션은 확정 CLI.
    Discord embed 필드 상한 (25) 안에서 10명까지 펼치고 나머지는 건수로 접는다.

    성이 같고 이름이 비슷한 기존 선수가 있으면 그 줄을 카드 안에 덧붙인다
    (추출 범위 개정 스펙 §8.5). 별도 알림을 만들지 않는 것은 의도다 — 후보가 없는
    회차에는 이 알림 자체가 안 나가므로 도배가 되지 않고, 판단 재료가 후보 정보와
    같은 자리에 있어야 사람이 한 번에 본다. 병합은 확정 CLI 에서 사람이 한다."""
    fields = []
    for c in candidates[:10]:
        name = f"{c.get('ko') or '?'} ({c['full_name']})"
        lines = [f"단계: {c['stage']}", f"근거: {(c.get('title') or '-')[:200]}"]
        dups = c.get("dup_suspects") or []
        if dups:
            lines.append("중복 의심 (병합은 수동): "
                         + " · ".join(f"{d['full_name']} (id {d['id']})"
                                      for d in dups))
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
            "color": COLOR_CANDIDATE, "fields": fields,
            "channel": CHANNEL_REVIEW}


_SEARCH_TARGET_LABELS = {"title": "제목", "title_content": "제목·본문"}
BOT_BLOCK_CODE = 430   # fmkorea 의 자동 수집 차단 응답 (런북 2026-07-13-collection-alerts-ops)


def _search_keyword_line(source: dict, failed: int) -> str | None:
    """설정에 있는 검색 키워드를 알림이 직접 싣는다 (스펙 2026-08-14 §6.1).

    어댑터는 키워드마다 첫 실패에서 그 키워드를 접으므로 실패 계수와 실패한 키워드
    수가 같다 — 그래서 「전부」 라고 쓸 수 있다. 키워드를 안 쓰는 어댑터는 None.
    키워드마다 중첩 목록 한 줄로 내는 이유는 디스코드가 들여쓴 이어붙임 줄을 앞
    불릿에 흡수해 한 덩어리로 흘려 버리기 때문이다 (2026-08-22 실물 화면)."""
    kws = ((source.get("config") or {}).get("search_keywords")) or []
    if not kws:
        return None
    rows = [f"  - `{k['keyword']}` — "
            f"{_SEARCH_TARGET_LABELS.get(k['target'], k['target'])}" for k in kws]
    head = (f"검색 키워드 **{len(kws)}개가 전부 실패**했습니다" if failed == len(kws)
            else f"검색 키워드 {len(kws)}개")
    return "\n".join([head, *rows])


_FUNNEL_STAGES = [("selected", "목록"), ("deduped", "URL"),
                  ("titled", "제목"), ("passed", "키워드")]


def _funnel_lines(funnel: dict | None) -> list[str]:
    """발견 4단 계수를 두 줄로 (스펙 2026-08-14 §8.2).

    기록되는 후보 계수는 마지막 단뿐이라, 셀렉터가 깨져 첫 단이 0 이 된 것과 원문이
    조용해 마지막 단이 0 이 된 것이 구분되지 않았다 (§2.5 실측 13 → 13 → 7 → 3).
    계수를 안 내놓는 어댑터 (rss · x_playwright) 는 빈 목록이라 그 줄이 빠진다 —
    _failure_code_line 과 같은 방식이다."""
    if not funnel:
        return []
    chain = " → ".join(f"{label} {funnel.get(key, 0)}"
                       for key, label in _FUNNEL_STAGES)
    return [f"발견 퍼널: {chain}",
            "*단마다 남은 수 — 목록이 0이면 셀렉터, 키워드만 0이면 원문이 "
            "조용한 것입니다*"]


def _failure_code_line(codes: dict) -> str | None:
    """어댑터가 센 검색 실패 사유 — 서버 응답 코드라 관측 사실로 적을 수 있다.
    계수를 내놓지 않는 어댑터는 None 을 돌려 그 줄이 빠진다."""
    if not codes:
        return None
    total = sum(codes.values())
    parts = [("연결 오류" if k == "error" else f"`HTTP {k}`") + f" {v}건"
             for k, v in sorted(codes.items(), key=lambda kv: str(kv[0]))]
    return f"검색 실패 **{total}건** — " + " · ".join(parts)


def build_cliff_alert(cliffs: list[str], *, history: list[dict], sources: dict,
                      failure_codes: dict, success_rate: float,
                      run_id: str, funnels: dict | None = None) -> dict:
    """후보 절벽 알림 (차단 알림 스펙 §5.1).

    판정은 run.py 가 끝냈고 여기서는 표시만 한다 — history[0] 이 직전 회차다.
    ADAPTER_HINTS 를 쓰지 않는다: 후보 0 의 원인은 알림 시점에 알 수 없고,
    같은 함정으로 SLO-5 를 두 번 고쳤다 (#169 · #174)."""
    per_source: list[tuple[str, list[tuple[str, list[str]]]]] = []
    for sid in cliffs:
        codes = failure_codes.get(sid) or {}
        blocked = BOT_BLOCK_CODE in codes
        happened = []
        kw_line = _search_keyword_line(sources.get(sid) or {}, sum(codes.values()))
        if kw_line:
            happened.append(kw_line)
        code_line = _failure_code_line(codes)
        if code_line:
            happened.append(code_line
                            + (" *(자동 수집 차단 응답)*" if blocked else ""))
        happened += _funnel_lines((funnels or {}).get(sid))
        recent = [h.get(sid, 0) for h in history[:4]]
        # 마지막 자리가 이번 회차임을 화살표 사슬 안에서 보여 준다 — 종전에는 계수와
        # 추이를 따로 적어 어느 숫자가 이번 것인지 한눈에 안 보였다.
        compared = [(" → ".join(str(c) for c in reversed(recent))
                     + " → **0 (이번)**" if recent else "**0건** (이번 회차)"),
                    "*「찾은 글」 은 중복을 포함한 발견 결과 수이고 저장된 글 수가 "
                    "아닙니다*"]
        compared[0] = ("찾은 글 추이: " if recent else "찾은 글: ") + compared[0]
        # "정상 종료" 라고 쓰면 success_rate 가 1 미만일 때 숫자와 말이 어긋난다
        # (실사례 2026-08-04 06:04 — arsenal_official 503 으로 0.889).
        # 실패 알림이 왜 따로 안 왔는지만 사실로 적고 판단은 숫자에 맡긴다.
        state = ["이번 회차에 새 글이 없습니다",
                 "*다음 회차에 풀리면 대개 놓치는 글이 없습니다 — 발견이 최근 글 "
                 "목록을 매번 다시 훑습니다*",
                 f"회차는 실패로 끝나지 않았습니다 (`success_rate {success_rate:g}`)",
                 "*어댑터가 예외를 던지지 않아 실패 알림이 따로 가지 않았습니다*"]
        todo = ["차단은 보통 저절로 풀립니다 — 지금은 조치하지 않습니다"] if blocked else []
        todo += ["확인할 때 사이트에 직접 접속하지 말고 다음 회차 로그를 보십시오",
                 "회차가 계속 0이면 런북 (제목 클릭) 의 절차를 따릅니다"]
        per_source.append((sid, [("무슨 일이 있었나", happened),
                                 ("평소와 비교", compared),
                                 ("지금 어떤 상태인가", state),
                                 ("무엇을 하나", todo)]))
    # 소스가 하나면 구획을 필드로 펼친다 (읽기 좋은 쪽). 여럿이면 소스당 한 필드로
    # 접는다 — 구획을 펼친 채로 소스가 일곱 곳 동시에 끊기면 embed 필드 상한 (25) 을
    # 넘겨 알림이 발송에 실패한다. 하필 전면 장애 때 알림을 잃는 자리다.
    if len(per_source) == 1:
        fields = _section_fields(per_source[0][1])
    else:
        fields = [{"name": _source_field_name(sid, sources),
                   "value": _sectioned(sections), "inline": False}
                  for sid, sections in per_source]
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": _cliff_title(cliffs, sources, failure_codes),
            "description": "직전 회차까지 글을 가져오던 소스가 이번 회차에 한 건도 못 가져왔습니다.",
            "color": COLOR_BLOCK, "fields": fields, "url": RUNBOOK_ANOMALY,
            "channel": CHANNEL_INCIDENT}


def _cliff_title(cliffs: list[str], sources: dict, failure_codes: dict) -> str:
    """소스 이름을 제목에 올린다 (스펙 2026-08-14 §6.1) — 실패 계수는 있을 때만."""
    if len(cliffs) > 1:
        return ("🚨 이번 회차 수집 0건 — "
                + _title_subject([_source_label(c, sources) for c in cliffs]))
    sid = cliffs[0]
    failed = sum((failure_codes.get(sid) or {}).values())
    kws = ((sources.get(sid) or {}).get("config") or {}).get("search_keywords") or []
    if not failed:
        return f"🚨 {_source_label(sid, sources)} 수집 0건"
    whole = "전부 " if failed == len(kws) else ""
    return f"🚨 {_source_label(sid, sources)} 수집 0건 — 검색 {failed}건이 {whole}실패했습니다"


def build_watchlist_blackout_alert(*, searched: int, failure_codes: dict,
                                   last_contact) -> dict:
    """워치리스트 배치 전멸 알림 (차단 알림 스펙 §5.2).

    커서가 전진하지 않는다는 사실을 함께 적는다 — 다음 배치가 같은 슬라이스를
    다시 검색하므로 사람이 따로 되돌릴 것이 없다."""
    lines = [f"검색 {searched}명 · "
             + (_failure_code_line(failure_codes) or f"검색 실패 {searched}건")]
    if last_contact is not None:
        lines.append(f"마지막 fmkorea 접촉: {_discord_ts(last_contact, 'R')} "
                     f"({_discord_ts(last_contact, 'f')})")
    return {"title": f"🚨 fmkorea 선수 검색 실패 — {searched}명 전원",
            "description": (f"이번 차례 선수 {searched}명을 fmkorea 에서 이름으로 검색했으나 "
                            "전부 실패해 새로 가져온 글이 없습니다.\n"
                            "검색 순서는 그대로 두어 다음 차례에 같은 선수들을 "
                            "다시 시도합니다."),
            "color": COLOR_BLOCK,
            "fields": [{"name": "이번 차례",
                        "value": "\n".join(f"- {ln}" for ln in lines),
                        "inline": False}],
            "url": RUNBOOK_ANOMALY, "channel": CHANNEL_INCIDENT}


# 명단 이적 축 낡음 관측 알림 (스펙 2026-08-10) — 표기는 사람이 읽는 한국어로.
_AXIS_LABELS = {"none": "이적 축 없음", "in_link": "영입 링크",
                "out_link": "방출 링크", "in_done": "영입 완료",
                "out_done": "방출 완료"}
_STAGE_LABELS = {"rumour": "루머", "interest": "관심", "negotiating": "협상",
                 "personal_terms": "개인 합의", "agreed": "합의",
                 "medical": "메디컬", "official": "오피셜",
                 "done": "이적 완료", "collapsed": "무산"}


def build_roster_staleness_alert(cases: list[dict], *, run_id: str) -> dict:
    """명단 축 값과 이번 회차 새 기사 단계의 어긋남 의심을 선수별 필드로 펼친다.

    관측만 싣는다 (현재 값 · 새로 붙은 단계 · 최근 7일 누적) — 원인 단정 · 값
    갱신 판단은 명단 런북 §6 절차로 사람이 한다."""
    fields = []
    for c in cases:
        new_txt = " · ".join(
            f"{_STAGE_LABELS.get(s, s)} {n}건"
            for s, n in sorted(c["new_stages"].items()))
        lines = [f"명단 값: {_AXIS_LABELS.get(c['transfer_status'], c['transfer_status'])}",
                 f"이번 회차 새 기사 단계: {new_txt}",
                 f"최근 7일 같은 계열 기사: {c['recent_total']}건"]
        fields.append({"name": c["ko_name"],
                       "value": "\n".join(f"- {ln}" for ln in lines),
                       "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": f"📋 선수 명단 확인 — 이적 상태 값이 낡았을 수 있음 ({len(cases)}명)",
            "description": ("확정 선수의 이적 상태 값과 새로 수집된 기사의 단계가 "
                            "어긋난다. 명단 런북 §6 절차로 값을 확인한다."),
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ROSTER,
            "footer": "bullet-in", "channel": CHANNEL_REVIEW}
