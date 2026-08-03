# 수집 경로 차단 알림 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 직전 회차까지 후보가 있던 소스가 이번 회차에 0건이 되는 전이와 워치리스트 검색 전원 실패를 Discord 알림으로 승격한다.

**Architecture:** 판정은 `quality.py` 의 순수 함수가 맡고, 문구는 `notify.py` 빌더가 만들며, 배선은 `run.py` 와 `watchlist_fmkorea.py` 가 각각 담당한다. fmkorea 어댑터는 이미 세고 있는 검색 실패에 HTTP 상태 코드를 함께 집계해 알림이 관측 사실을 그대로 적을 재료를 준다. 스키마 변경은 없고 `pipeline_runs.candidate_counts` 를 읽기만 한다.

**Tech Stack:** Python 3.11 · pytest · httpx · SQLAlchemy Core · Discord webhook embed

## Global Constraints

- 설계 근거는 `docs/superpowers/specs/2026-08-03-collection-block-alert-design.md` 이며 절 번호로 참조한다.
- 알림 문구에 원인 추정을 넣지 않는다 — `ADAPTER_HINTS` · `수집 끊김 의심` 류 표현을 이 두 알림에서 쓰지 않는다 (스펙 §5.3).
- 절벽 판정은 상태가 아니라 전이다 — 직전 회차 후보 1건 이상 → 이번 회차 0건 (스펙 §3.1).
- 알림 발송 실패가 회차 · 배치를 멈추지 않는다 (스펙 §6).
- `serve/` · `players` · `article_players` · `transfer_stage` · `transfer_direction` 은 건드리지 않는다.
- 스키마 변경 없음 · systemd 유닛 변경 없음 · `.env` 변경 없음.
- 커밋 트레일러는 실제 작업 모델 + `noreply@anthropic.com` (컨벤션 §1.3).
- git 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>`.

## 파일 구조

| 파일 | 책임 |
| --- | --- |
| `src/bullet_in/quality.py` | 절벽 판정 순수 함수 — DB · 알림을 모름 |
| `src/bullet_in/notify.py` | 두 알림의 embed 문구 조립 — 판정을 다시 하지 않음 |
| `src/bullet_in/run.py` | 직전 회차 조회 · 절벽 알림 발송 배선 |
| `src/bullet_in/watchlist_fmkorea.py` | 배치 전멸 판정 · 알림 발송 배선 |
| `src/bullet_in/adapters/fmkorea.py` | 검색 실패 사유 (HTTP 상태 코드) 집계 |
| `docs/runbook/2026-07-13-collection-alerts-ops.md` | 두 알림 판독법 · 튜닝 노브 |

판정 · 문구 · 배선을 나누는 이유는 테스트 가능성이다.
판정은 DB 없이, 문구는 네트워크 없이 검증할 수 있어야 한다.

---

### Task 1: 절벽 판정 함수

**Files:**
- Modify: `src/bullet_in/quality.py`
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: 없음
- Produces: `candidate_cliffs(today: dict[str, int], previous: dict[str, int]) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_quality.py` 끝에 추가한다.
세 경우는 실측 16회차 (스펙 §3.1 표) 에서 그대로 가져온 것이다.

```python
from bullet_in.quality import candidate_cliffs


def test_candidate_cliffs_detects_transition_to_zero():
    # fmkorea 가 직전 회차 10건에서 이번 회차 0건으로 떨어진 경우
    previous = {"fmkorea": 10, "goal": 13, "guardian": 8}
    today = {"goal": 14, "guardian": 8}
    assert candidate_cliffs(today, previous) == ["fmkorea"]


def test_candidate_cliffs_ignores_source_that_was_already_zero():
    # arsenal_official 은 직전에도 이번에도 0 — 전이가 아니므로 발화하지 않는다
    previous = {"arsenal_official": 0, "goal": 13}
    today = {"goal": 14}
    assert candidate_cliffs(today, previous) == []


def test_candidate_cliffs_returns_empty_when_no_previous_run():
    # 첫 회차 — 직전 행이 없으면 판정 대상이 없다
    assert candidate_cliffs({"goal": 14}, {}) == []


