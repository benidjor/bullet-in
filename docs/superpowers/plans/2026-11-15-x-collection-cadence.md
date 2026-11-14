# X 수집 빈도 · 반복 접근 줄이기 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** X 두 소스 (`x_afcstuff` · `x_ornstein`) 가 이적기간에는 영국 낮 다섯 회차, 그 밖에는 두 회차에만 돌고, 이미 본 트윗은 펼치기 · 역추적을 다시 하지 않게 한다.

**Architecture:** 이적시장 일정을 `transfer_windows.py` 한 곳으로 옮기고 (화면 타이머와 수집 일정이 같은 목록을 본다), `factory.scheduled_skips` 가 회차 시각으로 건너뛸 소스를 고른다.
건너뛴 소스는 깔때기에 `{"skipped": "schedule"}` 표식을 남기고, 응답 판정 · 신선도 상태 · 절벽 알림 · 운영 화면이 그 표식을 「건너뜀」 으로 읽는다.
X 어댑터는 트윗별 결과 (펼친 전문 · 역추적 결과 항목) 를 `state/x_cache_<소스>.json` 에 기억해 두고, 이미 본 트윗에는 기억한 결과를 그대로 내보낸다.

**Tech Stack:** Python 3.11 · PyYAML · Playwright (변경 없음) · pytest

**Spec:** 별도 설계 문서 없음 · 결정은 2026-11-15 세션의 사용자 결정 (아래 「결정」 절) 과 실측이다

## 배경

X 가 2026-11-08 수집용 쿠키의 계정을 자동화 탐지 (inauthentic behaviors) 로 정지했다.
수집은 그보다 앞선 2026-10-20 00:00 UTC 부터 11-09 06:00 UTC 까지 163회차 연속 실패했고, 사용자가 잠금을 푼 뒤 회복했다.
2026-11-15 실측으로 두 가지가 드러났다.

- 역추적이 연 기자 타임라인 607번 가운데 538번 (89%) 이 직전 회차와 같은 기자의 반복이다 · 회차마다 afcstuff 최근 30트윗 전부를 다시 역추적하기 때문이다
- 저장된 afcstuff 트윗 313건의 85% 가 07 ~ 18 UTC 에 올라왔고 02 ~ 05 UTC 는 0건이다

## 결정 (2026-11-15 사용자)

| 항목 | 결정 |
| --- | --- |
| X 수집 | 끄지 않는다 |
| 이적기간 X 회차 (UTC) | 9 · 12 · 15 · 18 · 21 (KST 18 · 21 · 00 · 03 · 06시) |
| 비이적기간 X 회차 (UTC) | 12 · 21 (KST 21 · 06시) |
| 역추적 | 끄지 않는다 · 새 트윗만 (이미 본 트윗은 첫 결과 재사용) |
| 잘린 트윗 펼치기 | 새 트윗만 (이미 본 트윗은 첫 결과 재사용) |
| 머지 전 임시 조치 | 없음 |

## 작업 원칙 (Karpathy 4원칙 · CLAUDE.md 「행동 가이드라인」)

구현 · 리뷰 서브에이전트는 CLAUDE.md 의 4원칙을 지킨다.
특히 아래 둘은 이 계획에서 리뷰가 Important 로 다룬다.

- **요청 밖 변경 금지** — 작업의 Files 목록 밖 파일을 고치거나, 리뷰의 Minor 를 근거로 설계에 없는 동작을 더하지 않는다. 넣을 만하면 보고만 하고 사용자가 정한다.
- **근거 없는 단정 금지** — 보고 · 커밋 · 주석의 숫자와 사실은 실행한 명령이나 읽은 파일에 닿아야 한다. 닿지 않으면 「추정」 이라고 쓴다.

## 가정과 확인

