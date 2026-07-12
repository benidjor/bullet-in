# SLO-6 수집 이상 알림 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파이프라인 하드 실패 (예외 crash) 와 소프트 드리프트 (한 소스가 조용히 0건) 를 Discord 로 알린다.

**Architecture:** 공유 `notify.py` 가 Discord embed 전송 (`send_alert`) 과 두 알림의 순수 포맷 빌더 (`build_anomaly_alert` · `build_failure_alert`) 를 담당한다.
소프트 드리프트는 `quality.volume_anomalies` 가 소스별로 탐지해 run.py 가 연결하고, 하드 실패는 Airflow `on_failure_callback` 이 연결한다.
`notify.py` 는 Airflow 를 import 하지 않고 context 를 duck-typing 으로만 읽어 단위 테스트가 DB · Airflow 없이 돈다.

**Tech Stack:** Python 3.11 · httpx (동기 post) · SQLAlchemy · Airflow 3.x · pytest.

## Global Constraints

- **동기 httpx** — `notify.send_alert` 는 run.py (async main) 와 Airflow 콜백 (sync) 양쪽에서 호출되므로 `httpx.post` 동기 API 를 쓴다.
- **알림 실패 무해** — webhook 미설정 · 네트워크 오류는 `logging.warning` 으로 남기고 삼킨다 (파이프라인 · 태스크를 죽이지 않음) .
- **`notify.py` 는 Airflow-free** — airflow 를 import 하지 않는다.
- **커밋 트레일러** — 커밋 본문 끝에 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` 를 넣는다.
- **git 신원** — `benidjor <94089198+benidjor@users.noreply.github.com>` 로 커밋한다.
- **파라미터** — `sigma=2.0` · `min_baseline=3.0` · history 윈도우 12 회.

## 파일 구조

- **Create** `src/bullet_in/notify.py` — Discord embed 전송 + 알림 포맷 빌더.
- **Create** `tests/test_notify.py` — `send_alert` · `build_anomaly_alert` · `build_failure_alert` 단위 테스트.
- **Modify** `src/bullet_in/quality.py` — `Anomaly` dataclass + `volume_anomalies` 순수 함수 추가.
- **Modify** `tests/test_quality.py` — `volume_anomalies` 케이스 추가.
- **Modify** `src/bullet_in/run.py` — 이상탐지 조회 · 알림 연결.
- **Modify** `airflow/dags/bullet_in_daily.py` — `on_failure_callback` 부착.
- **Modify** `tests/test_dag_import.py` — 콜백 부착 검증.

## 스펙과의 차이 (의도된 정련)

- **`build_failure_alert` 를 notify.py 에 둔다** — 스펙은 context 매핑을 DAG 파일에 두자고 했으나, 이 함수는 airflow 를 import 하지 않고 context dict 를 duck-typing 으로만 읽으므로 notify.py 에 둬도 Airflow-free 가 유지된다.
  DAG 파일 직접 import 는 pip `airflow` 패키지와 이름이 충돌해 테스트가 어렵지만, notify.py 함수는 가짜 context 로 바로 테스트된다.
  DAG 파일은 콜백 배선만 담는다.
- **embed `timestamp` 생략** — Discord 가 메시지 수신 시각을 자동 표시하므로 명시 timestamp 는 불필요하다 (YAGNI · 테스트 결정성) .

---

### Task 1: notify.py — Discord embed 전송

**Files:**
- Create: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Produces: `send_alert(title: str, description: str, *, color: int, fields: list[dict] | None = None) -> None` · 상수 `COLOR_ANOMALY = 0xF2A600` · `COLOR_FAILURE = 0xE01E5A` · 모듈 속성 `httpx` (테스트가 monkeypatch) .

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_notify.py`

```python
import logging
import pytest
from bullet_in import notify


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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bullet_in.notify'`.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/notify.py`

```python
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
    except httpx.HTTPError as e:
        logger.warning("알림 발송 오류: %s (%s)", title, e)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: PASS (3 passed) .

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): Discord embed 전송 · webhook 미설정 시 로깅 폴백"
```

---

### Task 2: quality.volume_anomalies — 소스별 이상탐지

**Files:**
- Modify: `src/bullet_in/quality.py`
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: 기존 `volume_anomaly(today, history, sigma)` · `statistics.mean` .
- Produces: `@dataclass Anomaly(source_id: str, today: int, baseline: float, direction: str)` · `volume_anomalies(today_counts: dict[str, int], history_counts: list[dict[str, int]], sigma: float = 2.0, min_baseline: float = 3.0) -> list[Anomaly]` .

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_quality.py` 상단 import 를 아래로 교체하고 테스트를 추가

