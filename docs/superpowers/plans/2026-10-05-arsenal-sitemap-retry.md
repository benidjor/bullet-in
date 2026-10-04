# 아스날 공식 소스 사이트맵 재시도 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공식 소스 사이트맵 요청이 일시 장애 (시간 초과 · 연결 오류 · 5xx) 를 만나면 10초 뒤 한 번 더 묻고, 재시도가 가린 실패를 수집 현황 화면과 알림에서 읽을 수 있게 한다.

**Architecture:** 어댑터가 사이트맵 요청을 감싸 재시도하고 그 결과를 `funnel` 속성 (키 셋) 에 남긴다.
`run.adapter_funnels` 가 이미 `funnel` 속성을 걷어 `pipeline_runs.fetch_detail.funnels` 에 저장하므로 저장 경로는 새로 만들지 않는다.
읽는 자리는 둘이다.
수집 현황 화면의 SLO 해설 줄 (스냅샷이 실행마다 시도 수와 공식 소스 오류를 함께 읽는다) 과, 재시도까지 실패하거나 404 일 때만 나가는 경향 채널 알림이다.

**Tech Stack:** Python 3.11 · httpx · respx (테스트) · SQLAlchemy · MariaDB 11 (`JSON_VALUE`) · pytest

**Spec:** `docs/superpowers/specs/2026-10-05-arsenal-sitemap-retry-design.md`

**Dry run:** 2026-10-05 에 이 계획서의 코드 블록을 워크트리에 그대로 적용해 전체 테스트를 돌렸고 (1,912 통과 · 1 skip) 되돌렸다.
dry run 은 「도는가」 만 본다. 값이 맞는지는 작업 리뷰가 본다.

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv run --project . --extra dev pytest`) · 전체 테스트는 워크트리 디렉터리에서 돌리고 수집 수를 먼저 본다 (기준 1,889 = 1,888 통과 + 1 skip · 2026-10-05 실측)
- 통합 테스트는 로컬 MariaDB (`docker compose up -d`) 가 있으면 돈다 · 없으면 skip 된다
- 재시도는 사이트맵 요청 한 곳만 · 기사별 GraphQL 요청은 지금처럼 기사 단위로 건너뛴다 (설계 §2.1)
- 재시도 대상은 `httpx.TransportError` 계열과 5xx · 4xx 는 재시도하지 않는다 (설계 §2.1)
- 재시도 1회 · 대기 10초 · 시간 제한 20초 그대로 (설계 §2.2)
- 수집 단계 기록 키는 `sitemap_attempts` (1 또는 2) · `sitemap_sec` (소수 첫째 자리 · 대기 포함) · `sitemap_first_error` (첫 시도 실패 사유 · 없으면 키 없음) (설계 §3.1)
- 첫 시도 실패 사유 표기는 상태 오류면 코드 문자열 (`"503"` · `"404"`), 전송 오류면 예외 이름 (`"ReadTimeout"`)
- 로그 문구 — INFO 「사이트맵 N.N초 · 시도 N」 · WARNING 「사이트맵 1차 실패 (사유) — 10초 뒤 재시도」 (설계 §3.2) · 앞에 기존 로그처럼 `source_id: ` 를 붙인다
- 화면 문구 — 「SLO-2 최근 30회 가운데 사이트맵 재시도로 구한 실행은 N회다.」 (설계 §4.1) · 0회여도 그린다
- 알림은 경향 채널 (`CHANNEL_TREND`) · 「실행」 칸은 `notify.run_label` (설계 §4.2) · 사용자가 읽는 새 문자열에 「회차」 를 쓰지 않는다 (「실행」)
- 커밋은 `benidjor <94089198+benidjor@users.noreply.github.com>` 신원 · 컨벤션 `docs/conventions/2026-06-11-commit-pr-convention.md` · 트레일러는 실행 방식이 정해지면 정한다 (설계 · 구현 모델이 다르면 역할 라벨 두 줄)
- 문서 (`docs/`) 는 컨벤션 §2.2 서식 · `docs/` 는 서술형 · 「급사」 · 「계수기」 라는 말은 쓰지 않는다

## Review Focus

- **첫 시도 5xx · 재시도는 404** — 재시도까지 실패한 경우로 보고 사유를 「503 → 재시도도 404」 로 적는다 (작업 2 의 테스트 `test_alert_reason_when_retry_failed_differently`)
- **httpx 오류 문자열이 길거나 비어 있는 경우** — `HTTPStatusError` 는 「Server error '503 Service Unavailable' for url ...」 처럼 여러 줄이고, 시간 초과는 `str(e)` 가 비어 `gather_all` 이 예외 이름을 넣는다. 알림 사유는 둘 다 짧은 꼴 (`503` · `ReadTimeout`) 이어야 한다 (작업 2 의 테스트 `test_short_fetch_error_*`)
- **같은 어댑터 인스턴스로 `fetch()` 를 두 번 부르는 경우** (`backfill_arsenal` 등) — 둘째 호출의 `funnel` 이 첫 호출의 `sitemap_first_error` 를 끌고 오지 않는다 (작업 1 의 테스트 `test_funnel_resets_between_fetches`)
- **SLO-2 여유를 셀 때 이번 실행** — 알림은 이번 실행의 행이 들어가기 전에 나가므로, 이전 29회에 이번 실행을 더해 30회로 센다. 이력이 짧으면 있는 만큼만 센다 (작업 2 의 테스트 `test_margin_*`)
- **창 밖의 재시도 · 기록 없는 옛 행** — 31회 전의 「재시도로 구함」 은 세지 않고, `fetch_detail` 이 NULL 이거나 공식 소스 기록이 없는 행도 세지 않는다 (작업 3 의 테스트 `test_slo_절은_창_밖의_재시도를_세지_않는다` · 통합 테스트)

## 알고 두는 한계 (고치지 않음)

- 사이트맵이 재시도로 성공한 뒤 같은 실행에서 HTTP 가 아닌 예외 (예: GraphQL 응답에 `data` 키가 없어 `KeyError`) 로 소스가 실패하면, 알림 사유가 「ReadTimeout → 재시도도 KeyError」 처럼 사이트맵 탓으로 읽힌다. 기사별 HTTP 오류는 어댑터 안에서 잡히므로 이 경로는 드물고, 설계의 기록 키 셋으로는 가를 수 없다.
- 사이트맵이 실패한 실행에서 직전 실행에 공식 기사 후보가 있었다면 기존 후보 절벽 알림 (장애 채널) 도 함께 나간다. 지금도 그렇고 이 계획은 그 판정을 바꾸지 않는다. 대신 그 알림의 「수집 단계 기록」 줄이 HTML 4단 사슬로 잘못 그려지지 않게 사이트맵 꼴을 더한다 (작업 2).
- `quality.responded` 는 공식 소스 (`arsenal_api`) 에 수집 단계 기록이 생기면 `no_record` 대신 응답으로 본다. 공식 소스는 신선도 감시 제외 (`freshness_hours: 0` · `quality.py` 205행) 라 이 판정을 쓰는 자리가 없다.

---

### Task 1: 어댑터 — 사이트맵 재시도와 수집 단계 기록

**Files:**
- Modify: `src/bullet_in/adapters/arsenal_api.py` (import · 상수 · 헬퍼 둘 · `__init__` · `_sitemap` 메서드 신설 · `fetch` 의 사이트맵 두 줄)
- Test: `tests/test_arsenal_api_adapter.py` (autouse 대기 0 픽스처 · 새 테스트 여섯 · 기존 `test_sitemap_failure_propagates` 는 그대로 통과해야 한다)

**Interfaces:**
- Produces: `ArsenalApiAdapter.funnel: dict` — `fetch()` 가 사이트맵을 묻기 시작하면 새로 채운다 · 키 `sitemap_attempts: int` · `sitemap_sec: float` · (첫 시도 실패 때만) `sitemap_first_error: str`
- Produces: 모듈 상수 `SITEMAP_RETRY_WAIT_SEC = 10.0` (테스트가 0 으로 바꾼다)

- [ ] **Step 1: 실패 테스트 쓰기** — `tests/test_arsenal_api_adapter.py` 위쪽 import 아래에 픽스처를, 파일 끝에 테스트를 더한다

import 줄 바로 아래:

```python
import pytest
from bullet_in.adapters import arsenal_api


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """재시도 대기 10초를 테스트에서는 0초로 (설계 2026-10-05 §5.1)."""
    monkeypatch.setattr(arsenal_api, "SITEMAP_RETRY_WAIT_SEC", 0)