| 가정 | 확인 방법 · 결과 |
| --- | --- |
| 수집에서 소스를 통째로 빼는 장치가 이미 있다 | `adapters/factory.py:33` 의 `collect: false` (goal 소스가 사용) · 같은 자리에 `skip` 인자를 더한다 |
| 깔때기가 없는 소스는 무응답으로 세어 두 번이면 「끊김」 알림이 간다 | `quality.responded` 가 `(False, "no_record")` · `evaluate_states` 의 `_miss_runs_to_break` 기본 2 · 그래서 건너뜀 표식이 필요하다 |
| 건너뛴 회차에는 절벽 알림이 X 를 「후보 0」 으로 잡는다 | `quality.candidate_cliffs` 가 직전 > 0 · 이번 0 을 잡음 · `run.cliff_alert_payload` 에 `skip` 인자가 이미 있다 (사이트맵 알림용) |
| X 의 수집량 이상 탐지는 이번 변경과 무관하다 | `quality.volume_anomalies` 의 `min_baseline` 3 · X 의 회차당 신규는 2026-11 실측 0 ~ 4 · 평균이 3 미만이라 원래 판정 대상이 아니다 (추정 · 이적기간 평균은 안 쟀다) |
| afcstuff 신선도 기준 24시간은 바꾸지 않아도 된다 | X 회차 간격 최대 = 비이적기간 21 → 12 UTC 15시간 · 이적기간 21 → 9 UTC 12시간 · 신선도 워터마크는 Mongo 원본 `fetched_at` (`run.publish`) |
| 직전 신선도 행에 상태가 저장된다 | `storage/mariadb.py` `previous_freshness` 가 `state` · `miss_streak` · `list_sig` · `list_changed_at` · `block_streak` 를 읽는다 |
| 이미 본 트윗의 펼치기를 건너뛰면 저장 행이 잘린 글로 덮인다 | 내용 해시 = 제목 · 본문 + 주소 (`run.collect`) · 해시가 다르면 `to_articles` 가 「바뀜」 으로 다시 쓴다 · 그래서 건너뛰지 않고 첫 결과를 재사용한다 |
| 역추적 결과를 건너뛰고 트윗 주소로 내보내면 행이 하나 더 생긴다 | 승격된 행의 주소는 기사 주소 · 트윗 주소는 DB 에 없다 · 그래서 승격 결과 항목 전체를 기억한다 |
| `backtrack_promote` 는 입력 순서대로 하나씩 내보낸다 | `adapters/x_backtrack.py` 의 `out.append` 가 항목마다 정확히 한 번 · 원래 주소와 결과를 짝지을 수 있다 |
| `state/` 는 배포에서 지워지지 않는다 | `.gitignore` 17행 · VM `~/bullet-in/state/` 에 `deploy.json` (09-19 생성) 등이 남아 있다 (2026-11-15 `ls`) |
| YAML 키 `off` 는 `False` 로 읽힌다 | 메모리 「YAML 1.1 on · off」 (2026-10-08 실제 사고) · 그래서 키를 `in_window` · `out_of_window` 로 짓는다 |
| Airflow 재시도는 같은 회차 시각을 넘겨 시작할 수 있다 | 2026-11-11 12:00 회차의 collect 재시도가 12:07 · 18:00 회차가 18:24 에 시작 · 그래서 시각을 3시간 칸으로 내린다 |
| X 어댑터 시험에는 가짜 Playwright 가 없다 | `tests/test_x_playwright.py` · `tests/test_x_expand.py` 는 순수 함수와 가짜 `ctx` 만 쓴다 · 그래서 기억 로직을 브라우저 밖 함수로 뺀다 |

## 더 단순한 꼴과 버린 이유