기존 첫 줄
```python
from bullet_in.quality import success_rate, volume_anomaly
```
을 다음으로 교체한다.
```python
from bullet_in.quality import success_rate, volume_anomaly, volume_anomalies, Anomaly
```

파일 끝에 추가한다.
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_quality.py -v`
Expected: FAIL — `ImportError: cannot import name 'volume_anomalies'`.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/quality.py` 에 추가

파일 상단 import 를 교체한다.
```python
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean, pstdev
```

파일 끝에 추가한다.
```python
@dataclass
class Anomaly:
    source_id: str
    today: int
    baseline: float
    direction: str  # "drop" | "spike"


def volume_anomalies(today_counts: dict[str, int],
                     history_counts: list[dict[str, int]],
                     sigma: float = 2.0, min_baseline: float = 3.0) -> list[Anomaly]:
    source_ids = set(today_counts) | {s for h in history_counts for s in h}
    out: list[Anomaly] = []
    for sid in sorted(source_ids):
        hist = [h.get(sid, 0) for h in history_counts]
        if len(hist) < 2:
            continue
        mu = mean(hist)
        if mu < min_baseline:
            continue
        today = today_counts.get(sid, 0)
        if volume_anomaly(today, hist, sigma):
            out.append(Anomaly(sid, today, round(mu, 1),
                               "drop" if today < mu else "spike"))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_quality.py -v`
Expected: PASS (8 passed — 기존 3 + 신규 5, import 교체로 기존도 유지) .

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(quality): 소스별 수집량 이상탐지 volume_anomalies"
```

---

### Task 3: notify.build_anomaly_alert + run.py 연결

**Files:**
- Modify: `src/bullet_in/notify.py`
- Modify: `tests/test_notify.py`
- Modify: `src/bullet_in/run.py`

**Interfaces:**
- Consumes: `Anomaly` (duck-typed: `.source_id` · `.today` · `.baseline` · `.direction`) · `send_alert` · `COLOR_ANOMALY` · `quality.volume_anomalies` .
- Produces: `build_anomaly_alert(anomalies, history_count: int) -> dict` (`send_alert(**alert)` 로 splat 가능한 `{title, description, color, fields}`) .

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_notify.py` 끝에 추가

```python
from bullet_in.quality import Anomaly


def test_build_anomaly_alert_formats_lines_and_fields():
    anomalies = [Anomaly("fmkorea", 0, 14.0, "drop"),
                 Anomaly("bbc", 30, 9.0, "spike")]
    alert = notify.build_anomaly_alert(anomalies, history_count=12)
    assert alert["title"] == "⚠️ 수집량 이상"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert "▼ fmkorea: 0건 (평소 ~14)" in alert["description"]
    assert "▲ bbc: 30건 (평소 ~9)" in alert["description"]
    assert alert["fields"][0]["value"] == "최근 12회 기준"
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py::test_build_anomaly_alert_formats_lines_and_fields -v`
Expected: FAIL — `AttributeError: module 'bullet_in.notify' has no attribute 'build_anomaly_alert'`.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/notify.py` 끝에 추가

```python
def build_anomaly_alert(anomalies, history_count: int) -> dict:
    lines = "\n".join(
        f"{'▼' if a.direction == 'drop' else '▲'} {a.source_id}: "
        f"{a.today}건 (평소 ~{a.baseline:g})"
        for a in anomalies)
    return {"title": "⚠️ 수집량 이상", "description": lines,
            "color": COLOR_ANOMALY,
            "fields": [{"name": "회차", "value": f"최근 {history_count}회 기준",
                        "inline": True}]}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: PASS (4 passed) .

- [ ] **Step 5: run.py 연결** — `src/bullet_in/run.py`

import 줄 교체 (line 17)
```python
from bullet_in.quality import success_rate
```
를 다음으로 바꾼다.
```python
from bullet_in.quality import success_rate, volume_anomalies
from bullet_in import notify
```