```

파일 끝:

```python
# --- 사이트맵 재시도 (설계 2026-10-05) ----------------------------------------

def _wide():
    return ArsenalApiAdapter("arsenal_official", window_hours=24 * 365)


def _articles_ok():
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {"getArticle":
        _gql_article("Christos Tzolis signs", ["Men", "Transfer news"])}}))


@respx.mock
def test_sitemap_ok_records_one_attempt():
    _mock_backend(_sitemap(FIXED_NOW_ENTRIES), {"axDM85b0dBUW": _gql_article(
        "Christos Tzolis signs", ["Men", "Transfer news"])})
    a = _wide()
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert a.funnel["sitemap_attempts"] == 1
    assert isinstance(a.funnel["sitemap_sec"], float)
    assert "sitemap_first_error" not in a.funnel


@respx.mock
def test_sitemap_timeout_then_ok_retries_once(caplog):
    route = respx.get(SITEMAP_URL).mock(side_effect=[
        httpx.ReadTimeout("timed out"),
        httpx.Response(200, text=_sitemap(FIXED_NOW_ENTRIES))])
    _articles_ok()
    a = _wide()
    with caplog.at_level("INFO"):
        items = asyncio.run(a.fetch())
    assert route.call_count == 2
    assert len(items) == 1
    assert a.funnel["sitemap_attempts"] == 2
    assert a.funnel["sitemap_first_error"] == "ReadTimeout"
    assert any("사이트맵 1차 실패 (ReadTimeout) — 10초 뒤 재시도" in r.message
               and r.levelname == "WARNING" for r in caplog.records)
    assert any("사이트맵" in r.message and "시도 2" in r.message
               and r.levelname == "INFO" for r in caplog.records)


@respx.mock
def test_sitemap_503_then_ok_records_status_code():
    respx.get(SITEMAP_URL).mock(side_effect=[
        httpx.Response(503), httpx.Response(200, text=_sitemap(FIXED_NOW_ENTRIES))])
    _articles_ok()
    a = _wide()
    items = asyncio.run(a.fetch())
    assert len(items) == 1
    assert a.funnel["sitemap_attempts"] == 2
    assert a.funnel["sitemap_first_error"] == "503"


@respx.mock
def test_sitemap_404_fails_without_retry():
    route = respx.get(SITEMAP_URL).mock(return_value=httpx.Response(404))
    a = _wide()
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(a.fetch())
    assert route.call_count == 1
    assert a.funnel["sitemap_attempts"] == 1
    assert a.funnel["sitemap_first_error"] == "404"
    assert "sitemap_sec" in a.funnel