| 더 단순한 꼴 | 버린 이유 |
| --- | --- |
| Airflow DAG 를 X 전용으로 하나 더 만든다 | 태스크 여덟 · 배포 판정 · 알림이 한 DAG 에 묶여 있다 · 수집 단계 안에서 소스 하나를 빼는 편이 바뀌는 곳이 적다 |
| 회차 시각 대신 「지난 X 수집 후 N시간」 으로 판정한다 | 지난 시각을 기억할 상태가 필요하고, 재시도 · 실패 회차에서 꼬인다 · 시각 목록은 무상태다 |
| 기자를 회차마다 돌아가며 고른다 (순환) | 반복의 원인은 같은 트윗을 다시 보는 것이라 순환으로는 반복이 남는다 · 차례를 기다리는 동안 원본이 25트윗 밖으로 밀려 매칭 성공률이 떨어진다 (2026-11-15 사용자와 검토) |
| 이미 본 트윗은 펼치기 · 역추적을 그냥 건너뛴다 | 잘린 원문 · 트윗 주소가 나가 저장 행을 덮거나 새 행을 만든다 (「가정과 확인」) |
| 이미 본 트윗을 결과에서 빼 버린다 | 그 회차 적재가 실패하면 (2026-11-11 시간 초과처럼) 그 트윗은 영영 안 들어온다 · 기억한 결과를 매번 내보내면 다음 회차가 채운다 |
| 기억 파일 크기에 상한을 둔다 | 이번 수집에 보인 트윗만 남기면 (최근 30개) 크기가 저절로 묶인다 |
| 건너뛴 회차에 새 상태 `skipped` 를 쓴다 | 알림 · 운영 화면이 상태 넷만 센다 (`notify.py:279`) · 다음 회차가 직전 상태를 「skipped」 로 읽어 끊김 재알림 간격이 흔들린다 · 직전 판정을 그대로 잇는 편이 바뀌는 곳이 적다 |

## Global Constraints

- 파이썬은 워크트리의 3.11 가상환경으로 돌린다 (`uv venv --python 3.11 --project .` 뒤 `uv run --project . --extra dev pytest`)
- 전체 테스트 기준 = 1,930 통과 · 89 skip (DB 없이 · `d0d9d75` · 2026-11-15)
- 회차 시각 판정은 UTC 시를 3시간 칸으로 내린 값이다 (`hour - hour % 3`)
- 설정 키 = `run_hours_utc: {in_window: [...], out_of_window: [...]}` · `off` · `on` · `yes` · `no` 를 키로 쓰지 않는다
- 기억 파일 경로 = `state/x_cache_afcstuff.json` · `state/x_cache_ornstein.json` (설정 `config.cache_path`) · 설정이 없으면 기억하지 않는다 (시험이 실제 파일을 쓰지 않게)
- 건너뜀 표식 = 깔때기 `{"skipped": "schedule"}` · 응답 판정 사유 = `"skipped"`
- 시험에서 X · 외부 사이트에 접속하지 않는다

## Review Focus

- **Airflow 재시도 · 늦은 시작** — 12:07 · 13:59 UTC 에 시작한 collect 는 12 회차로 본다 (Task 2 시험)
- **기억 파일이 없거나 깨짐** — 빈 기억으로 시작하고 수집은 계속한다 · 경고 한 줄 (Task 3 시험)
- **이미 저장한 트윗의 원문** — 기억한 전문이 그대로 나가 저장 행이 잘린 글로 바뀌지 않는다 (Task 3 시험)
- **기자 타임라인을 못 연 항목** — 기억하지 않아 다음 회차에 다시 시도한다 (Task 3 시험)
- **건너뛴 회차의 신선도 상태** — 직전이 「끊김」 이면 그대로 「끊김」 · 연속 무응답 수가 늘지 않는다 (Task 2 시험)

## 알고 두는 한계 (고치지 않음)

- **X 의 절벽 알림은 사실상 꺼진다** — 건너뛴 회차 다음 X 회차는 직전 회차에 X 후보가 없어 「직전 > 0 · 이번 0」 이 성립하지 않는다 · X 고장은 신선도 「끊김」 (X 회차 두 번 연속 무응답) 이 잡는다 · 비이적기간에는 알림까지 최대 약 24시간
- **기자 링크가 나중에 달리는 경우** — 첫 시도에서 카드가 없던 트윗은 다시 시도하지 않는다 · 지금까지 그런 사례가 있었는지는 안 쟀다
- **X 실패 때 화면 단서** — 시간 초과 때 페이지 주소 · 제목을 남기는 일은 이번 범위 밖이다 (사용자 결정 대기)

