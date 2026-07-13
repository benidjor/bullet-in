# 알림 embed 디테일 강화 구현 계획 (2026-07-13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SLO-5 · SLO-6 Discord embed 에 진단 컨텍스트 (원인 후보 · 마지막 수집 상대시간 · 런북 링크) · 전체 조망 · 추세 시퀀스 · 실행 메타를 담는다.

**Architecture:** 표시 계층 (notify.py) 만 개편한다 — `send_alert` 에 선택 인자 3개 (하위 호환), 빌더 2개를 소스당 필드형으로 재작성, run.py 는 이미 스코프에 있는 값의 전달만 추가.
판정 · 적재 (`evaluate_freshness` · `volume_anomalies` · storage · schema · config) 무변경.
spec: `docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md`.

**Tech Stack:** Python 3.11 · httpx (Discord webhook) · pytest (httpx 모킹).

## Global Constraints

- `send_alert` 하위 호환 — `url` · `timestamp` · `footer` 는 선택 인자, 미지정 시 embed 에 해당 키 자체가 없어야 함 (기존 Airflow 콜백 호출부 무변경).
- 원인 후보는 `ADAPTER_HINTS` 매핑만 사용, 미지 어댑터는 힌트 줄 생략. 스파이크 고정 문구 = `중복 유입 · 파싱 회귀 의심`.
- 필드 이름 = `display_name (source_id)`, display_name 없으면 `source_id` 만.
- `<t:epoch:R>` epoch 변환은 naive UTC 에 `timezone.utc` 명시 (SLO-5 UTC 계약과 정합).
- run_id 표기는 앞 8자 (`run {run_id[:8]}`).
- SLO-6 시퀀스 = `hist[:5]` 를 뒤집어 (오래 → 최신) + `(오늘) {today}`, 이상 소스가 hist 에 없으면 시퀀스 줄 생략.
- 판정 · 적재 로직 무변경. run.py 는 두 호출부 인자 외 무변경.
- 커밋: 한국어 제목 + 서술형 도입 문장 + 평불릿 `- 항목: 설명` 본문 + Refs + 트레일러
  `Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>` / `Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>`.
  git 신원은 benidjor noreply 유지.
- docs 수정 (런북) 은 §2.2 서식 훅 통과 필수.
- 테스트는 httpx 모킹 단위 테스트만 (DB 불필요). 전체 스위트 기준선 = 205 passed · 1 skipped (통합은 MariaDB 없으면 skip).

---

### Task 1: `send_alert` 확장 · 시각 헬퍼 · 상수 (notify.py)

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: 없음.
- Produces (Task 2 · 3 이 사용):
  `send_alert(title, description, *, color, fields=None, url=None, timestamp=None, footer=None) -> None`,
  `_discord_ts(dt: datetime, style: str) -> str`,
  상수 `ADAPTER_HINTS: dict[str, str]` · `SPIKE_HINT: str` · `RUNBOOK_FRESHNESS: str` · `RUNBOOK_ANOMALY: str`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notify.py` 상단 import 를 다음으로 교체한다.

```python
import logging
from datetime import datetime, timedelta, timezone
import pytest
from bullet_in import notify
from bullet_in.quality import Anomaly, SourceFreshness
```

파일 끝에 추가한다.

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 신규 3건 FAIL — `TypeError: send_alert() got an unexpected keyword argument 'url'` · `AttributeError: ... no attribute '_discord_ts'`. 기존 테스트는 PASS 유지.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/notify.py` 상단 import 에 추가한다.

```python
from datetime import datetime, timezone
```

`COLOR_FAILURE` 아래에 상수를 추가한다.

```python
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
```

`send_alert` 를 다음으로 교체한다 (embed 구성부만 변경 · 발송 · 폴백 · 예외 삼킴 로직은 그대로).

```python
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
```

( 주의: 기존 지역 변수명 `url` 이 새 인자와 충돌하므로 webhook 변수명으로 바꾼 것 — 그 외 로직 동일. )

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 전부 PASS (기존 send_alert 폴백 · 예외 삼킴 테스트 포함).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): send_alert 에 url · timestamp · footer 선택 인자

embed 디테일 강화 (SLO-5 · SLO-6) 의 공통 배관을 깐다.
기존 호출부 (Airflow 콜백 포함) 는 무변경으로 동작한다.