@respx.mock
def test_sitemap_timeout_twice_raises_and_keeps_the_record():
    route = respx.get(SITEMAP_URL).mock(side_effect=[
        httpx.ReadTimeout("timed out"), httpx.ReadTimeout("timed out")])
    a = _wide()
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(a.fetch())
    assert route.call_count == 2
    assert a.funnel["sitemap_attempts"] == 2
    assert a.funnel["sitemap_first_error"] == "ReadTimeout"


@respx.mock
def test_funnel_resets_between_fetches():
    """같은 인스턴스를 다시 부르면 지난 호출의 첫 실패 사유를 끌고 오지 않는다."""
    respx.get(SITEMAP_URL).mock(side_effect=[
        httpx.ReadTimeout("timed out"),
        httpx.Response(200, text=_sitemap(FIXED_NOW_ENTRIES)),
        httpx.Response(200, text=_sitemap(FIXED_NOW_ENTRIES))])
    _articles_ok()
    a = _wide()
    asyncio.run(a.fetch())
    assert a.funnel["sitemap_attempts"] == 2
    asyncio.run(a.fetch())
    assert a.funnel["sitemap_attempts"] == 1
    assert "sitemap_first_error" not in a.funnel
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py -q`
Expected: 새 테스트 여섯이 `AttributeError: 'ArsenalApiAdapter' object has no attribute 'funnel'` 또는 재시도 없음으로 FAIL · 기존 테스트는 PASS

- [ ] **Step 3: 구현** — `src/bullet_in/adapters/arsenal_api.py`

import 블록을 이렇게 바꾼다 (`asyncio` · `time` 추가):

```python
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import re
import time
import httpx
```

`WINDOW_HOURS = 48.0` 아래에 더한다:

```python
# 사이트맵이 가끔 20초를 넘기거나 503 · 404 를 준다 (설계 2026-10-05 §1.3 · 627회 중 8회).
# 일시 장애만 한 번 더 묻는다 — 최악 소요 20 + 10 + 20 = 50초 (설계 §2.2).
SITEMAP_RETRY_WAIT_SEC = 10.0


def _error_label(e: httpx.HTTPError) -> str:
    """기록 · 로그용 짧은 사유 — 상태 오류는 코드 (`503`), 전송 오류는 예외 이름 (`ReadTimeout`)."""
    if isinstance(e, httpx.HTTPStatusError):
        return str(e.response.status_code)
    return type(e).__name__


def _retryable(e: httpx.HTTPError) -> bool:
    """시간 초과 · 연결 오류와 5xx 만 다시 묻는다.

    4xx 는 주소가 바뀐 구조적 신호일 수 있어 재시도로 덮지 않는다 (설계 §2.1)."""
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code >= 500
    return isinstance(e, httpx.TransportError)
```

`__init__` 끝에 한 줄:

```python
        self.funnel: dict = {}   # 사이트맵 시도 기록 — run.adapter_funnels 가 실행 행에 남긴다 (설계 §3.1)
```

`_gql` 메서드 아래에 메서드 둘을 더한다:

```python
    async def _get_sitemap(self, client: httpx.AsyncClient) -> str:
        r = await client.get(SITEMAP_URL)
        r.raise_for_status()
        return r.text

    async def _sitemap(self, client: httpx.AsyncClient) -> str:
        """사이트맵 본문 — 일시 장애면 10초 뒤 한 번 더 묻는다.

        끝내 실패하면 예외를 그대로 낸다 (조용한 폴백 없음). 기록은 예외를 내기 전에
        채워 실패한 실행에도 남는다 (설계 §3.1)."""
        t0 = time.perf_counter()
        self.funnel = {"sitemap_attempts": 1}
        try:
            try:
                return await self._get_sitemap(client)
            except httpx.HTTPError as e:
                self.funnel["sitemap_first_error"] = _error_label(e)
                if not _retryable(e):
                    raise
                # 문구는 리터럴이다 — 테스트가 대기를 0 으로 바꿔도 설계 §3.2 문구를 검사할 수 있게
                log.warning("%s: 사이트맵 1차 실패 (%s) — 10초 뒤 재시도", self.source_id,
                            self.funnel["sitemap_first_error"])
            await asyncio.sleep(SITEMAP_RETRY_WAIT_SEC)
            self.funnel["sitemap_attempts"] = 2
            return await self._get_sitemap(client)
        finally:
            self.funnel["sitemap_sec"] = round(time.perf_counter() - t0, 1)
            log.info("%s: 사이트맵 %.1f초 · 시도 %d", self.source_id,
                     self.funnel["sitemap_sec"], self.funnel["sitemap_attempts"])
```

상수 `SITEMAP_RETRY_WAIT_SEC` 정의 바로 위 주석 끝에 한 줄을 더한다: `# 바꾸면 _sitemap 의 경고 문구 「10초 뒤 재시도」 도 함께 바꾼다.`

`fetch` 안의 사이트맵 세 줄을

```python
            r = await c.get(SITEMAP_URL)
            r.raise_for_status()  # sitemap 장애 = 에러로 전파 (조용한 폴백 없음)
            urls = _sitemap_candidates(r.text, now, self.window_hours)
```

이렇게 바꾼다:

```python
            # sitemap 장애 = 일시 장애면 한 번 더, 그래도 실패면 에러로 전파 (조용한 폴백 없음)
            urls = _sitemap_candidates(await self._sitemap(c), now, self.window_hours)
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_arsenal_api_adapter.py tests/test_backfill_arsenal.py -q`
Expected: 전부 PASS (기존 `test_sitemap_failure_propagates` 는 503 두 번으로 재시도 뒤 같은 예외를 내므로 그대로 통과)

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/adapters/arsenal_api.py tests/test_arsenal_api_adapter.py
git commit -m "feat(collect): 공식 소스 사이트맵 일시 장애에 1회 재시도와 시도 기록"
```

(본문 · 트레일러는 컨벤션대로)

---

### Task 2: 알림 — 재시도까지 실패하거나 404 일 때 경향 채널로

**Files:**
- Modify: `src/bullet_in/notify.py` (`_funnel_lines` 에 사이트맵 꼴 · `_short_fetch_error` · `build_sitemap_failure_alert` 신설)
- Modify: `src/bullet_in/run.py` (import `math` · ops_view 상수 · `RECENT_RATES_SQL` · `slo2_margin` · `sitemap_alert_payloads` · `collect` 배선)
- Test: `tests/test_notify.py` (끝에 더함) · `tests/test_run_sitemap_alert.py` (신설) · `tests/test_run_cliff_alert.py` (끝에 하나 더함)

**Interfaces:**
- Consumes: 작업 1 의 `funnel` 키 (`sitemap_attempts` · `sitemap_sec` · `sitemap_first_error`) · `gather_all` 의 `errors: dict[str, str]` (값 = `str(e) or type(e).__name__`)
- Produces: `notify.build_sitemap_failure_alert(funnel: dict, error: str | None, *, failed_runs: int, allowed_runs: int, window: int, run_id: str) -> dict | None`
- Produces: `run.slo2_margin(previous_rates: list[float], current_rate: float, n_sources: int) -> tuple[int, int, int]` — (소스 실패 실행 수, 충족 한도, 창 길이)
- Produces: `run.sitemap_alert_payloads(adapters, errors: dict, *, previous_rates: list[float], run_id: str) -> list[dict]`

- [ ] **Step 1: 실패 테스트 쓰기 — notify** — `tests/test_notify.py` 끝에 더한다

```python
from bullet_in.notify import (build_sitemap_failure_alert, _short_fetch_error, _funnel_lines,
                              CHANNEL_TREND)

RID = "scheduled__2026-10-04T18:00:00+00:00"


def test_short_fetch_error_takes_the_status_code_from_httpx_message():
    err = ("Server error '503 Service Unavailable' for url "
           "'https://www.arsenal.com/sitemaps/articles/1/sitemap.xml'\n"
           "For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/503")
    assert _short_fetch_error(err) == "503"


def test_short_fetch_error_keeps_exception_name_and_cuts_long_lines():
    assert _short_fetch_error("ReadTimeout") == "ReadTimeout"
    assert _short_fetch_error("x" * 200 + "\nsecond") == "x" * 80
    assert _short_fetch_error("") == "알 수 없음"


def test_sitemap_alert_when_retry_also_failed():
    p = build_sitemap_failure_alert(
        {"sitemap_attempts": 2, "sitemap_sec": 50.1, "sitemap_first_error": "ReadTimeout"},
        "ReadTimeout", failed_runs=3, allowed_runs=2, window=30, run_id=RID)
    assert p["title"] == "⚠️ 공식 소스 사이트맵 수집 실패 — 이번 실행 공식 기사 0건"
    assert "사유: ReadTimeout → 재시도도 ReadTimeout" in p["description"]
    assert p["channel"] == CHANNEL_TREND
    fields = {f["name"]: f["value"] for f in p["fields"]}
    assert fields["SLO-2 여유"] == "최근 30회 중 소스 실패 3회 (2회까지 충족)"
    assert fields["실행"] == "10-05 03:00 (UTC 10-04 18:00)"
    assert "회차" not in str(p)


def test_alert_reason_when_retry_failed_differently():
    p = build_sitemap_failure_alert(
        {"sitemap_attempts": 2, "sitemap_first_error": "503"},
        "Client error '404 Not Found' for url 'https://www.arsenal.com/sitemaps/articles/1/sitemap.xml'",
        failed_runs=1, allowed_runs=2, window=30, run_id=RID)
    assert "사유: 503 → 재시도도 404" in p["description"]


def test_sitemap_alert_for_404_without_retry():
    p = build_sitemap_failure_alert(
        {"sitemap_attempts": 1, "sitemap_first_error": "404"},
        "Client error '404 Not Found' for url 'https://www.arsenal.com/sitemaps/articles/1/sitemap.xml'",
        failed_runs=1, allowed_runs=2, window=30, run_id=RID)
    assert "사유: 404 (재시도 안 함)" in p["description"]
    assert "주소" in p["description"]
    assert p["channel"] == CHANNEL_TREND


def test_no_sitemap_alert_when_retry_rescued_or_never_failed():
    rescued = {"sitemap_attempts": 2, "sitemap_first_error": "ReadTimeout"}
    assert build_sitemap_failure_alert(rescued, None, failed_runs=0, allowed_runs=2,
                                       window=30, run_id=RID) is None
    clean = {"sitemap_attempts": 1, "sitemap_sec": 0.4}
    assert build_sitemap_failure_alert(clean, None, failed_runs=0, allowed_runs=2,
                                       window=30, run_id=RID) is None
    # 사이트맵은 첫 시도에 받았는데 다른 이유로 소스가 실패 — 사이트맵 알림이 아니다
    assert build_sitemap_failure_alert(clean, "KeyError", failed_runs=1, allowed_runs=2,
                                       window=30, run_id=RID) is None