`write_site(rows, sources, "site")` 다음 · `summary = {...}` 앞에 이상탐지 블록을 삽입한다.
```python
    # 수집량 이상탐지 (SLO-6): 지난 12회 source_counts 대비 소스별 드롭 · 스파이크 알림
    with engine.connect() as c:
        hist = [json.loads(s) for s in c.execute(text(
            "SELECT source_counts FROM pipeline_runs "
            "ORDER BY started_at DESC LIMIT 12")).scalars().all() if s]
    anomalies = volume_anomalies(stats["source_counts"], hist)
    if anomalies:
        notify.send_alert(**notify.build_anomaly_alert(anomalies, len(hist)))
```

- [ ] **Step 6: import 스모크 확인**

Run: `uv run python -c "import bullet_in.run"`
Expected: 출력 없음 · exit 0 (구문 · import 오류 없음) .

- [ ] **Step 7: 전체 테스트**

Run: `uv run pytest -q`
Expected: 기존 대비 신규만 늘고 실패 0 (DB 통합은 skip) .

- [ ] **Step 8: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py src/bullet_in/run.py
git commit -m "feat(run): 수집량 이상 시 Discord 알림 연결 (SLO-6)"
```

---

### Task 4: notify.build_failure_alert — Airflow context 매핑

**Files:**
- Modify: `src/bullet_in/notify.py`
- Modify: `tests/test_notify.py`

**Interfaces:**
- Consumes: `COLOR_FAILURE` · context dict (`task_instance` 는 `.dag_id` · `.task_id` · `.try_number` · `.hostname` · `.duration` · `.log_url` 속성 · `run_id` · `exception` 키) .
- Produces: `build_failure_alert(context) -> dict` (`send_alert(**alert)` 로 splat 가능) .

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_notify.py` 끝에 추가

```python
from types import SimpleNamespace


def test_build_failure_alert_maps_context():
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
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py::test_build_failure_alert_maps_context -v`
Expected: FAIL — `AttributeError: module 'bullet_in.notify' has no attribute 'build_failure_alert'`.

- [ ] **Step 3: 최소 구현** — `src/bullet_in/notify.py` 끝에 추가

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: PASS (5 passed) .

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): Airflow 실패 context → embed 필드 매핑"
```

---

### Task 5: DAG on_failure_callback 부착

**Files:**
- Modify: `airflow/dags/bullet_in_daily.py`
- Modify: `tests/test_dag_import.py`

**Interfaces:**
- Consumes: `notify.send_alert` · `notify.build_failure_alert` .
- Produces: `run_pipeline` 태스크의 `on_failure_callback` .

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_dag_import.py` 끝에 추가

```python
def test_failure_callback_attached():
    bag = DagBag(dag_folder="airflow/dags", include_examples=False)
    task = bag.dags["bullet_in_daily"].get_task("run_pipeline")
    assert task.on_failure_callback
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_dag_import.py -v`
Expected: FAIL — `assert task.on_failure_callback` 가 None/빈 값 (또는 airflow 미설치 시 skip) .

- [ ] **Step 3: 최소 구현** — `airflow/dags/bullet_in_daily.py`

`from airflow.providers.standard.operators.python import PythonOperator` 다음에 추가한다.
```python
from bullet_in import notify
```

`_run` 함수 다음에 콜백을 추가한다.
```python
def _notify_failure(context) -> None:
    notify.send_alert(**notify.build_failure_alert(context))
```

`PythonOperator(...)` 를 다음으로 바꾼다.
```python
    PythonOperator(task_id="run_pipeline", python_callable=_run,
                   on_failure_callback=_notify_failure)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_dag_import.py -v`
Expected: PASS (2 passed — 또는 airflow 미설치 시 skip) .

- [ ] **Step 5: 전체 테스트 · 커밋**

Run: `uv run pytest -q`
Expected: 실패 0.
```bash
git add airflow/dags/bullet_in_daily.py tests/test_dag_import.py
git commit -m "feat(dag): run_pipeline 실패 시 Discord 알림 콜백"
```

---

## 최종 검증

- [ ] `uv run pytest -q` 전체 통과 (통합 · airflow 미설치 항목은 skip) .
- [ ] `uv run python -c "import bullet_in.run"` · `uv run python -c "import bullet_in.notify"` 오류 없음.
- [ ] `DISCORD_WEBHOOK_URL` 미설정 상태에서 알림 경로가 WARNING 폴백으로만 동작하는지 로그 확인 (전체 실행은 라이브 E2E 트랙에서) .