- send_alert: url (제목 링크) · timestamp (ISO) · footer 선택 인자, 미지정 시 키 생략
- _discord_ts: naive UTC → <t:epoch:스타일> 마크업 (timezone.utc 명시)
- 상수: ADAPTER_HINTS 원인 후보 매핑 · SPIKE_HINT · 런북 링크 2종
- 지역 변수 url → webhook 개명: 신규 인자와의 충돌 회피

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 2: `build_freshness_alert` 소스당 필드형 개편

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 1 의 `_discord_ts` · `ADAPTER_HINTS` · `RUNBOOK_FRESHNESS`, `bullet_in.quality.SourceFreshness`.
- Produces (Task 4 가 사용): `build_freshness_alert(records, default_hours, *, sources, run_id, checked_at) -> dict`
  — `records` 는 전체 `SourceFreshness` 목록, `sources` 는 `load_sources()` 반환 dict, `checked_at` 은 naive UTC datetime. 반환 dict 는 `send_alert(**alert)` 호환.

- [ ] **Step 1: 기존 테스트 교체 · 신규 테스트 작성**

`tests/test_notify.py` 의 `test_build_freshness_alert_formats_lines_and_threshold_field` 함수를 통째로 삭제하고, 파일 끝에 추가한다.

```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 신규 4건 FAIL — `TypeError: build_freshness_alert() got an unexpected keyword argument 'sources'`.

- [ ] **Step 3: 구현**

`src/bullet_in/notify.py` 의 `build_freshness_alert` 를 통째로 교체한다.

```python
def _source_field_name(source_id: str, sources: dict) -> str:
    name = (sources.get(source_id) or {}).get("display_name")
    return f"{name} ({source_id})" if name else source_id


def build_freshness_alert(records, default_hours: float, *,
                          sources: dict, run_id: str,
                          checked_at: datetime) -> dict:
    """전체 판정 레코드를 받아 stale 소스만 필드로 펼친다 (stale=True 는 age_hours 존재)."""
    breaches = [r for r in records if r.stale]
    no_wm = sum(1 for r in records if r.last_fetched_at is None)
    ok = len(records) - len(breaches) - no_wm
    fields = []
    for b in breaches:
        lines = [f"⏳ {b.age_hours:.1f}h 경과 (임계 {b.threshold_hours:g}h)",
                 f"마지막 수집: {_discord_ts(b.last_fetched_at, 'R')} "
                 f"({_discord_ts(b.last_fetched_at, 'f')})"]
        hint = ADAPTER_HINTS.get((sources.get(b.source_id) or {}).get("adapter"))
        if hint:
            lines.append(f"원인 후보: {hint}")
        fields.append({"name": _source_field_name(b.source_id, sources),
                       "value": "\n".join(lines), "inline": False})
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 전부 PASS.
주의: 이 시점에 run.py 는 아직 구 시그니처로 호출하지만, run.py 는 테스트가 import 하지 않으므로 스위트는 깨지지 않는다 (Task 4 에서 함께 갱신).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): 신선도 embed 를 소스당 필드형으로 개편

알림만 보고 원인 추정 · 심각도 파악 · 런북 이동이 되도록
신선도 경고를 진단 컨텍스트 중심으로 재구성한다.

- 제목: stale 건수 + 클릭 시 freshness 런북 (url)
- description: 감시 전체 조망 (stale · 정상 · 워터마크 없음 카운트)
- stale 소스당 필드: 경과/임계 · 마지막 수집 <t:R> 상대시간 · 원인 후보
- 원인 후보: ADAPTER_HINTS 매핑, 미지 어댑터는 줄 생략
- 메타: run_id 앞 8자 필드 · timestamp=checked_at · footer bullet-in
- 시그니처: breaches → records 전체 + sources · run_id · checked_at

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 3: `build_anomaly_alert` 추세 시퀀스 개편

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 1 의 `ADAPTER_HINTS` · `SPIKE_HINT` · `RUNBOOK_ANOMALY`, Task 2 의 `_source_field_name`, `bullet_in.quality.Anomaly`.
- Produces (Task 4 가 사용): `build_anomaly_alert(anomalies, history_count, *, hist, sources, run_id) -> dict`
  — `hist` 는 run.py 가 조회한 최신순 `list[dict[str, int]]`.

- [ ] **Step 1: 기존 테스트 교체 · 신규 테스트 작성**