def test_funnel_lines_reads_sitemap_record():
    assert _funnel_lines({"sitemap_attempts": 2, "sitemap_sec": 10.4,
                          "sitemap_first_error": "ReadTimeout"}) == [
        "수집 단계 기록: 사이트맵 시도 2 · 10.4초 · 1차 실패 ReadTimeout"]
    assert _funnel_lines({"sitemap_attempts": 1, "sitemap_sec": 0.4}) == [
        "수집 단계 기록: 사이트맵 시도 1 · 0.4초"]
```

- [ ] **Step 2: 실패 테스트 쓰기 — run** — `tests/test_run_sitemap_alert.py` 신설

```python
"""공식 소스 사이트맵 실패 알림의 배선 — SLO-2 여유 셈과 어댑터 걷기 (설계 2026-10-05 §4.2)."""
from bullet_in.run import sitemap_alert_payloads, slo2_margin

RID = "scheduled__2026-10-04T18:00:00+00:00"


class _Adapter:
    def __init__(self, source_id, funnel=None):
        self.source_id = source_id
        if funnel is not None:
            self.funnel = funnel


SEVEN = [_Adapter(f"s{i}") for i in range(7)]          # funnel 없는 소스 일곱 + 공식 소스 = 8


def test_margin_counts_the_current_run_and_the_29_before_it():
    # 직전 29회 중 실패 2 (0.875) · 30번째 전 실패 1 은 창 밖 · 이번 실행도 실패
    prev = [0.875, 0.875] + [1.0] * 27 + [0.875]
    assert slo2_margin(prev, 0.875, 8) == (3, 2, 30)   # 한도 = floor(30 × 0.01 × 8) = 2


def test_margin_with_short_history():
    assert slo2_margin([1.0, 0.875], 0.875, 8) == (2, 2, 3)
    assert slo2_margin([], 1.0, 8) == (0, 2, 1)


def test_payload_when_official_sitemap_failed_after_retry():
    off = _Adapter("arsenal_official", {"sitemap_attempts": 2, "sitemap_sec": 50.1,
                                        "sitemap_first_error": "ReadTimeout"})
    out = sitemap_alert_payloads(SEVEN + [off], {"arsenal_official": "ReadTimeout"},
                                 previous_rates=[1.0] * 29, run_id=RID)
    assert len(out) == 1
    fields = {f["name"]: f["value"] for f in out[0]["fields"]}
    assert fields["SLO-2 여유"] == "최근 30회 중 소스 실패 1회 (2회까지 충족)"


def test_no_payload_when_retry_rescued():
    off = _Adapter("arsenal_official", {"sitemap_attempts": 2, "sitemap_first_error": "503"})
    assert sitemap_alert_payloads(SEVEN + [off], {}, previous_rates=[1.0] * 29, run_id=RID) == []


def test_other_sources_errors_do_not_make_a_sitemap_alert():
    """funnel 이 없거나 사이트맵 키가 없는 어댑터는 건너뛴다."""
    html = _Adapter("goal", {"selected": 3, "deduped": 3, "titled": 3, "passed": 1})
    assert sitemap_alert_payloads(SEVEN + [html], {"goal": "boom", "s0": "x"},
                                  previous_rates=[1.0] * 29, run_id=RID) == []
```

`tests/test_run_cliff_alert.py` 끝에 하나 더한다:

```python
def test_cliff_payload_draws_the_sitemap_record_not_the_html_chain():
    """공식 소스가 절벽에 걸려도 수집 단계 기록이 HTML 4단 사슬 (목록 0 → …) 로 그려지지 않는다."""
    off = _Adapter("arsenal_official")
    off.funnel = {"sitemap_attempts": 2, "sitemap_sec": 50.1, "sitemap_first_error": "ReadTimeout"}
    payload = cliff_alert_payload(
        {}, [{"arsenal_official": 1}], adapters=[off],
        sources={"arsenal_official": {"display_name": "Arsenal.com"}},
        success_rate=0.875, run_id="r")
    text = str(payload["fields"])
    assert "사이트맵 시도 2" in text
    assert "목록 0" not in text
```

- [ ] **Step 3: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_notify.py tests/test_run_sitemap_alert.py tests/test_run_cliff_alert.py -q`
Expected: 새 테스트가 `ImportError` (`build_sitemap_failure_alert` · `sitemap_alert_payloads` 없음) 로 FAIL

- [ ] **Step 4: 구현 — notify** — `src/bullet_in/notify.py`

`_funnel_lines` 의 `if not funnel: return []` 바로 아래에 더한다:

```python
    if "sitemap_attempts" in funnel:
        line = (f"수집 단계 기록: 사이트맵 시도 {funnel['sitemap_attempts']} · "
                f"{funnel.get('sitemap_sec', 0)}초")
        if funnel.get("sitemap_first_error"):
            line += f" · 1차 실패 {funnel['sitemap_first_error']}"
        return [line]
```

docstring 의 「어댑터마다 키가 다르다 — HTML 은 네 단계, X 는 타임라인 트윗, fmkorea 는 검색.」 끝에 「공식 소스는 사이트맵 시도.」 를 이어 붙인다.

`build_coverage_alert` 함수 바로 뒤에 더한다:

```python
# httpx 상태 오류 문자열 — 「Server error '503 Service Unavailable' for url '…'」
_HTTP_STATUS_IN_ERROR = re.compile(r"'(\d{3}) ")


def _short_fetch_error(err: str) -> str:
    """수집 오류 문자열을 짧은 사유로 — httpx 상태 오류는 코드만, 나머지는 첫 줄 80자."""
    if not err:
        return "알 수 없음"
    m = _HTTP_STATUS_IN_ERROR.search(err)
    return m.group(1) if m else err.splitlines()[0][:80]


def build_sitemap_failure_alert(funnel: dict, error: str | None, *, failed_runs: int,
                                allowed_runs: int, window: int, run_id: str) -> dict | None:
    """공식 소스 사이트맵이 끝내 실패한 실행의 알림 (설계 2026-10-05 §4.2).

    재시도로 구했거나 사이트맵 첫 시도가 성공했으면 None — 앞의 것은 받는 사람이 할 일이
    없어 수집 현황 화면 한 줄에서 세고, 뒤의 것은 사이트맵 장애가 아니다.
    SLO-2 여유를 함께 실어 「이번 실패로 미달이 되는가」 를 알림만 보고 판단하게 한다."""
    first = funnel.get("sitemap_first_error")
    if not error or not first:
        return None
    if int(funnel.get("sitemap_attempts", 1)) >= 2:
        reason = f"{first} → 재시도도 {_short_fetch_error(error)}"
        todo = "아스날 공식 사이트 쪽 일시 장애로 보입니다 — 다음 실행에서 대개 풀립니다"
    else:
        reason = f"{first} (재시도 안 함)"
        todo = "사이트맵 주소가 바뀌었을 수 있습니다 — 주소를 확인해 주세요"
    return {"title": "⚠️ 공식 소스 사이트맵 수집 실패 — 이번 실행 공식 기사 0건",
            "description": f"사유: {reason}\n{todo}",
            "color": COLOR_FAILURE,
            "fields": [{"name": "SLO-2 여유",
                        "value": f"최근 {window}회 중 소스 실패 {failed_runs}회 "
                                 f"({allowed_runs}회까지 충족)",
                        "inline": False},
                       {"name": "실행", "value": run_label(run_id), "inline": True}],
            "channel": CHANNEL_TREND}
```

- [ ] **Step 5: 구현 — run** — `src/bullet_in/run.py`

import 첫 줄에 `math` 를 더한다:

```python
import argparse, asyncio, json, logging, math, os, time, uuid, yaml
```

`from bullet_in.serve.render import (...)` 블록 바로 아래에 더한다:

```python
from bullet_in.serve.ops_view import RECENT_RUNS, SLO2_TARGET
```

`VOLUME_HISTORY_SQL` 정의 바로 아래에 더한다:

```python
# SLO-2 여유 — 이번 행은 collect 끝에 들어가므로 직전 마감된 실행만 읽고 이번 실행을 더한다.
RECENT_RATES_SQL = ("SELECT success_rate FROM pipeline_runs WHERE finished_at IS NOT NULL "
                    "AND run_id <> :rid ORDER BY started_at DESC LIMIT :n")
```

`cliff_alert_payload` 함수 바로 뒤에 더한다:

```python
def slo2_margin(previous_rates: list[float], current_rate: float,
                n_sources: int) -> tuple[int, int, int]:
    """(소스 실패 실행 수, 충족 한도, 창 길이) — 수집 현황 화면의 SLO-2 와 같은 창 (설계 2026-10-05 §4.2).

    창 = 이번 실행 + 직전 29회. 「소스 실패」 는 성공률이 1 보다 작은 실행이다.
    한도는 실행마다 소스 하나가 실패한다고 보고 센다 — 30 × (1 − 0.99) × 8 = 2.4 → 2."""
    window = [current_rate, *previous_rates[:RECENT_RUNS - 1]]
    failed = sum(1 for r in window if r < 1)
    allowed = math.floor(round(RECENT_RUNS * (1 - SLO2_TARGET) * n_sources, 6))
    return failed, allowed, len(window)


def sitemap_alert_payloads(adapters, errors: dict, *, previous_rates: list[float],
                           run_id: str) -> list[dict]:
    """사이트맵 시도 기록을 내놓는 어댑터 가운데 사이트맵이 끝내 실패한 것만 알림으로."""
    failed, allowed, window = slo2_margin(
        previous_rates, success_rate(len(adapters), len(errors)), len(adapters))
    out = []
    for a in adapters:
        funnel = getattr(a, "funnel", None) or {}
        if "sitemap_attempts" not in funnel:
            continue
        p = notify.build_sitemap_failure_alert(
            funnel, errors.get(a.source_id), failed_runs=failed, allowed_runs=allowed,
            window=window, run_id=run_id)
        if p:
            out.append(p)
    return out
```

`collect` 안, 「공홈 커버리지 감시」 `for` 문 바로 뒤에 더한다:

```python
    # 공식 소스 사이트맵이 재시도까지 실패하거나 404 면 알림 (설계 2026-10-05 §4.2).
    # 재시도로 구한 실행은 알림 없이 수집 현황 화면 한 줄에서 센다. 판정 · 발송 실패가
    # 실행을 멈추지 않게 감싼다 (후보 절벽 알림과 같은 격리).
    try:
        with engine.connect() as c:
            prev_rates = [float(r) for r in c.execute(
                text(RECENT_RATES_SQL), {"rid": run_id, "n": RECENT_RUNS - 1}).scalars().all()]
        for p in sitemap_alert_payloads(adapters, errors, previous_rates=prev_rates,
                                        run_id=run_id):
            notify.send_alert(**p)
    except Exception:
        logging.getLogger(__name__).warning(
            "사이트맵 실패 알림 판정 실패 — 이번 실행 건너뜀 (수집에는 영향 없음)", exc_info=True)
```