def test_candidate_cliffs_sorted_for_stable_alert_order():
    previous = {"skysports": 5, "fmkorea": 10}
    assert candidate_cliffs({}, previous) == ["fmkorea", "skysports"]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_quality.py -k candidate_cliffs -v`
Expected: FAIL — `ImportError: cannot import name 'candidate_cliffs'`

- [ ] **Step 3: 최소 구현을 넣는다**

`src/bullet_in/quality.py` 의 `evaluate_coverage` 아래에 추가한다.

```python
def candidate_cliffs(today: dict[str, int], previous: dict[str, int]) -> list[str]:
    """직전 회차에 후보가 있었는데 이번에 0 이 된 소스 (차단 알림 스펙 §3.1).

    상태 (후보 == 0) 가 아니라 전이만 잡는다 — 상태로 잡으면 이미 죽어 있는 소스가
    매 회차 발화한다 (실측 16회차에서 arsenal_official 은 16회 전부 후보 0).
    직전 회차에 후보가 있었다는 사실 자체가 '직전까지 살아 있었다' 의 증거라
    추가 이력 조건을 두지 않는다."""
    return sorted(sid for sid, n in previous.items()
                  if n > 0 and today.get(sid, 0) == 0)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_quality.py -k candidate_cliffs -v`
Expected: PASS 4건

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -F - <<'EOF'
feat(quality): 후보 절벽 판정 함수 추가

수집 경로가 막혀도 회차가 성공으로 끝나 알림이 나가지 않는 공백을 메우는 첫 조각이다.
직전 회차에 후보가 있던 소스가 이번 회차에 0 이 되는 전이만 잡아, 이미 후보가 끊긴 지 오래인 소스가 매 회차 발화하는 것을 막는다.

- 판정 함수: candidate_cliffs (직전 회차 계수 · 이번 회차 계수 비교)
- 전이 기준 채택 근거: 실측 16회차에서 arsenal_official 이 전부 후보 0
- 테스트: 전이 발화 · 상시 0 침묵 · 첫 회차 침묵 · 정렬 안정성

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: fmkorea 어댑터 실패 사유 계수

**Files:**
- Modify: `src/bullet_in/adapters/fmkorea.py:199` (속성 선언) · `:210` (초기화) · `:220-236` (집계)
- Test: `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: 없음
- Produces: `FmkoreaAdapter.search_failure_codes` — `Counter` · 키는 HTTP 상태 코드 `int` 또는 연결 오류 `"error"` · 값은 실패 횟수

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_fmkorea_adapter.py` 끝에 추가한다.
이 파일은 `respx` 로 HTTP 를 모킹하고 `asyncio.run(a.fetch())` 로 돌리는 방식이며, 기존 429 · 403 테스트가 같은 실패 경로를 이미 그렇게 검증한다.
같은 방식을 그대로 따른다.

```python
@respx.mock
def test_fmkorea_search_failure_codes_count_status():
    """상태 코드별로 집계된다 — 알림이 원인 추정 없이 사실을 적기 위한 재료."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(430))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(
        return_value=httpx.Response(403))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"},
                                        {"keyword": "kw2", "target": "title_content"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert a.search_failures == 2
    assert dict(a.search_failure_codes) == {430: 1, 403: 1}


@respx.mock
def test_fmkorea_search_failure_codes_count_connection_error():
    """연결 오류는 상태 코드가 없으므로 error 키로 집계된다."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(
        side_effect=httpx.ConnectError("boom"))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert a.search_failures == 1
    assert dict(a.search_failure_codes) == {"error": 1}