`tests/test_notify.py` 의 `test_build_anomaly_alert_formats_lines_and_fields` 함수를 통째로 삭제하고, 파일 끝에 추가한다.

```python
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
    assert "▼ 0건 (평소 ~14)" in field["value"]
    assert "최근: 14 → 12 → 15 → 13 → 14 → (오늘) 0" in field["value"]
    assert "원인 후보: 검색 URL 변경 · 429 차단" in field["value"]
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
    assert "▲ 30건 (평소 ~9)" in spike_field["value"]
    assert "원인 후보: 중복 유입 · 파싱 회귀 의심" in spike_field["value"]
    assert "최근:" not in ghost_field["value"]      # hist 에 없음 → 시퀀스 생략
    assert "원인 후보" not in ghost_field["value"]  # 미지 어댑터 드롭 → 힌트 생략
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 신규 2건 FAIL — `TypeError: build_anomaly_alert() got an unexpected keyword argument 'hist'`.

- [ ] **Step 3: 구현**

`src/bullet_in/notify.py` 의 `build_anomaly_alert` 를 통째로 교체한다.

```python
def build_anomaly_alert(anomalies, history_count: int, *,
                        hist: list[dict], sources: dict, run_id: str) -> dict:
    drops = sum(1 for a in anomalies if a.direction == "drop")
    fields = []
    for a in anomalies:
        arrow = "▼" if a.direction == "drop" else "▲"
        lines = [f"{arrow} {a.today}건 (평소 ~{a.baseline:g})"]
        recent = [h[a.source_id] for h in hist[:5] if a.source_id in h]
        if recent:
            seq = " → ".join(str(n) for n in reversed(recent))
            lines.append(f"최근: {seq} → (오늘) {a.today}")
        hint = (ADAPTER_HINTS.get((sources.get(a.source_id) or {}).get("adapter"))
                if a.direction == "drop" else SPIKE_HINT)
        if hint:
            lines.append(f"원인 후보: {hint}")
        fields.append({"name": _source_field_name(a.source_id, sources),
                       "value": "\n".join(lines), "inline": False})
    fields.append({"name": "회차",
                   "value": f"최근 {history_count}회 기준 · run {run_id[:8]}",
                   "inline": True})
    return {"title": (f"⚠️ 수집량 이상 — {len(anomalies)}건 "
                      f"(드롭 {drops} · 스파이크 {len(anomalies) - drops})"),
            "description": f"최근 {history_count}회 대비 소스별 수집량 이상",
            "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_ANOMALY}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): 수집량 이상 embed 에 추세 시퀀스 · 원인 후보

한 줄 수치만으로는 급락인지 서서히 죽었는지 알 수 없어,
소스당 필드에 최근 회차 흐름과 진단 힌트를 담는다.

- 제목: 이상 건수 (드롭 · 스파이크 분해) + 클릭 시 anomaly 런북
- 소스당 필드: 오늘/평소 + 최근 5회 → (오늘) 시퀀스 (오래된 것부터)
- 원인 후보: 드롭 = ADAPTER_HINTS · 스파이크 = 고정 문구
- 시퀀스 생략: 이상 소스가 hist 에 없으면 (신규 소스) 줄 자체 생략
- 메타: 회차 필드에 기준 회수 + run_id 앞 8자

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 4: run.py 호출 인자 연결

**Files:**
- Modify: `src/bullet_in/run.py`

**Interfaces:**
- Consumes: Task 2 · 3 의 새 빌더 시그니처. run.py 스코프의 기존 값 `hist` · `sources` · `run_id` · `records` · `default_hours` · `checked_at`.
- Produces: 없음 (종단 연결).

- [ ] **Step 1: SLO-6 호출 교체**

`src/bullet_in/run.py` 에서

```python
    if anomalies:
        notify.send_alert(**notify.build_anomaly_alert(anomalies, len(hist)))
```

를 다음으로 교체한다.

```python
    if anomalies:
        notify.send_alert(**notify.build_anomaly_alert(
            anomalies, len(hist), hist=hist, sources=sources, run_id=run_id))
```

- [ ] **Step 2: SLO-5 호출 교체**

같은 파일에서

```python
    if breaches:
        notify.send_alert(**notify.build_freshness_alert(breaches, default_hours))
```

를 다음으로 교체한다 (발송 조건은 그대로 · 인자만 records 전체 + 메타).

```python
    if breaches:
        notify.send_alert(**notify.build_freshness_alert(
            records, default_hours, sources=sources, run_id=run_id,
            checked_at=checked_at))
```

- [ ] **Step 3: 검증**

Run: `uv run python -m py_compile src/bullet_in/run.py && uv run pytest -q`
Expected: compile 성공 · 전체 스위트 PASS (기준선 205 passed · 1 skipped, DB 없으면 integration skip).

- [ ] **Step 4: 커밋**

```bash
git add src/bullet_in/run.py
git commit -m "feat(run): 알림 빌더에 진단 컨텍스트 인자 전달

embed 개편 (notify) 이 요구하는 값을 호출부에서 잇는다.
전부 이미 스코프에 있는 값이라 신규 조회는 없다.

- SLO-6: hist (최근 12회 source_counts) · sources · run_id 전달
- SLO-5: breaches 대신 records 전체 + sources · run_id · checked_at
- 발송 조건 (이상 · stale 있을 때만) 은 무변경

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 5: 런북 알림 해석 갱신

**Files:**
- Modify: `docs/runbook/2026-07-13-freshness-watermark-ops.md`
- Modify: `docs/runbook/2026-07-13-collection-alerts-ops.md`

**Interfaces:**
- Consumes: Task 1–3 의 최종 embed 형식.
- Produces: 없음 (문서). after 이미지 링크는 Task 6 이 이미지와 함께 추가한다.

- [ ] **Step 1: freshness 런북 알림 해석 교체**

`docs/runbook/2026-07-13-freshness-watermark-ops.md` 의 `## 알림 해석` 첫 불릿

```
- **🕰️ 신선도 경고 (주황)** — stale 소스가 하나라도 있으면 한 embed 로 묶여 온다.
  라인 예: `⏳ x_afcstuff: 61.4h 경과 (임계 24h)`.
  `기본 임계` 필드 ( `전역 48h` ) 와 라인의 임계가 다르면 그 소스는 override 적용 상태다.
```

를 다음으로 교체한다 (무알림 불릿은 유지).

```
- **🕰️ 신선도 경고 (주황)** — stale 소스가 하나라도 있으면 한 embed 로 묶여 온다.
  제목이 stale 건수를, description 이 전체 조망 ( `감시 5소스: stale 1 · 정상 3 · 워터마크 없음 1` ) 을 보여준다.
- **소스당 필드** — 경과 시간 · 적용 임계, 마지막 수집 시각 (Discord 상대시간 · 절대시간), 어댑터 기반 원인 후보 한 줄.
  `기본 임계` 필드 ( `전역 48h` ) 와 필드의 임계가 다르면 그 소스는 override 적용 상태다.
- **메타** — `회차` 필드의 run_id 앞 8자로 `pipeline_runs` · `source_freshness` 회차를 특정하고, embed 하단 시각은 검사 시각 (UTC) 이다.
- **제목 클릭** — 이 런북으로 연결된다.
```

- [ ] **Step 2: collection-alerts 런북 소프트 드리프트 불릿 교체**

`docs/runbook/2026-07-13-collection-alerts-ops.md` 의

```
- **⚠️ 수집량 이상 (주황)** — 소프트 드리프트.
  실행은 성공했으나 소스별 수집량이 지난 이력 대비 2σ 밖.
  `▼` 는 드롭 (평소보다 급감, 셀렉터 드리프트 의심) · `▲` 는 스파이크 (급증, 중복 유입 · 페이지 구조 변화 의심) .
  라인 예: `▼ fmkorea: 0건 (평소 ~14)`.
```

를 다음으로 교체한다.

```
- **⚠️ 수집량 이상 (주황)** — 소프트 드리프트.
  실행은 성공했으나 소스별 수집량이 지난 이력 대비 2σ 밖.
  `▼` 는 드롭 (평소보다 급감, 셀렉터 드리프트 의심) · `▲` 는 스파이크 (급증, 중복 유입 · 페이지 구조 변화 의심) .
  제목이 이상 건수 (드롭 · 스파이크 분해) 를 보여주고, 제목 클릭은 이 런북으로 연결된다.
- **소스당 필드** — `▼ 0건 (평소 ~14)` + 최근 5회 → (오늘) 수집량 시퀀스 + 원인 후보 (드롭 = 어댑터 힌트 · 스파이크 = 중복 유입 · 파싱 회귀 의심).
  `회차` 필드의 run_id 앞 8자로 회차를 특정한다.
```

- [ ] **Step 3: 서식 훅 통과 확인**

두 파일 저장 시 PostToolUse 훅이 §2.2 위반을 보고하지 않아야 한다.

- [ ] **Step 4: 커밋**

```bash
git add docs/runbook/2026-07-13-freshness-watermark-ops.md docs/runbook/2026-07-13-collection-alerts-ops.md
git commit -m "docs(runbook): 알림 해석을 개편 embed 형식으로 갱신

embed 가 소스당 필드형으로 바뀌어 두 런북의 해석 절이
실물과 어긋나는 것을 바로잡는다.

- freshness: 제목 건수 · 조망 description · 필드 구성 · run_id 메타 · 제목 클릭
- collection-alerts: 드롭/스파이크 분해 제목 · 시퀀스 · 원인 후보 필드

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 6: 최종 검증 · 스모크 발송 · after 캡처 · PR

**Files:**
- Create: `docs/assets/discord-alert-embed-after.png` (사용자 캡처 수령 후)
- Modify: 두 런북 (after 이미지 링크 추가)

- [ ] **Step 1: 전체 스위트 · 최종 whole-branch 리뷰**

Run: `docker compose up -d && uv run pytest -q`
Expected: 전부 PASS. 이후 SDD 최종 리뷰 진행.

- [ ] **Step 2: 스모크 발송 (실 Discord)**

`.env` 의 `DISCORD_WEBHOOK_URL` 로 개편 embed 2건 (신선도 · 수집량) 을 실발송한다.

```python
from datetime import datetime, timedelta, timezone
from bullet_in import notify
from bullet_in.quality import SourceFreshness, Anomaly

now = datetime.now(timezone.utc).replace(tzinfo=None)
records = [SourceFreshness("x_afcstuff", now - timedelta(hours=61.4), 24.0, 61.4, True),
           SourceFreshness("bbc_sport", now - timedelta(hours=10), 48.0, 10.0, False),
           SourceFreshness("arsenal_official", None, 48.0, None, False)]
sources = {"x_afcstuff": {"display_name": "afcstuff (aggregator)", "adapter": "x_playwright"},
           "bbc_sport": {"display_name": "BBC Sport", "adapter": "html"}}
notify.send_alert(**notify.build_freshness_alert(records, 48, sources=sources,
                                                 run_id="3f2a9c12abcd", checked_at=now))
hist = [{"fmkorea": 14}, {"fmkorea": 13}, {"fmkorea": 15}, {"fmkorea": 12}, {"fmkorea": 14}]
notify.send_alert(**notify.build_anomaly_alert(
    [Anomaly("fmkorea", 0, 14.0, "drop")], 12, hist=hist,
    sources={"fmkorea": {"display_name": "fmkorea 축구 소식통", "adapter": "fmkorea"}},
    run_id="3f2a9c12abcd"))
```

- [ ] **Step 3: after 캡처 수령 · 커밋**

사용자에게 Discord 캡처를 요청해 `docs/assets/discord-alert-embed-after.png` 로 저장하고, 두 런북 알림 해석 절 끝에 이미지 링크를 추가한다.

```
개편 embed 실물: `docs/assets/discord-alert-embed-after.png` (before: `docs/assets/discord-alert-embed-before.png`).
```

```bash
git add docs/assets/discord-alert-embed-after.png docs/runbook/
git commit -m "docs(assets): 개편 알림 embed after 캡처 · 런북 링크

스모크 실발송으로 채집한 개편 embed 실물을 남겨
before 캡처와 비교 증거를 완성한다.

- after 캡처: 신선도 · 수집량 개편 embed (Discord 실렌더링)
- 런북 2종: 알림 해석 절에 before/after 이미지 참조 추가

Refs: docs/superpowers/specs/2026-07-13-alert-embed-detail-design.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: verification-before-completion 후 PR**

- PR 본문 7섹션 · `--body-file` · §4 에 before/after 이미지 (raw.githubusercontent URL) + 스모크 로그.
- 머지 전 PR head = 로컬 HEAD 확인.

```bash
git push -u origin feat/alert-embed-detail
gh pr create --title "feat(notify): 알림 embed 디테일 강화 · 진단 컨텍스트 + 추세" --body-file <body>
gh pr view --json headRefOid
```