`adapter_funnels` docstring 의 「rss · x_playwright 는 발견 단계가 달라 억지가 된다.」 는 건드리지 않는다 (지난 리뷰에서 미뤄 둔 항목 · 범위 밖).

- [ ] **Step 6: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_notify.py tests/test_run_sitemap_alert.py tests/test_run_cliff_alert.py tests/test_run_stages.py -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/notify.py src/bullet_in/run.py tests/test_notify.py tests/test_run_sitemap_alert.py tests/test_run_cliff_alert.py
git commit -m "feat(notify): 공식 소스 사이트맵이 재시도까지 실패하거나 404 면 경향 채널 알림"
```

---

### Task 3: 수집 현황 화면 — 재시도로 구한 실행 수 한 줄

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py` (상수 `SITEMAP_SOURCE` · `ops_snapshot` 의 `runs_all` SELECT 두 칸 · 후처리 한 줄)
- Modify: `src/bullet_in/serve/ops_view.py` (`_sitemap_rescued` 신설 · `_slo` 에 `recent` 인자 · `build_ops_view` 호출)
- Test: `tests/test_ops_view.py` (끝에 넷) · `tests/integration/test_ops_snapshot.py` (끝에 하나)

**Interfaces:**
- Consumes: 작업 1 의 `fetch_detail.funnels.arsenal_official.sitemap_attempts` · 기존 `fetch_detail.errors.arsenal_official`
- Produces: `ops_snapshot()["runs_all"][i]` 에 키 둘 — `sitemap_attempts: int | None` · `official_error: str | None`
- Produces: `ops_view._sitemap_rescued(recent: list[dict]) -> int`

- [ ] **Step 1: 실패 테스트 쓰기 — 뷰모델** — `tests/test_ops_view.py` 끝에 더한다

```python
def _slo_texts(snapshot):
    return [t for t, _ in _flat(_view(snapshot))[0]["insights"]]


def _sm(run, attempts, error=None):
    return dict(run, sitemap_attempts=attempts, official_error=error)


def test_slo_절은_사이트맵_재시도로_구한_실행_수를_적는다():
    runs = [_run("e", datetime(2026, 9, 3, 21, 0), 1, 0),                              # 기록 없는 옛 행
            _sm(_run("a", datetime(2026, 9, 4, 0, 0), 1, 0), 2),                       # 구함
            _sm(_run("b", datetime(2026, 9, 4, 3, 0), 1, 0), 2),                       # 구함
            _sm(_run("c", datetime(2026, 9, 4, 6, 0), 1, 0, err=1, sr=0.875), 2, "ReadTimeout"),  # 재시도도 실패
            _sm(_run("d", datetime(2026, 9, 4, 9, 0), 1, 0), 1)]                       # 첫 시도에 받음
    assert "SLO-2 최근 5회 가운데 사이트맵 재시도로 구한 실행은 2회다." in _slo_texts(dict(SNAPSHOT, runs_all=runs))


def test_slo_절은_재시도가_없어도_0회_줄을_그린다():
    assert "SLO-2 최근 4회 가운데 사이트맵 재시도로 구한 실행은 0회다." in _slo_texts(SNAPSHOT)


def test_slo_절은_창_밖의_재시도를_세지_않는다():
    base = datetime(2026, 8, 30, 0, 0)
    runs = [_sm(_run("old", base, 1, 0), 2)]                                           # 31번째 전 · 창 밖
    runs += [_sm(_run(f"r{i}", base + timedelta(hours=3 * (i + 1)), 1, 0), 1) for i in range(30)]
    assert "SLO-2 최근 30회 가운데 사이트맵 재시도로 구한 실행은 0회다." in _slo_texts(dict(SNAPSHOT, runs_all=runs))


def test_빈_스냅샷이면_사이트맵_줄이_없다():
    assert not any("사이트맵" in t for t in _slo_texts(EMPTY))
```

파일 맨 위 import 를 `from datetime import datetime, timedelta` 로 바꾼다.

- [ ] **Step 2: 실패 테스트 쓰기 — 스냅샷 (통합)** — `tests/integration/test_ops_snapshot.py` 끝에 더한다

```python
def test_ops_snapshot_reads_sitemap_attempts_and_official_error(engine):
    """실행마다 공식 소스 사이트맵 시도 수와 공식 소스 오류를 읽는다 (설계 2026-10-05 §4.1).
    fetch_detail 이 NULL 이거나 공식 소스 기록이 없는 행은 둘 다 None."""
    _seed_runs(engine, 4)
    details = {
        "run-000": None,
        "run-001": {"errors": {}, "funnels": {"bbc_sport": {"entries": 3}}},
        "run-002": {"errors": {}, "funnels": {"arsenal_official": {
            "sitemap_attempts": 2, "sitemap_sec": 10.4, "sitemap_first_error": "ReadTimeout"}}},
        "run-003": {"errors": {"arsenal_official": "ReadTimeout"}, "funnels": {"arsenal_official": {
            "sitemap_attempts": 2, "sitemap_sec": 50.1, "sitemap_first_error": "ReadTimeout"}}}}
    with engine.begin() as c:
        for rid, d in details.items():
            c.execute(text("UPDATE pipeline_runs SET fetch_detail=:d WHERE run_id=:rid"),
                      {"d": json.dumps(d) if d is not None else None, "rid": rid})
    runs = MartStore(engine).ops_snapshot()["runs_all"]
    assert [(r["sitemap_attempts"], r["official_error"]) for r in runs] == [
        (None, None), (None, None), (2, None), (2, "ReadTimeout")]
```