@respx.mock
def test_fmkorea_search_failure_codes_reset_between_fetches():
    """fetch 재진입 시 계수가 초기화된다 (search_failures 와 같은 규칙)."""
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(430))
    a = FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                       search_keywords=[{"keyword": "kw1", "target": "title"}],
                       base_url="https://www.fmkorea.com")
    asyncio.run(a.fetch())
    assert dict(a.search_failure_codes) == {430: 1}
    asyncio.run(a.fetch())
    assert dict(a.search_failure_codes) == {430: 1}   # 누적되지 않는다
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -k search_failure_codes -v`
Expected: FAIL — `AttributeError: 'FmkoreaAdapter' object has no attribute 'search_failure_codes'`

- [ ] **Step 3: 최소 구현을 넣는다**

파일 상단 import 에 `Counter` 를 더한다.

```python
from collections import Counter
```

`__init__` 의 `self.search_failures = 0` 다음 줄에 선언을 더한다.

```python
        self.search_failures = 0      # 이번 fetch 에서 실패한 키워드 검색 수
        self.search_failure_codes: Counter = Counter()   # 실패 사유 (HTTP 상태 코드 · 연결 오류)
```

`_discover` 의 초기화 줄을 함께 초기화하도록 바꾼다.

```python
        self.search_failures = 0
        self.search_failure_codes = Counter()
```

두 예외 처리에 집계를 더한다.
기존 로그 · 스킵 · `break` 동작은 그대로 둔다.

```python
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        log.warning("fmkorea 검색 429(rate limit) kw=%s p=%s — 스킵",
                                    kw["keyword"], page)
                    else:
                        log.warning("fmkorea 검색 HTTP %s kw=%s p=%s — 스킵",
                                    e.response.status_code, kw["keyword"], page)
                    self.search_failures += 1
                    self.search_failure_codes[e.response.status_code] += 1
                    break                       # 이 키워드의 남은 페이지도 중단
                except httpx.HTTPError as e:
                    log.warning("fmkorea 검색 실패 kw=%s p=%s err=%s — 스킵",
                                kw["keyword"], page, e)
                    self.search_failures += 1
                    self.search_failure_codes["error"] += 1
                    break
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_fmkorea_adapter.py -v`
Expected: 신규 3건 PASS · 기존 테스트 전부 PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/adapters/fmkorea.py tests/test_fmkorea_adapter.py
git commit -F - <<'EOF'
feat(collect): fmkorea 검색 실패 사유 집계

차단 알림이 원인을 지어내지 않고 관측 사실을 적으려면 실패 횟수만으로는 부족하다.
이미 세고 있는 검색 실패에 서버가 돌려준 상태 코드를 함께 담아, 알림이 "HTTP 430 4건" 처럼 확인된 값만 쓰게 한다.

- 신설 속성: search_failure_codes (상태 코드 · 연결 오류 error 키)
- 초기화 규칙: search_failures 와 같이 _discover 진입 시 리셋
- 수집 동작 무변경: 요청 · 스킵 · 커서 규칙은 그대로

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: 알림 문구 빌더 두 개

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `quality.candidate_cliffs` 의 결과 (`list[str]`) · `FmkoreaAdapter.search_failure_codes`
- Produces:
  - `build_cliff_alert(cliffs, *, history, sources, failure_codes, success_rate, run_id) -> dict`
  - `build_watchlist_blackout_alert(*, searched, failure_codes, last_contact) -> dict`
  - `COLOR_BLOCK` 상수

`history` 는 `pipeline_runs` 최신순 리스트이며 `history[0]` 이 직전 회차다.
판정은 이미 끝난 상태로 들어오고 빌더는 표시만 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_notify.py` 끝에 추가한다.

```python
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
    assert "후보 절벽" in embed["title"]
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
    assert "전멸" in embed["title"]
    body = "".join(f["value"] for f in embed["fields"])
    assert "검색 10명" in body
    assert "검색 실패 10건 — HTTP 430 10건" in body
    assert "커서" in embed["description"]


def test_watchlist_blackout_alert_without_last_contact():
    embed = notify.build_watchlist_blackout_alert(
        searched=10, failure_codes={"error": 10}, last_contact=None)
    body = "".join(f["value"] for f in embed["fields"])
    assert "연결 오류 10건" in body
    assert "마지막" not in body
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_notify.py -k "cliff or blackout" -v`
Expected: FAIL — `AttributeError: module 'bullet_in.notify' has no attribute 'build_cliff_alert'`