---

### Task 1: 이적시장 일정 공용화

**Files:**
- Create: `src/bullet_in/transfer_windows.py`
- Modify: `src/bullet_in/serve/render.py:851-866` (상수 정의를 import 로 바꿈 · 주석은 새 모듈로 옮김)
- Test: `tests/test_transfer_windows.py`

**Interfaces:**
- Produces: `TRANSFER_WINDOWS: list[dict]` (값 · 키 `name` · `open` · `close` 그대로) · `in_transfer_window(now: datetime) -> bool` (`open` 이상 · `close` 미만 · `now` 는 시간대가 있는 값)

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
from datetime import datetime, timezone
from bullet_in.transfer_windows import in_transfer_window, TRANSFER_WINDOWS
from bullet_in.serve import render

def _u(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def test_summer_window_closes_at_23_bst():
    assert in_transfer_window(_u("2026-09-01T21:59:00"))
    assert not in_transfer_window(_u("2026-09-01T22:00:00"))

def test_winter_window_bounds():
    assert not in_transfer_window(_u("2026-12-31T23:59:00"))
    assert in_transfer_window(_u("2027-01-01T00:00:00"))
    assert not in_transfer_window(_u("2027-02-01T23:00:00"))

def test_mid_november_is_outside():
    assert not in_transfer_window(_u("2026-11-15T12:00:00"))

def test_render_uses_the_same_list():
    assert render.TRANSFER_WINDOWS is TRANSFER_WINDOWS
```

- [ ] **Step 2: 실패 확인** — `uv run --project . --extra dev pytest tests/test_transfer_windows.py -q` · `ModuleNotFoundError`
- [ ] **Step 3: `transfer_windows.py` 에 상수와 `in_transfer_window` 를 두고 `render.py` 는 `from bullet_in.transfer_windows import TRANSFER_WINDOWS` 로 바꾼다** · 시각은 `datetime.fromisoformat` 으로 읽는다
- [ ] **Step 4: 통과 확인** — 같은 명령 · 4 passed · 이어서 `pytest tests/test_serve_render.py -q` 가 그대로 통과
- [ ] **Step 5: 커밋** — `refactor(serve): 이적시장 일정을 수집과 함께 쓰도록 별도 모듈로`

---

### Task 2: 회차 일정에 따라 X 건너뛰기

**Files:**
- Modify: `config/sources.yaml` (`x_afcstuff` · `x_ornstein` 에 `run_hours_utc` · 주석 두 줄)
- Modify: `src/bullet_in/adapters/factory.py` (`scheduled_skips` 추가 · `build_adapters` 에 `skip` 인자)
- Modify: `src/bullet_in/run.py` (`collect` 배선 · `skipped_funnels` 추가)
- Modify: `src/bullet_in/quality.py` (`responded` · `evaluate_states`)
- Modify: `src/bullet_in/serve/ops_view.py` (`_stage_text`)
- Test: `tests/test_adapter_factory.py` · `tests/test_quality.py` · `tests/test_run_cliff_alert.py` · `tests/test_ops_view.py`

**Interfaces:**
- Consumes: Task 1 `in_transfer_window(now)`
- Produces:
  - `factory.scheduled_skips(sources: list[dict], now: datetime) -> list[str]` — `run_hours_utc` 가 있고 수집 대상 (`enabled` · `collect` 가 참) 인 소스 가운데, 이번 칸 (`now` 를 UTC 로 바꾼 시 `- 시 % 3`) 이 그 기간 목록 (`in_window` 또는 `out_of_window`) 에 없는 소스 · 설정 순서대로
  - `factory.build_adapters(..., skip: Collection[str] = ())` — `skip` 의 소스를 만들지 않는다
  - `run.skipped_funnels(funnels: dict, skipped: list[str]) -> dict` — `funnels` 에 `{sid: {"skipped": "schedule"}}` 를 더한 새 dict
  - `quality.responded` — 깔때기에 `skipped` 가 있으면 `(False, "skipped")` (`errored` 판정 다음 · 깔때기 없음 판정 앞)
  - `quality.evaluate_states` — 사유 `"skipped"` 이면 직전 행의 `state` (없으면 `"ok"`) · `miss_streak` · `block_streak` · `list_sig` · `list_changed_at` 을 그대로 잇고 `reason` 은 `"skipped"` · `cap_hours` 는 평소대로 채운다
  - `ops_view._stage_text` — `{"skipped": ...}` 이면 `"일정상 건너뜀"`

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
# tests/test_adapter_factory.py
from datetime import datetime, timezone
from bullet_in.adapters.factory import scheduled_skips

_X = {"source_id": "x", "adapter": "x_playwright",
      "run_hours_utc": {"in_window": [9, 12, 15, 18, 21], "out_of_window": [12, 21]},
      "config": {"handle": "h"}}

def _t(s): return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)

def test_out_of_window_runs_only_at_listed_slots():
    assert scheduled_skips([_X], _t("2026-11-15T12:00:04")) == []
    assert scheduled_skips([_X], _t("2026-11-15T15:00:04")) == ["x"]

def test_in_window_uses_the_window_list():
    assert scheduled_skips([_X], _t("2027-01-10T15:00:04")) == []
    assert scheduled_skips([_X], _t("2027-01-10T03:00:04")) == ["x"]

def test_late_retry_counts_as_its_slot():
    assert scheduled_skips([_X], _t("2026-11-11T12:07:26")) == []
    assert scheduled_skips([_X], _t("2026-11-11T13:59:00")) == []

def test_sources_without_schedule_or_not_collected_are_never_listed():
    plain = {"source_id": "p", "adapter": "rss", "config": {"feed_url": "a"}}
    stopped = dict(_X, source_id="s", collect=False)
    assert scheduled_skips([plain, stopped], _t("2026-11-15T15:00:00")) == []

def test_build_adapters_drops_skipped_sources():
    cfg = {"sources": [{"source_id": "keep", "adapter": "rss", "config": {"feed_url": "a"}}, _X]}
    assert [a.source_id for a in build_adapters(cfg, skip=["x"])] == ["keep"]

def test_live_x_sources_have_both_schedules():
    cfg = yaml.safe_load(open("config/sources.yaml"))
    for s in cfg["sources"]:
        if s["source_id"] in ("x_afcstuff", "x_ornstein"):
            assert s["run_hours_utc"] == {"in_window": [9, 12, 15, 18, 21],
                                          "out_of_window": [12, 21]}
```

```python
# tests/test_quality.py
def test_responded_skipped_by_schedule():
    assert responded("x_playwright", {"skipped": "schedule"}, False) == (False, "skipped")

def test_skipped_run_carries_the_previous_judgement():
    prev = {"state": "broken", "miss_streak": 3, "block_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=5)}
    r = _judge(_rec("x_afcstuff", thr=24.0), ok=False, reason="skipped", sig=None, prev=prev)
    assert (r.state, r.reason, r.miss_streak, r.list_sig) == ("broken", "skipped", 3, "s1")
    assert r.list_changed_at == _T0 - timedelta(hours=5)

def test_skipped_run_without_history_is_ok():
    r = _judge(_rec("x_afcstuff", thr=24.0), ok=False, reason="skipped", sig=None)
    assert (r.state, r.miss_streak) == ("ok", 0)
```

```python
# tests/test_run_cliff_alert.py
from bullet_in.run import skipped_funnels

def test_skipped_sources_get_a_marker_and_keep_others():
    out = skipped_funnels({"bbc_sport": {"entries": 3}}, ["x_afcstuff"])
    assert out == {"bbc_sport": {"entries": 3}, "x_afcstuff": {"skipped": "schedule"}}

def test_cliff_ignores_a_skipped_source():
    assert cliff_alert_payload({"bbc_sport": 3}, [{"bbc_sport": 3, "x_afcstuff": 2}],
                               adapters=[], sources={}, success_rate=1.0,
                               run_id="r", skip={"x_afcstuff"}) is None
```

```python
# tests/test_ops_view.py
def test_stage_text_for_a_skipped_source():
    assert _stage_text({"skipped": "schedule"}) == "일정상 건너뜀"
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_adapter_factory.py tests/test_quality.py tests/test_run_cliff_alert.py tests/test_ops_view.py -q` · 새 시험만 실패 (`ImportError` · 단언 실패)
- [ ] **Step 3: 구현한다**
  - `sources.yaml` 두 X 소스에 `run_hours_utc: { in_window: [9, 12, 15, 18, 21], out_of_window: [12, 21] }` · 주석 = 「2026-11-08 X 가 자동화 탐지로 계정 정지 · 이적기간은 영국 낮 다섯 회차 · 그 밖에는 두 회차 (2026-11-15 사용자 결정 · 계획서 2026-11-15-x-collection-cadence)」
  - `collect` 는 `now = datetime.now(timezone.utc)` · `skipped = scheduled_skips(cfg["sources"], now)` 를 `build_adapters(..., skip=skipped)` 에 넘기고, 비어 있지 않으면 `INFO 일정상 건너뜀: x_afcstuff · x_ornstein` 한 줄 · 절벽 판정의 `skip` 은 `sitemap_alerted | set(skipped)` · `FetchSummary` 의 `funnels` 는 `skipped_funnels(adapter_funnels(adapters), skipped)`
  - `publish` 의 `build_adapters` 호출 (`run.py:697`) 은 바꾸지 않는다
- [ ] **Step 4: 통과 확인** — 같은 명령 통과 · 이어서 전체 `pytest -q` 가 1,930 + 새 시험 수만큼 통과 · 89 skip
- [ ] **Step 5: 커밋** — `feat(collect): X 를 이적기간 다섯 회차 · 그 밖에는 두 회차에만 돌게`

---

### Task 3: 이미 본 트윗은 첫 결과를 재사용

**Files:**
- Modify: `src/bullet_in/adapters/x_playwright.py` (`expand_truncated` 의 `known` 인자 · `load_x_cache` · `save_x_cache` · `backtrack_cached` 추가 · `XPlaywrightAdapter` 의 `cache_path` · `fetch` 배선 · `_scrape_journalists` 반환을 `(timelines, failed)` 로)
- Modify: `src/bullet_in/adapters/factory.py` (`cache_path` 전달)
- Modify: `config/sources.yaml` (두 X 소스 `config.cache_path`)
- Test: `tests/test_x_expand.py` · `tests/test_x_cache.py` (새 파일)

**Interfaces:**
- Produces:
  - `expand_truncated(ctx, raw_tweets, handle, log, cap=10, known: dict[str, str] | None = None) -> int` — `known` 에 있는 `status_id` 는 그 전문으로 바꾸고 페이지를 열지 않는다 · 새로 펼친 전문을 `known` 에 더한다 · 반환은 새로 늘어난 건수
  - `load_x_cache(path: str | None) -> dict` — `{"expanded": {status_id: text}, "outcomes": {tweet_url: {"url", "source_type", "raw_payload"}}}` · `None` · 파일 없음 · JSON 오류면 빈 꼴 (JSON 오류는 `WARNING X 결과 기억 파일을 못 읽음 — 빈 기억으로 시작`)
  - `save_x_cache(path: str | None, cache: dict, status_ids: set[str], tweet_urls: set[str]) -> None` — 이번에 본 키만 남겨 임시 파일에 쓰고 `os.replace` · `path` 가 `None` 이면 아무것도 안 한다
  - `async backtrack_cached(items: list[RawItem], outcomes: dict, now: datetime, scrape, promote) -> list[RawItem]` — `scrape(fresh) -> (timelines, failed)` · `promote(fresh, timelines) -> list[RawItem]` · 기억한 주소는 `RawItem(source_id, source_type, url, fetched_at=now, raw_payload)` 로 되살리고 나머지만 `scrape` · `promote` 에 넘긴다 · 새 결과는 인용 기자 (`raw_payload["journalist"]` 의 `@` 뗀 소문자) 가 `failed` 에 없을 때만 기억한다 · 출력 순서는 입력 순서 · 새 항목이 없으면 `scrape` · `promote` 를 부르지 않는다
- Consumes: 기존 `backtrack_promote(items, timelines, cfg)`

- [ ] **Step 1: 실패하는 시험을 쓴다**

```python
# tests/test_x_expand.py (기존 가짜 ctx 를 쓴다)
def test_expand_reuses_known_text_without_opening_a_page():
    ctx = _FakeCtx({})                         # 열면 시험이 실패하게 만든 가짜
    tweets = [{"status_id": "1", "text": "a" * 280}]
    grown = asyncio.run(expand_truncated(ctx, tweets, "h", logging.getLogger(), known={"1": "full"}))
    assert (grown, tweets[0]["text"], ctx.opened) == (0, "full", 0)

def test_expand_records_new_full_text():
    known = {}
    ctx = _FakeCtx({"2": "x" * 400})
    asyncio.run(expand_truncated(ctx, [{"status_id": "2", "text": "a" * 280}], "h",
                                 logging.getLogger(), known=known))
    assert known == {"2": "x" * 400}
```

```python
# tests/test_x_cache.py
def test_second_run_reuses_promotion_and_opens_no_timeline(tmp_path):
    calls = []
    async def scrape(fresh): calls.append(len(fresh)); return {"samimokbel_bbc": []}, set()
    async def promote(fresh, tl): return [_promoted(it) for it in fresh]
    outcomes = {}
    first = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW, scrape, promote))
    second = asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW2, scrape, promote))
    assert calls == [1]
    assert [i.url for i in second] == [i.url for i in first] == ["https://www.bbc.com/a"]
    assert second[0].raw_payload == first[0].raw_payload and second[0].fetched_at == _NOW2

def test_failed_timeline_is_not_remembered():
    async def scrape(fresh): return {}, {"samimokbel_bbc"}
    async def promote(fresh, tl): return list(fresh)
    outcomes = {}
    asyncio.run(backtrack_cached([_tweet("1")], outcomes, _NOW, scrape, promote))
    assert outcomes == {}

def test_save_keeps_only_what_this_run_saw_and_round_trips(tmp_path):
    p = tmp_path / "c.json"
    cache = {"expanded": {"1": "a", "9": "old"}, "outcomes": {"u1": {"url": "u1"}, "u9": {}}}
    save_x_cache(str(p), cache, {"1"}, {"u1"})
    assert load_x_cache(str(p)) == {"expanded": {"1": "a"}, "outcomes": {"u1": {"url": "u1"}}}

def test_broken_or_missing_cache_starts_empty(tmp_path, caplog):
    bad = tmp_path / "bad.json"; bad.write_text("{")
    empty = {"expanded": {}, "outcomes": {}}
    assert load_x_cache(None) == load_x_cache(str(tmp_path / "none.json")) == empty
    assert load_x_cache(str(bad)) == empty and "못 읽음" in caplog.text

def test_live_x_sources_have_cache_paths():
    cfg = yaml.safe_load(open("config/sources.yaml"))
    paths = {s["source_id"]: s["config"].get("cache_path") for s in cfg["sources"]
             if s["source_id"].startswith("x_")}
    assert paths == {"x_afcstuff": "state/x_cache_afcstuff.json",
                     "x_ornstein": "state/x_cache_ornstein.json"}
```

`_tweet(sid)` 은 `parse_afcstuff_tweets` 가 내는 모양의 `RawItem` (주소 `https://x.com/afcstuff/status/<sid>` · `raw_payload["journalist"] = "@SamiMokbel_BBC"`) · `_promoted(it)` 은 주소 `https://www.bbc.com/a` · `source_type="html"` 인 새 `RawItem` 이다.
`tests/test_x_expand.py` 의 가짜 `ctx` 에 연 페이지 수 (`opened`) 가 없으면 이 작업에서 더한다.

- [ ] **Step 2: 실패 확인** — `pytest tests/test_x_expand.py tests/test_x_cache.py -q` · 새 시험만 실패
- [ ] **Step 3: 구현한다** — `fetch` 순서 = `cache = load_x_cache(self.cache_path)` → 타임라인 스크롤 → `expand_truncated(..., known=cache["expanded"])` → 파싱 → (`backtrack_config` 가 있으면 브라우저를 닫기 전에) `backtrack_cached(items, cache["outcomes"], now, scrape=lambda f: self._scrape_journalists(ctx, f, bt, log), promote=lambda f, tl: backtrack_promote(f, tl, bt))` → 브라우저 닫기 → (`self_source` 면) `resolve_card_urls` → `save_x_cache(self.cache_path, cache, 이번 status_id 집합, 파싱한 트윗 주소 집합)`
  - 결과 기억 파일을 읽거나 쓰다 실패해도 수집은 계속한다 (쓰기 실패 = `WARNING` 한 줄)
- [ ] **Step 4: 통과 확인** — 같은 명령 통과 · 이어서 전체 `pytest -q` 통과 · 89 skip
- [ ] **Step 5: 커밋** — `perf(x): 이미 본 트윗은 펼치기 · 역추적을 다시 하지 않고 첫 결과를 쓰게`

---

### Task 4: 문서

**Files:**
- Create: `docs/troubleshooting/2026-11-15-x-account-suspended-for-automation.md`
- Modify: `docs/runbook/` 의 X 쿠키 · 수집 런북이 있으면 그 문서에 「정지 메일이 오면」 절 (없으면 만들지 않는다 · 트러블슈팅 문서 §5 에 둔다)

- [ ] **Step 1: 트러블슈팅 문서** — 절 = §1 무슨 일 (163회차 · 10-20 ~ 11-09 · 정지 메일 11-08) · §2 왜 몰랐나 (실패 때 화면 단서 없음 · 반복 알림만) · §3 원인 (자동화 탐지 · 회차당 접근량 · 89% 반복) · §4 고친 것 (이 계획 · 표로) · §5 다시 생기면 (메일 확인 → 브라우저로 잠금 해제 · 새 계정으로 돌리지 않는다 · 정지 회피 금지 문구 인용)
- [ ] **Step 2: 서식 검사** — 저장 시 `.claude/hooks/check-doc-format.py` 훅 통과
- [ ] **Step 3: 커밋** — `docs(troubleshooting): X 계정이 자동화 탐지로 정지된 일 기록`

---

## 마무리 (컨트롤러가 직접)

- `.claude/tools/check-plan-scope.py --plan docs/superpowers/plans/2026-11-15-x-collection-cadence.md` 로 Files 밖 변경 확인
- 전체 시험 · 최종 리뷰 뒤 PR (본문 7섹션 · `check-pr-format.py --body` · 서명 줄 grep 0)
- 배포 확인 = 머지 뒤 첫 15:00 UTC 회차 로그에 `일정상 건너뜀: x_afcstuff · x_ornstein` · 다음 21:00 UTC 회차에 X 깔때기 `scraped` · `state/x_cache_*.json` 생성 · 그다음 21:00 UTC 회차의 기자 타임라인 수가 새 인용 트윗 수 이하