- [ ] **Step 3: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_ops_view.py tests/integration/test_ops_snapshot.py -q`
Expected: 새 뷰모델 테스트 셋 (`구한_실행_수` · `0회_줄` · `창_밖`) 과 통합 테스트가 FAIL (`KeyError: 'sitemap_attempts'` 또는 줄 없음) · `빈_스냅샷` 은 PASS 일 수 있다

- [ ] **Step 4: 구현 — 스냅샷** — `src/bullet_in/storage/mariadb.py`

모듈 위쪽 상수들 (`OPS_EPOCH` 근처) 에 더한다:

```python
# 사이트맵 재시도 기록을 남기는 소스 (설계 2026-10-05 §3.1) — 수집 현황 화면이 실행마다 읽는다.
SITEMAP_SOURCE = "arsenal_official"
```

`ops_snapshot` 의 `runs_all` SELECT 를 이렇게 바꾼다:

```python
            runs_all = [dict(r) for r in c.execute(text(
                "SELECT run_id,started_at,duration_sec,fetch_duration_sec,"
                "source_counts,new_count,dup_count,error_count,success_rate,"
                f"JSON_VALUE(fetch_detail,'$.funnels.{SITEMAP_SOURCE}.sitemap_attempts') AS sitemap_attempts,"
                f"JSON_VALUE(fetch_detail,'$.errors.{SITEMAP_SOURCE}') AS official_error "
                "FROM pipeline_runs WHERE finished_at IS NOT NULL AND started_at >= :epoch "
                "ORDER BY started_at"), {"epoch": OPS_EPOCH}).mappings().all()]
```

아래 `for r in runs_all:` 후처리 블록에 한 줄을 더한다 (`JSON_VALUE` 는 문자열을 돌려준다):

```python
        for r in runs_all:
            r["source_counts"] = (json.loads(r["source_counts"])
                                  if r["source_counts"] else {})
            r["sitemap_attempts"] = (int(r["sitemap_attempts"])
                                     if r["sitemap_attempts"] is not None else None)
```

- [ ] **Step 5: 구현 — 뷰모델** — `src/bullet_in/serve/ops_view.py`

`_slo_rows` 바로 앞에 더한다:

```python
def _sitemap_rescued(recent) -> int:
    """SLO-2 창에서 사이트맵 재시도로 구한 실행 수 (설계 2026-10-05 §4.1).

    시도 2 이고 공식 소스 오류가 없는 실행이다. 기록 키가 없는 옛 실행은 세지 않는다."""
    return sum(1 for r in recent
               if r.get("sitemap_attempts") == 2 and not r.get("official_error"))
```

`_slo` 의 서명과 본문을 바꾼다:

```python
def _slo(rows, gate, completion: dict | None = None, recent=None):
```

`if bad:` 블록 바로 뒤에 더한다:

```python
    if recent:
        # 재시도가 가린 실패 — SLO-2 숫자가 좋아 보여도 무엇이 가려졌는지 같은 화면에서 읽힌다.
        ins.append((f"SLO-2 최근 {len(recent)}회 가운데 사이트맵 재시도로 구한 실행은 "
                    f"{_sitemap_rescued(recent)}회다.", []))
```

`build_ops_view` 의 `_slo(slo, gate, completion),` 을 `_slo(slo, gate, completion, recent),` 로 바꾼다.

- [ ] **Step 6: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_ops_view.py tests/test_serve_ops.py tests/integration/test_ops_snapshot.py -q`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py src/bullet_in/serve/ops_view.py tests/test_ops_view.py tests/integration/test_ops_snapshot.py
git commit -m "feat(ops): 수집 현황 SLO 해설에 사이트맵 재시도로 구한 실행 수"
```

---

## 마무리 (컨트롤러가 직접)

- [ ] 전체 테스트 — 워크트리 디렉터리에서 `uv run --project . --extra dev pytest -q` · 기대 = 1,912 통과 + 1 skip (기준 1,889 + 새 테스트 24 = 작업 1 의 6 · 작업 2 의 13 · 작업 3 의 5 · 2026-10-05 계획서 dry run 실측)
- [ ] 머지 전 라이브 확인 (설계 §5.2) — 공식 소스 어댑터 하나만 한 번 `fetch()` 하고 출력은 파일로 받는다

```bash
uv run --project . python -c "
import asyncio, json
from bullet_in.adapters.arsenal_api import ArsenalApiAdapter
a = ArsenalApiAdapter('arsenal_official')
items = asyncio.run(a.fetch())
print(json.dumps({'funnel': a.funnel, 'coverage': a.coverage, 'items': len(items)}, ensure_ascii=False))
" 2>&1 | tee "$SCRATCH/sitemap-live-fetch.txt"
```

기대 = `funnel` 이 `{"sitemap_attempts": 1, "sitemap_sec": …}` 이고 `sitemap_first_error` 가 없다. 출력 확인을 위해 다시 돌리지 않는다.

- [ ] 최종 전체 리뷰 · PR (본문 humanize-korean fast 1회 → `check-pr-format.py` → 통과에 묶어 push · PR 생성)
- [ ] 머지 뒤 첫 실행 — `fetch_detail.funnels.arsenal_official` 에 `sitemap_attempts: 1` 이 남는지 · 수집 현황 화면에 「사이트맵 재시도로 구한 실행은 0회다」 줄이 있는지