- [ ] **Step 3: 최소 구현을 넣는다**

`notify.py` 의 색상 상수 옆에 하나 더한다.

```python
COLOR_BLOCK = 0xD9534F
```

파일 끝에 헬퍼와 빌더 두 개를 더한다.

```python
def _failure_code_line(codes: dict) -> str | None:
    """어댑터가 센 검색 실패 사유 — 서버 응답 코드라 관측 사실로 적을 수 있다.
    계수를 내놓지 않는 어댑터는 None 을 돌려 그 줄이 빠진다."""
    if not codes:
        return None
    total = sum(codes.values())
    parts = [("연결 오류" if k == "error" else f"HTTP {k}") + f" {v}건"
             for k, v in sorted(codes.items(), key=lambda kv: str(kv[0]))]
    return f"검색 실패 {total}건 — " + " · ".join(parts)


def build_cliff_alert(cliffs: list[str], *, history: list[dict], sources: dict,
                      failure_codes: dict, success_rate: float,
                      run_id: str) -> dict:
    """후보 절벽 알림 (차단 알림 스펙 §5.1).

    판정은 run.py 가 끝냈고 여기서는 표시만 한다 — history[0] 이 직전 회차다.
    ADAPTER_HINTS 를 쓰지 않는다: 후보 0 의 원인은 알림 시점에 알 수 없고,
    같은 함정으로 SLO-5 를 두 번 고쳤다 (#169 · #174)."""
    fields = []
    for sid in cliffs:
        prev = history[0].get(sid, 0) if history else 0
        lines = [f"직전 회차 {prev}건 → 이번 회차 0건"]
        recent = [h.get(sid, 0) for h in history[:4]]
        if recent:
            seq = " → ".join(str(n) for n in reversed(recent))
            lines.append(f"최근 {len(recent) + 1}회: {seq} → 0 (이번)")
        code_line = _failure_code_line(failure_codes.get(sid) or {})
        if code_line:
            lines.append(code_line)
        lines.append(f"회차 자체는 정상 종료 (success_rate {success_rate:g})")
        fields.append({"name": _source_field_name(sid, sources),
                       "value": "\n".join(f"- {ln}" for ln in lines),
                       "inline": False})
    fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
    return {"title": f"🚨 수집 후보 절벽 — 소스 {len(cliffs)}건",
            "description": "직전 회차까지 후보가 있던 소스가 이번 회차에 0건이 되었습니다.",
            "color": COLOR_BLOCK, "fields": fields, "url": RUNBOOK_ANOMALY}


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
    return {"title": f"🚨 워치리스트 배치 전멸 — 검색 {searched}명 전원 실패",
            "description": ("검색한 선수 전원의 검색이 실패해 적재가 0건입니다.\n"
                            "커서는 전진하지 않아 다음 배치가 같은 슬라이스를 "
                            "다시 검색합니다."),
            "color": COLOR_BLOCK,
            "fields": [{"name": "이번 배치",
                        "value": "\n".join(f"- {ln}" for ln in lines),
                        "inline": False}],
            "url": RUNBOOK_ANOMALY}
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 신규 5건 PASS · 기존 테스트 전부 PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -F - <<'EOF'
feat(notify): 후보 절벽 · 배치 전멸 알림 문구 추가

두 알림은 차단 사실을 알리되 원인을 짚지 않는다.
후보 0 의 원인은 알림 시점에 알 수 없고, 기존 어댑터 힌트는 fmkorea 에 429 를 적으면서 실제 응답인 430 과 어긋나 있다.

- 절벽 문구: 직전 회차 대비 계수 · 최근 5회 추이 · 회차 정상 종료 사실
- 전멸 문구: 검색 인원 · 실패 건수 · 커서 무전진 안내
- 공통: 어댑터가 실패 사유를 내놓을 때만 상태 코드 줄을 붙임
- 금지 검증: 어댑터 힌트 · "의심" 표현이 본문에 없음을 테스트로 고정

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: 회차 배선

**Files:**
- Modify: `src/bullet_in/run.py:25` (import) · `:69-73` 직후 (알림 블록 삽입)
- Test: `tests/test_run_cliff_alert.py` (신규)

**Interfaces:**
- Consumes: `quality.candidate_cliffs` · `notify.build_cliff_alert`
- Produces: 없음 (배선 종점)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`run.main` 전체를 돌리려면 Mongo · Gemini · MariaDB 가 필요해 단위 테스트로 적합하지 않다.
알림 블록을 함수로 떼어 그 함수만 검증한다.

`tests/test_run_cliff_alert.py` 를 새로 만든다.

```python
from bullet_in.run import cliff_alert_payload


class _Adapter:
    def __init__(self, source_id, codes=None):
        self.source_id = source_id
        if codes is not None:
            self.search_failure_codes = codes


def test_payload_none_when_no_history():
    """첫 회차 — 직전 행이 없으면 판정하지 않는다."""
    assert cliff_alert_payload({"goal": 14}, [], adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_none_when_no_cliff():
    history = [{"goal": 13, "fmkorea": 10}]
    assert cliff_alert_payload({"goal": 14, "fmkorea": 9}, history,
                               adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_built_for_cliff_with_adapter_codes():
    history = [{"fmkorea": 10, "goal": 13}]
    payload = cliff_alert_payload(
        {"goal": 14}, history,
        adapters=[_Adapter("fmkorea", {430: 4}), _Adapter("goal")],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통"}},
        success_rate=1.0, run_id="3259230a")
    assert "후보 절벽" in payload["title"]
    assert "HTTP 430 4건" in payload["fields"][0]["value"]


def test_payload_ignores_source_already_at_zero():
    """arsenal_official 은 직전에도 0 — 전이가 아니므로 알림이 없다."""
    history = [{"arsenal_official": 0, "goal": 13}]
    assert cliff_alert_payload({"goal": 14}, history, adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_run_cliff_alert.py -v`
Expected: FAIL — `ImportError: cannot import name 'cliff_alert_payload'`

- [ ] **Step 3: 최소 구현을 넣는다**

`run.py:25` 의 quality import 에 `candidate_cliffs` 를 더한다.

```python
from bullet_in.quality import (success_rate, volume_anomalies, evaluate_freshness,
                               evaluate_coverage, candidate_cliffs)
```

`RUN_INSERT_SQL` 상수 아래에 조회 SQL 상수와 함수를 더한다.

```python
# 후보 절벽 판정 재료 (차단 알림 스펙 §3.1): [0] 이 직전 회차 · 나머지는 알림 표시용.
# 이번 회차 행은 파이프라인 마지막에 적재되므로 이 시점의 최신 행이 곧 직전 회차다.
CANDIDATE_HISTORY_SQL = ("SELECT candidate_counts FROM pipeline_runs "
                         "ORDER BY started_at DESC LIMIT 5")


def cliff_alert_payload(candidate_counts: dict, history: list[dict], *,
                        adapters, sources: dict, success_rate: float,
                        run_id: str) -> dict | None:
    """절벽이 있으면 알림 payload · 없으면 None (차단 알림 스펙 §3.1 · §5.1)."""
    if not history:
        return None
    cliffs = candidate_cliffs(candidate_counts, history[0])
    if not cliffs:
        return None
    failure_codes = {a.source_id: dict(getattr(a, "search_failure_codes", {}) or {})
                     for a in adapters}
    return notify.build_cliff_alert(
        cliffs, history=history, sources=sources,
        failure_codes=failure_codes, success_rate=success_rate, run_id=run_id)
```

`main` 의 후보 계수 로깅 (`run.py:72-73`) 바로 다음에 발송 블록을 넣는다.
공홈 커버리지 감시 루프 앞이다.

```python
    # 수집 후보 절벽 알림 (차단 알림 스펙 §3.1): 번역 · 렌더를 기다리지 않고 먼저 보낸다.
    # 판정 · 발송 실패가 회차를 멈추지 않게 감싼다 (ops 뷰 생성과 같은 격리).
    try:
        with engine.connect() as c:
            cand_hist = [json.loads(s) for s in
                         c.execute(text(CANDIDATE_HISTORY_SQL)).scalars().all() if s]
        payload = cliff_alert_payload(
            candidate_counts, cand_hist, adapters=adapters, sources=sources,
            success_rate=success_rate(len(adapters), len(errors)), run_id=run_id)
        if payload:
            notify.send_alert(**payload)
    except Exception:
        logging.getLogger(__name__).warning(
            "후보 절벽 판정 실패 — 이번 회차 건너뜀 (수집에는 영향 없음)", exc_info=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_run_cliff_alert.py -v && uv run pytest -q`
Expected: 신규 4건 PASS · 전체 통과

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/run.py tests/test_run_cliff_alert.py
git commit -F - <<'EOF'
feat(run): 회차에 후보 절벽 알림 배선

후보 계수는 회차마다 pipeline_runs 에 쌓이고 있었으나 알림 조건으로 쓰이지 않았다.
직전 회차 한 행을 읽어 절벽을 판정하고, 번역 · 분류 · 렌더를 기다리지 않도록 수집 직후에 알림을 보낸다.

- 판정 함수 분리: cliff_alert_payload (DB · 발송과 분리해 단위 테스트 가능)
- 조회 범위: 최근 5행 — 판정은 첫 행 · 나머지는 알림 추이 표시용
- 실패 격리: 판정 · 발송 실패를 회차와 분리 (ops 뷰 생성과 같은 방식)

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: 배치 배선

**Files:**
- Modify: `src/bullet_in/watchlist_fmkorea.py`
- Test: `tests/test_watchlist_fmkorea.py`

**Interfaces:**
- Consumes: `notify.build_watchlist_blackout_alert` · `FmkoreaAdapter.search_failure_codes`
- Produces: 없음 (배선 종점)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_watchlist_fmkorea.py` 의 `_FakeAdapter` 에 계수 속성을 더하고 테스트를 추가한다.

```python
class _FakeAdapter:
    def __init__(self, raw, search_failures=0, search_failure_codes=None):
        self._raw = raw
        self.search_failures = search_failures
        self.search_failure_codes = search_failure_codes or {}
        self.relevance_dropped = 0
        self.relevance_terms = []
        self.player_names = set()
    async def fetch(self):
        return self._raw
```

```python
def test_blackout_alert_sent_when_every_search_fails(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=5, search_failure_codes={430: 5})
    _run_main(monkeypatch, tmp_path, adapter=adapter,
              players=[(10, "케파"), (20, "누사"), (30, "딕슨"),
                       (40, "스톤스"), (50, "일디즈")])
    assert len(sent) == 1
    assert "전멸" in sent[0]["title"]


def test_no_alert_on_partial_failure(monkeypatch, tmp_path):
    """부분 실패는 알리지 않는다 (스펙 §3.2)."""
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=2, search_failure_codes={430: 2})
    _run_main(monkeypatch, tmp_path, adapter=adapter,
              players=[(10, "케파"), (20, "누사"), (30, "딕슨"),
                       (40, "스톤스"), (50, "일디즈")])
    assert sent == []


def test_no_alert_on_dry_run(monkeypatch, tmp_path):
    """dry-run 은 적재도 알림도 하지 않는다."""
    sent = []
    monkeypatch.setattr(watchlist_fmkorea.notify, "send_alert",
                        lambda **kw: sent.append(kw))
    adapter = _FakeAdapter([], search_failures=5, search_failure_codes={430: 5})
    _run_main(monkeypatch, tmp_path, adapter=adapter, dry_run=True,
              players=[(10, "케파"), (20, "누사"), (30, "딕슨"),
                       (40, "스톤스"), (50, "일디즈")])
    assert sent == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -k "blackout or partial or dry_run" -v`
Expected: FAIL — `AttributeError: module 'bullet_in.watchlist_fmkorea' has no attribute 'notify'`

- [ ] **Step 3: 최소 구현을 넣는다**

import 에 `notify` 를 더한다.

```python
from bullet_in import notify
```

`main` 의 커서 기록 뒤 · 완료 로그 앞에 발송 블록을 넣는다.
dry-run 은 이 지점 앞에서 이미 반환하므로 자연히 제외된다.

```python
    # 배치 전멸 알림 (차단 알림 스펙 §3.2): 검색 실패가 슬라이스 전원과 같을 때만.
    # 부분 실패는 알리지 않는다 — 실측 3회 모두 전원 실패였다.
    if slice_ids and adapter.search_failures == len(slice_ids):
        try:
            notify.send_alert(**notify.build_watchlist_blackout_alert(
                searched=len(slice_ids),
                failure_codes=dict(getattr(adapter, "search_failure_codes", {}) or {}),
                last_contact=last))
        except Exception:
            log.warning("배치 전멸 알림 발송 실패 — 배치는 계속 진행", exc_info=True)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run pytest tests/test_watchlist_fmkorea.py -v`
Expected: 신규 3건 PASS · 기존 테스트 전부 PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/watchlist_fmkorea.py tests/test_watchlist_fmkorea.py
git commit -F - <<'EOF'
feat(watchlist): 배치 전멸 알림 배선

워치리스트 배치는 검색이 전부 실패해도 정상 종료라 알림이 나가지 않았다.
실측에서 배치 다섯 번 중 세 번이 이 상태였고, 매번 사람이 저널을 읽어서 알았다.

- 발화 조건: 검색 실패 수가 슬라이스 인원과 같을 때만 (부분 실패 제외)
- dry-run 제외: 적재 없는 확인 실행에서는 알리지 않음
- 실패 격리: 알림 발송 실패가 커서 규칙 · 접촉 스탬프에 영향 없음

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: 런북 판독법

**Files:**
- Modify: `docs/runbook/2026-07-13-collection-alerts-ops.md`

**Interfaces:**
- Consumes: Task 3 의 문구 형태
- Produces: 없음

- [ ] **Step 1: 알림 해석 절에 두 항목을 더한다**

기존 `## 알림 해석` 의 마지막 불릿 (`**실물 캡처**`) 앞에 넣는다.

```markdown
- **🚨 수집 후보 절벽 (빨강)** — 직전 회차까지 후보가 있던 소스가 이번 회차에 0건.
  회차 자체는 성공으로 끝나므로 실패 알림이 따로 오지 않는다.
  소스당 필드에 직전 회차 대비 계수 · 최근 5회 추이 · 회차 종료 상태가 들어간다.
  어댑터가 실패 사유를 내놓으면 `검색 실패 4건 — HTTP 430 4건` 처럼 서버 응답 코드가 붙는다.
  **원인은 적지 않는다** — 후보 0 이 차단인지 셀렉터 드리프트인지는 알림 시점에 알 수 없다.
- **🚨 워치리스트 배치 전멸 (빨강)** — 배치가 검색한 선수 전원의 검색이 실패.
  적재 0건이고 커서가 전진하지 않아 다음 배치가 같은 슬라이스를 다시 검색한다.
  사람이 되돌릴 것은 없다.
```

- [ ] **Step 2: 대응 절에 두 항목을 더한다**

기존 `## 대응` 의 `❌ 실패 알림` 항목 뒤에 넣는다.

```markdown
- **🚨 절벽 알림 — fmkorea** — 응답 코드가 430 이면 자동 수집 차단이다.
  대개 한 회차 (3시간) 안에 풀리므로 즉시 조치가 필요하지 않다.
  풀렸는지 확인할 때도 직접 접촉하지 말고 다음 회차 로그를 본다 (`docs/troubleshooting/2026-08-03-fmkorea-430-not-explained-by-our-requests.md`).
- **🚨 절벽 알림 — 그 외 소스** — 응답 코드 줄이 없으면 어댑터 단독 `fetch()` 로 라이브 재검증한다.
  대개 셀렉터 · feed_url 드리프트다.
- **🚨 배치 전멸 알림** — 같은 슬라이스를 다음 배치가 재시도하므로 한 번은 지켜본다.
  연속으로 오면 fmkorea 접촉 경로 (터널 · 프록시) 를 확인한다.
```

- [ ] **Step 3: 튜닝 노브 절에 항목을 더한다**

기존 `## 튜닝 노브` 마지막에 넣는다.

```markdown
- **절벽 판정 (`quality.candidate_cliffs`)** — 임계가 없다.
  직전 회차에 후보가 1건 이상이었는데 이번에 0 이면 발화한다.
  상태가 아니라 전이를 보므로 후보가 끊긴 지 오래인 소스는 발화하지 않는다.
  연속 차단도 두 번째 회차부터는 직전이 0 이라 조용하다.
- **절벽 이력 윈도우 (`run.py` 의 `CANDIDATE_HISTORY_SQL` · `LIMIT 5`)** — 판정에는 첫 행만 쓴다.
  나머지 4행은 알림 본문의 최근 추이 표시용이라 늘리거나 줄여도 판정이 바뀌지 않는다.
- **배치 전멸 조건 (`watchlist_fmkorea.main`)** — 검색 실패 수가 슬라이스 인원과 같을 때만 발화.
  부분 실패에도 알리려면 이 등호를 비율 비교로 바꾼다.
```

- [ ] **Step 4: 서식 검사를 통과시킨다**

Run: `echo '{"tool_input":{"file_path":"docs/runbook/2026-07-13-collection-alerts-ops.md"}}' | python3 .claude/hooks/check-doc-format.py; echo "exit=$?"`
Expected: `exit=0`

- [ ] **Step 5: 커밋한다**

```bash
git add docs/runbook/2026-07-13-collection-alerts-ops.md
git commit -F - <<'EOF'
docs(runbook): 차단 알림 두 종 판독법 추가

새 알림이 늘면 판독 기준도 같은 자리에 있어야 한다.
수집 이상 알림 런북에 절벽 · 전멸 알림의 해석 · 대응 · 튜닝 지점을 이어 붙인다.

- 해석: 두 알림이 회차 성공과 함께 온다는 점 · 원인을 적지 않는 이유
- 대응: 430 은 대기 · 응답 코드 없는 절벽은 어댑터 라이브 재검증
- 튜닝: 절벽은 임계 없는 전이 판정 · 이력 5행 중 판정은 첫 행만

Refs: docs/superpowers/specs/2026-08-03-collection-block-alert-design.md

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 구현 후 검증

- [ ] 전체 테스트 — `uv run pytest -q` · 베이스라인 945 passed · 1 skipped 대비 신규 19건 증가.
- [ ] 스펙 대조 — 스펙 §3 · §4 · §5 · §6 · §7 의 각 항목이 어느 태스크에서 처리됐는지 확인.
- [ ] 최종 전체 리뷰 — 태스크별 리뷰만으로는 계획서 코드의 결함이 살아남는다 (세션 메모리 `plan-code-defects-survive-implementation`).
- [ ] PR 생성 — 7섹션 한국어 본문 · `--body-file` 전달 · humanize-korean fast 1회 통과 · Claude 서명 금지.
- [ ] VM 반영 — 머지 후 사용자 지시를 받아 진행 (스펙 §10).
세션이 임의로 `git pull` · 재렌더 · 배포를 하지 않는다.

## 계획 수립 중 확인한 사항

- **스펙 §5.2 의 시각 표기 변경** — 스펙 예시는 `2026-08-03 19:34 KST` 였으나 구현은 Discord 시각 마크업 (`_discord_ts`) 을 쓴다.
보는 사람의 로컬 시각으로 렌더되고 기존 신선도 알림과 같은 방식이라 표기만 바뀐다.
- **런북의 회차 주기 표기가 낡았다** — `## 튜닝 노브` 에 `6 시간마다 4 회/일` 이라고 적혀 있으나 실제는 3시간마다 8회다.
이 트랙 범위 밖이라 고치지 않고 남긴다 (사용자 판단 대기).
