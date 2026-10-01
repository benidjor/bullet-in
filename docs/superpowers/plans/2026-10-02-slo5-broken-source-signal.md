# SLO-5 끊김 신호 분리 구현 계획서

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SLO-5 가 「목록 응답」 과 「목록 변화」 로 끊김만 재고, 조용함은 화면에만 따로 보이게 한다.

**Architecture:** 판정은 `quality.py` 의 순수 함수 넷 (`list_signature` · `responded` · `evaluate_states` · `broken_alert_split`) 이 맡는다.
어댑터 셋은 수집 단계 기록 (`funnel`) 에 목록 지문과 개수를 남기고, `run.py` 게시 단계가 그것을 읽어 판정한 뒤 `source_freshness` 에 결과를 적는다.
알림 · 수집 현황 화면 · dbt Gold 는 저장된 `state` 를 읽는다.

**Tech Stack:** Python 3.11 · pytest · respx · SQLAlchemy (MariaDB) · Jinja2 · dbt-duckdb

**Spec:** `docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md`

## Global Constraints

- 상태 값은 `ok` · `quiet` · `no_response` · `broken` 넷뿐이다.
- 무응답은 2회 연속이어야 끊김이다.
- 상한은 `list_unchanged_cap_hours: 48` (모든 소스 같은 값) 이다.
- HTML 응답 조건은 `deduped ≥ 1` 이고 `titled × 2 ≥ deduped` 이다 (제목 확인 비율 절반 이상).
- 재알림 간격은 `FRESHNESS_REALERT_HOURS = 48.0` · 무응답 끊김은 16회 단위다.
- `stale` · `threshold_hours` 칼럼의 뜻은 바꾸지 않는다.
- 저장 키 `funnels` 는 그대로 두고, 문서와 화면 · 알림에서는 「수집 단계 기록」 이라고 부른다.
- 「급사」 · 「계수기」 라는 말은 새 코드 · 주석 · 문안에 쓰지 않는다.
- 문서는 저장소 서식 §2.2 (한 줄 한 문장 · `·` 와 여는 괄호 양옆 띄움 · `→` `—` 를 줄 끝에 두지 않음) 를 따르고, 하위 절 머리글과 문단 사이 빈 줄로 GitHub 에서 읽기 쉽게 쓴다.

## Review Focus

- **배포 뒤 첫 실행** — 직전 행에 새 칼럼이 비어 있어도 끊김이 나오면 안 된다 (Task 2 의 첫 실행 테스트).
- **무응답 다음 실행의 지문 비교** — 무응답 실행 뒤 목록이 그대로면 「바뀜」 으로 판정되면 안 된다 (Task 2 의 이어 적기 테스트).
- **워터마크가 없는 소스** — `last_fetched_at` 이 없는 소스도 상태가 매겨지고 알림 문안이 깨지지 않아야 한다 (Task 3 · Task 6 테스트).
- **제목 확인 비율의 경계** — 3/7 은 무응답, 4/7 은 응답이어야 한다 (Task 1 테스트).
- **옛 행이 섞인 화면** — `state` 가 빈 행만 있으면 SLO-5 는 「—」 이고 화면이 깨지지 않아야 한다 (Task 7 테스트).
- **수집 단계 기록이 없는 어댑터** — `arsenal_api` · `rss` 는 기록을 남기지 않아 `responded` 가 무응답으로 본다.
  지금은 둘 다 `freshness_hours: 0` 이라 감시에서 빠지지만, 나중에 임계를 주면 2회 뒤 끊김이 된다 (dry run 확인 · Task 1 의 `test_responded_without_record_is_no_response` 가 이 동작을 고정한다).

---

## 파일 구조

| 파일 | 할 일 |
| --- | --- |
| `src/bullet_in/quality.py` | 판정 함수 넷 · `SourceFreshness` 필드 · 옛 `freshness_alert_split` 제거 |
| `src/bullet_in/adapters/html.py` | 수집 단계 기록에 `list_sig` · `fetch()` 첫 줄 초기화 |
| `src/bullet_in/adapters/x_playwright.py` | 수집 단계 기록 (`scraped` · `passed` · `list_sig`) |
| `src/bullet_in/adapters/fmkorea.py` | 수집 단계 기록 (`keywords` · `searched` · `listed` · `passed` · `list_sig`) |
| `src/bullet_in/storage/schema.sql` | `source_freshness` 칼럼 다섯 |
| `src/bullet_in/storage/mariadb.py` | 저장 · 직전 행 · 화면 스냅샷이 새 칼럼을 쓰고 읽음 |
| `config/sources.yaml` | `list_unchanged_cap_hours: 48` |
| `src/bullet_in/run.py` | 게시 단계 판정 연결 · `source_responses` |
| `src/bullet_in/notify.py` | 끊김 문안 · 수집 단계 기록 줄 |
| `src/bullet_in/serve/ops_view.py` · `templates/_dash.html.j2` | 상태 칸 · 수집 단계 칸 · 타일 · SLO 5행 |
| `dbt/models/staging/stg_source_freshness.sql` · `dbt/models/gold/gold_slo_rollup.sql` · `dbt/models/sources.yml` | `state` 와 SLO-5 · 허용 값 테스트 |
| `docs/runbook/2026-08-20-freshness-threshold-recalibration.md` | 상한과 제목 확인 비율 절 |

---

## Task 0: 작업 환경

**Files:** 없음

- [ ] **Step 1: 워크트리 venv 를 3.11 로 만든다**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/slo5-broken-signal
uv venv --python 3.11 --project .
uv sync --project . --extra dev
```

- [ ] **Step 2: 기준선 테스트 수와 결과를 잰다**

```bash
uv run --project . --extra dev pytest -q 2>&1 | tail -3
```

Expected: 수집 1,792 · 1,792 passed · 1 skipped (2026-10-02 dry run 실측 · 통합 테스트는 MariaDB 가 없으면 skip).
수집 수를 적어 두고, 이후 전체 실행에서 이 수보다 줄면 수집 경로를 의심한다.

- [ ] **Step 3: 통합 테스트용 MariaDB 가 떠 있는지 본다**

```bash
docker compose -f /Users/aryijq/Documents/01_DE_project/bullet-in/docker-compose.yml ps
```

떠 있지 않으면 `docker compose up -d mariadb` 를 메인 체크아웃에서 실행한다.
Task 5 의 통합 테스트가 skip 되면 그 사실을 보고에 적는다.

---

## Task 1: 목록 지문과 응답 판정

**Files:**
- Modify: `src/bullet_in/quality.py` (머리 import · `SourceFreshness` 아래)
- Test: `tests/test_quality.py`

**Interfaces:**
- Produces: `list_signature(urls: Iterable[str]) -> str` · `responded(adapter: str | None, funnel: dict | None, errored: bool) -> tuple[bool, str]`
- 사유 코드: `"error"` · `"no_record"` · `"no_links"` · `"title_ratio"` · `"no_tweets"` · `"search_failed"` · `"no_results"` · 응답이면 `""`
- 2026-10-02 실행 중 판정 — 세 어댑터는 응답 조건을 만족해도 `list_sig` 가 비면 `(False, "no_record")` 다 (스펙 §2.2.4 · 지문 없는 응답은 기록 고장)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_quality.py` 의 import 줄에 `list_signature, responded` 를 더하고 파일 끝에 붙인다.

```python
# ── SLO-5 끊김 신호 (스펙 2026-10-02 §2.2 · §2.3) ─────────────────────────────

def test_list_signature_ignores_order_and_duplicates():
    a = list_signature(["https://x.test/2", "https://x.test/1", "https://x.test/1"])
    b = list_signature(["https://x.test/1", "https://x.test/2"])
    assert a == b and len(a) == 16


def test_list_signature_changes_when_one_link_changes():
    assert list_signature(["https://x.test/1", "https://x.test/2"]) != \
        list_signature(["https://x.test/1", "https://x.test/3"])


def test_list_signature_of_empty_list_is_empty_string():
    assert list_signature([]) == "" and list_signature(["", None]) == ""


def test_responded_error_wins_over_funnel():
    assert responded("html", {"deduped": 9, "titled": 9}, errored=True) == (False, "error")


def test_responded_without_record_is_no_response():
    assert responded("html", {}, errored=False) == (False, "no_record")
    assert responded("x_playwright", None, errored=False) == (False, "no_record")


def test_responded_html_needs_links():
    assert responded("html", {"selected": 0, "deduped": 0, "titled": 0}, False) == (False, "no_links")


def test_responded_html_title_ratio_boundary():
    # 2026-10-01 BBC Sport 실측은 7개 중 1개 (14%) 였다
    assert responded("html", {"deduped": 7, "titled": 1}, False) == (False, "title_ratio")
    assert responded("html", {"deduped": 7, "titled": 3}, False) == (False, "title_ratio")
    assert responded("html", {"deduped": 7, "titled": 4}, False) == (True, "")
    assert responded("html", {"deduped": 20, "titled": 20}, False) == (True, "")


def test_responded_x_needs_scraped_tweets():
    assert responded("x_playwright", {"scraped": 0, "passed": 0}, False) == (False, "no_tweets")
    assert responded("x_playwright", {"scraped": 30, "passed": 0}, False) == (True, "")


def test_responded_fmkorea_partial_failure_still_responds():
    assert responded("fmkorea", {"keywords": 3, "searched": 0, "listed": 0}, False) == (False, "search_failed")
    assert responded("fmkorea", {"keywords": 3, "searched": 1, "listed": 0}, False) == (False, "no_results")
    assert responded("fmkorea", {"keywords": 3, "searched": 1, "listed": 12}, False) == (True, "")


def test_responded_unknown_adapter_with_record_responds():
    assert responded("arsenal_api", {"anything": 1}, False) == (True, "")
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py -q -k "list_signature or responded"
```

Expected: ImportError (`list_signature` 없음).

- [ ] **Step 3: 구현한다**

`quality.py` 머리 import 에 `import hashlib` 과 `from collections.abc import Iterable` 을 더한다.
`SourceFreshness` 정의 바로 아래에 넣는다.

```python
def list_signature(urls: Iterable[str]) -> str:
    """목록 링크 묶음의 지문 — 순서와 중복은 무시한다 (스펙 2026-10-02 §2.3.2).

    같은 기사들의 순서만 바뀐 것은 목록이 바뀐 것으로 보지 않는다."""
    uniq = sorted({u for u in urls if u})
    if not uniq:
        return ""
    return hashlib.sha256("\n".join(uniq).encode()).hexdigest()[:16]


def responded(adapter: str | None, funnel: dict | None,
              errored: bool) -> tuple[bool, str]:
    """이번 실행에 목록이 응답했는가와 무응답 사유 (스펙 2026-10-02 §2.2).

    HTML 은 제목 확인 비율 (titled ÷ deduped) 이 절반 이상이어야 응답이다 —
    제목이 확인되지 않은 링크는 이적 키워드 검사까지 가지 못하고 버려진다."""
    if errored:
        return False, "error"
    if not funnel:
        return False, "no_record"
    if adapter == "html":
        links, titled = int(funnel.get("deduped", 0)), int(funnel.get("titled", 0))
        if links == 0:
            return False, "no_links"
        if titled * 2 < links:
            return False, "title_ratio"
        return True, ""
    if adapter == "x_playwright":
        return (True, "") if int(funnel.get("scraped", 0)) > 0 else (False, "no_tweets")
    if adapter == "fmkorea":
        if int(funnel.get("searched", 0)) == 0:
            return False, "search_failed"
        if int(funnel.get("listed", 0)) == 0:
            return False, "no_results"
        return True, ""
    return True, ""
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py -q
```

Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(quality): 목록 지문과 목록 응답 판정 함수 추가"
```

---

## Task 2: 소스 상태 판정

**Files:**
- Modify: `src/bullet_in/quality.py` (`SourceFreshness` 필드 · 새 함수)
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: Task 1 의 `responded` 반환 모양 `(bool, str)`
- Produces:
  - `SourceFreshness` 에 `state: str | None` · `miss_streak: int | None` · `list_sig: str | None` · `list_changed_at: datetime | None` · `cap_hours: float | None` · `reason: str` (저장하지 않음)
  - `LIST_UNCHANGED_CAP_HOURS = 48.0`
  - `evaluate_states(records, responses: dict[str, tuple[bool, str]], sigs: dict[str, str | None], cap_hours: float, previous: dict[str, dict], now: datetime) -> None`
  - `previous` 의 값 dict 키: `state` · `miss_streak` · `list_sig` · `list_changed_at` · `cap_hours` · `checked_at` (없으면 None)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

import 줄에 `evaluate_states, SourceFreshness` 를 더하고 파일 끝에 붙인다.

```python
_T0 = datetime(2026, 10, 2, 3, 0)


def _rec(sid="bbc_sport", age=10.0, thr=96.0):
    return SourceFreshness(sid, _T0 - timedelta(hours=age), thr, age, age > thr)


def _judge(rec, ok=True, reason="", sig="s1", prev=None, now=_T0, cap=48.0):
    evaluate_states([rec], {rec.source_id: (ok, reason)}, {rec.source_id: sig},
                    cap, {rec.source_id: prev} if prev else {}, now)
    return rec


def test_first_run_never_breaks_even_without_response():
    r = _judge(_rec(), ok=False, reason="title_ratio", sig=None)
    assert (r.state, r.miss_streak, r.list_changed_at) == ("no_response", 1, _T0)


def test_first_run_with_old_row_missing_new_columns_starts_fresh():
    old = {"state": None, "miss_streak": None, "list_sig": None,
           "list_changed_at": None, "cap_hours": None, "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), prev=old)
    assert (r.state, r.miss_streak, r.list_changed_at, r.cap_hours) == ("ok", 0, _T0, 48.0)


def test_two_misses_in_a_row_break():
    prev = {"state": "no_response", "miss_streak": 1, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=3), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), ok=False, reason="title_ratio", sig=None, prev=prev)
    assert (r.state, r.reason, r.miss_streak) == ("broken", "title_ratio", 2)


def test_response_resets_streak():
    prev = {"state": "broken", "miss_streak": 5, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=15), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(), sig="s2", prev=prev)
    assert (r.state, r.miss_streak, r.list_changed_at) == ("ok", 0, _T0)


def test_miss_carries_previous_signature_forward():
    # 무응답 실행이 지문을 비우면 다음 응답 실행이 빈 값과 비교해 「바뀜」 으로 오판한다
    changed = _T0 - timedelta(hours=40)
    prev = {"state": "ok", "miss_streak": 0, "list_sig": "s1", "list_changed_at": changed,
            "cap_hours": 48.0, "checked_at": _T0 - timedelta(hours=3)}
    miss = _judge(_rec(), ok=False, reason="error", sig=None, prev=prev)
    assert (miss.list_sig, miss.list_changed_at) == ("s1", changed)
    nxt = {"state": miss.state, "miss_streak": miss.miss_streak, "list_sig": miss.list_sig,
           "list_changed_at": miss.list_changed_at, "cap_hours": 48.0, "checked_at": _T0}
    back = _judge(_rec(), sig="s1", prev=nxt, now=_T0 + timedelta(hours=3))
    assert back.list_changed_at == changed and back.state == "ok"


def test_list_unchanged_past_cap_breaks_even_with_candidates():
    # 07-31 함정: 매 실행 응답하고 후보도 있는데 목록이 그대로면 결국 끊김이어야 한다
    prev = {"state": "ok", "miss_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=49), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(age=2.0), sig="s1", prev=prev)
    assert (r.state, r.reason) == ("broken", "list_unchanged")


def test_off_season_silence_is_quiet_not_broken():
    # 목록은 실행마다 바뀌고 새 원본만 2주째 없다
    prev = {"state": "quiet", "miss_streak": 0, "list_sig": "s1",
            "list_changed_at": _T0 - timedelta(hours=3), "cap_hours": 48.0,
            "checked_at": _T0 - timedelta(hours=3)}
    r = _judge(_rec(age=336.0, thr=96.0), sig="s2", prev=prev)
    assert (r.state, r.stale) == ("quiet", True)


def test_source_without_watermark_still_gets_a_state():
    r = SourceFreshness("new_source", None, 48.0, None, False)
    evaluate_states([r], {"new_source": (True, "")}, {"new_source": "s1"}, 48.0, {}, _T0)
    assert r.state == "ok"


def test_missing_response_entry_counts_as_no_record():
    r = _rec()
    evaluate_states([r], {}, {}, 48.0, {}, _T0)
    assert (r.state, r.reason) == ("no_response", "no_record")
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py -q -k "first_run or misses or streak or carries or unchanged or off_season or watermark or response_entry"
```

Expected: ImportError (`evaluate_states` 없음).

- [ ] **Step 3: 구현한다**

`SourceFreshness` 의 마지막 필드 (`stored_fetched_at`) 아래에 필드를 더한다.

```python
    # SLO-5 끊김 판정 (스펙 2026-10-02 §2) — evaluate_states 가 채운다.
    state: str | None = None            # ok · quiet · no_response · broken
    miss_streak: int | None = None      # 연속 무응답 횟수
    list_sig: str | None = None         # 마지막으로 응답한 실행의 목록 지문
    list_changed_at: datetime | None = None
    cap_hours: float | None = None
    reason: str = ""                    # 저장하지 않는다 — 알림 문안용
```

`responded` 아래에 넣는다.

```python
# 목록이 이만큼 바뀌지 않으면 「옛 글만 보이는」 고장으로 본다 (스펙 2026-10-02 §2.3.3).
LIST_UNCHANGED_CAP_HOURS = 48.0


def evaluate_states(records: list[SourceFreshness],
                    responses: dict[str, tuple[bool, str]],
                    sigs: dict[str, str | None], cap_hours: float,
                    previous: dict[str, dict], now: datetime) -> None:
    """소스마다 상태 넷 가운데 하나를 매기고 이어 적을 값을 채운다 (스펙 §2.1 · §2.5).

    무응답 실행은 지문과 바뀐 시각을 직전 값 그대로 잇는다 — 비워 두면 다음 응답
    실행이 빈 값과 비교해 목록이 그대로여도 「바뀜」 으로 판정한다."""
    for r in records:
        ok, reason = responses.get(r.source_id, (False, "no_record"))
        prev = previous.get(r.source_id) or {}
        prev_sig, prev_changed = prev.get("list_sig"), prev.get("list_changed_at")
        if ok:
            r.miss_streak = 0
            r.list_sig = sigs.get(r.source_id) or None
            r.list_changed_at = (now if prev_changed is None or r.list_sig != prev_sig
                                 else prev_changed)
        else:
            r.miss_streak = int(prev.get("miss_streak") or 0) + 1
            r.list_sig = prev_sig
            r.list_changed_at = prev_changed or now
        r.cap_hours = cap_hours
        unchanged = (now - r.list_changed_at).total_seconds() / 3600
        if not ok and r.miss_streak >= 2:
            r.state, r.reason = "broken", reason
        elif unchanged > cap_hours:
            r.state, r.reason = "broken", "list_unchanged"
        elif not ok:
            r.state, r.reason = "no_response", reason
        elif r.stale:
            r.state, r.reason = "quiet", ""
        else:
            r.state, r.reason = "ok", ""
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py -q
```

Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(quality): 목록 응답과 목록 변화로 소스 상태를 매기는 판정 추가"
```

---

## Task 3: 끊김 알림 분할

**Files:**
- Modify: `src/bullet_in/quality.py` (`broken_alert_split` 을 `freshness_alert_split` 옆에 더함 · 옛 함수는 Task 6 에서 지운다)
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: Task 2 의 `SourceFreshness` 새 필드 · `previous` 의 `checked_at`
- Produces: `REALERT_RUNS = 16` · `broken_alert_split(records, previous, now, interval_hours=FRESHNESS_REALERT_HOURS, runs_per_interval=REALERT_RUNS) -> tuple[list[SourceFreshness], list[FreshnessHold]]`

- [ ] **Step 1: 새 테스트를 쓴다**

`tests/test_quality.py` import 줄에 `broken_alert_split` 을 더한다.
옛 `freshness_alert_split` 과 그 테스트는 이 태스크에서 지우지 않는다 — `run.py` 가 Task 6 까지 그것을 import 하므로, 지금 지우면 `import bullet_in.run` 이 깨진다.

```python
def _broken(miss=0, changed_h=10.0, cap=48.0, now=_T0, sid="bbc_sport"):
    r = _rec(sid)
    r.state, r.miss_streak, r.cap_hours = "broken", miss, cap
    r.list_changed_at = now - timedelta(hours=changed_h)
    r.reason = "title_ratio" if miss >= 2 else "list_unchanged"
    return r


def _prev_of(r, at):
    return {r.source_id: {"state": r.state, "miss_streak": r.miss_streak, "list_sig": r.list_sig,
                          "list_changed_at": r.list_changed_at, "cap_hours": r.cap_hours,
                          "checked_at": at}}


def test_broken_alert_sends_on_first_broken_run():
    send, hold = broken_alert_split([_broken(miss=2)], {}, _T0)
    assert [r.source_id for r in send] == ["bbc_sport"] and hold == []


def test_broken_alert_holds_within_same_interval_then_resends():
    first = _broken(miss=2)
    prev = _prev_of(first, _T0)
    later = _broken(miss=17, now=_T0 + timedelta(hours=45))       # 2 + 15 → 같은 16회 구간
    assert broken_alert_split([later], prev, _T0 + timedelta(hours=45))[0] == []
    again = _broken(miss=18, now=_T0 + timedelta(hours=48))       # 2 + 16 → 다음 구간
    assert len(broken_alert_split([again], prev, _T0 + timedelta(hours=48))[0]) == 1


def test_broken_alert_list_unchanged_realerts_every_48_hours():
    first = _broken(changed_h=49)
    prev = _prev_of(first, _T0)
    same = _broken(changed_h=95, now=_T0 + timedelta(hours=46))
    assert broken_alert_split([same], prev, _T0 + timedelta(hours=46))[0] == []
    nxt = _broken(changed_h=97, now=_T0 + timedelta(hours=48))
    assert len(broken_alert_split([nxt], prev, _T0 + timedelta(hours=48))[0]) == 1


def test_broken_alert_resends_when_reason_kind_changes():
    first = _broken(changed_h=49)                                 # 목록 그대로
    prev = _prev_of(first, _T0)
    now_miss = _broken(miss=2, changed_h=52, now=_T0 + timedelta(hours=3))
    assert len(broken_alert_split([now_miss], prev, _T0 + timedelta(hours=3))[0]) == 1


def test_broken_alert_resends_when_cap_changes():
    first = _broken(changed_h=49)
    prev = _prev_of(first, _T0)
    moved = _broken(changed_h=52, cap=50.0, now=_T0 + timedelta(hours=3))
    assert len(broken_alert_split([moved], prev, _T0 + timedelta(hours=3))[0]) == 1


def test_broken_alert_ignores_non_broken_and_holds_without_watermark():
    quiet = _rec(); quiet.state = "quiet"
    nowm = _broken(miss=2, sid="new_source"); nowm.age_hours = None
    send, hold = broken_alert_split([quiet, nowm], _prev_of(nowm, _T0), _T0)
    assert send == [] and hold[0].source_id == "new_source" and hold[0].age_hours == 0.0
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py -q -k broken_alert
```

Expected: ImportError (`broken_alert_split` 없음).

- [ ] **Step 3: 구현한다**

`freshness_alert_split` 바로 아래에 넣는다 (옛 함수 · `_realert_level` · `FRESHNESS_REALERT_HOURS` · `FreshnessHold` 는 그대로 둔다).

```python
# 무응답 끊김의 재알림 단위 — 3시간 실행 × 16 = 48시간 (스펙 2026-10-02 §4.1.2).
REALERT_RUNS = 16


def _broken_level(miss_streak, list_changed_at, cap_hours, at,
                  interval_hours: float, runs_per_interval: int) -> tuple[str, int, float]:
    """끊긴 종류 · 재알림 구간 · 다음 구간까지 남은 시간 (시간)."""
    if (miss_streak or 0) >= 2:
        done = miss_streak - 2
        level = done // runs_per_interval
        return "miss", level, ((level + 1) * runs_per_interval - done) * 3.0
    over = (at - list_changed_at).total_seconds() / 3600 - (cap_hours or 0.0)
    level = int(over // interval_hours)
    return "list", level, round((level + 1) * interval_hours - over, 1)


def broken_alert_split(records: list[SourceFreshness], previous: dict[str, dict],
                       now: datetime,
                       interval_hours: float = FRESHNESS_REALERT_HOURS,
                       runs_per_interval: int = REALERT_RUNS
                       ) -> tuple[list[SourceFreshness], list[FreshnessHold]]:
    """끊김 소스를 이번 실행 발송분과 보류분으로 가른다 (스펙 2026-10-02 §4.1.2).

    직전 행과 비교하는 무상태 판정이다. 직전 행이 끊김이 아니었거나, 끊긴 종류가
    바뀌었거나, 상한이 바뀌었거나, 재알림 구간이 올라가면 보낸다."""
    send: list[SourceFreshness] = []
    hold: list[FreshnessHold] = []
    for r in records:
        if r.state != "broken":
            continue
        kind, level, to_next = _broken_level(r.miss_streak, r.list_changed_at, r.cap_hours,
                                             now, interval_hours, runs_per_interval)
        prev = previous.get(r.source_id) or {}
        if (prev.get("state") == "broken" and prev.get("cap_hours") == r.cap_hours
                and prev.get("checked_at") is not None):
            p_kind, p_level, _ = _broken_level(
                prev.get("miss_streak"), prev.get("list_changed_at"), prev.get("cap_hours"),
                prev["checked_at"], interval_hours, runs_per_interval)
            if p_kind == kind and level <= p_level:
                hold.append(FreshnessHold(r.source_id, r.age_hours or 0.0, to_next))
                continue
        send.append(r)
    return send, hold
```

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_quality.py tests/test_run_stages.py -q
```

Expected: 전부 PASS.

- [ ] **Step 5: 커밋한다**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(quality): 끊김 소스를 발송분과 보류분으로 가르는 알림 분할 추가"
```

---

## Task 4: 어댑터 셋의 수집 단계 기록

**Files:**
- Modify: `src/bullet_in/adapters/html.py` (`fetch` 첫 줄 · 루프 뒤)
- Modify: `src/bullet_in/adapters/x_playwright.py` (`__init__` · `fetch`)
- Modify: `src/bullet_in/adapters/fmkorea.py` (`__init__` · `_discover` · `fetch`)
- Test: `tests/test_html_adapter.py` · `tests/test_x_playwright.py` · `tests/test_fmkorea_adapter.py`

**Interfaces:**
- Consumes: Task 1 의 `list_signature`
- Produces:
  - HTML `funnel` = `{"selected", "deduped", "titled", "passed", "list_sig"}`
  - X `funnel` = `{"scraped", "passed", "list_sig"}` · 순수 함수 `tweet_list_urls(raw_tweets: list[dict]) -> list[str]`
  - fmkorea `funnel` = `{"keywords", "searched", "listed", "passed", "list_sig"}`

- [ ] **Step 1: HTML 테스트를 고치고 더한다**

`tests/test_html_adapter.py` 의 기존 깔때기 테스트 둘 (282행 머리 주석 아래) 의 기대값에 `list_sig` 를 더한다.
`test_html_adapter_counts_each_discovery_stage` (304행) 는 아래처럼 바꾼다 (중복을 뺀 링크가 /a · /b · /c 셋이다).

```python
    assert a.funnel == {"selected": 5, "deduped": 3, "titled": 2, "passed": 1,
                        "list_sig": list_signature(["https://a.test/a", "https://a.test/b",
                                                    "https://a.test/c"])}
```

나머지 하나 (`shows_zero_at_the_top`) 는 아래 블록대로 바꾸고, 원래 있던 주석 줄과 `@respx.mock` 장식자는 그대로 둔다.
머리 주석 「발견 퍼널 4단」 은 「수집 단계 기록」 으로 바꾼다.

```python
def test_html_adapter_funnel_shows_zero_at_the_top_when_selector_breaks():
    respx.get("https://a.test/news").mock(
        return_value=httpx.Response(200, text="<div>개편된 페이지</div>"))
    a = _funnel_adapter()
    assert asyncio.run(a.fetch()) == []
    assert a.funnel == {"selected": 0, "deduped": 0, "titled": 0, "passed": 0, "list_sig": ""}


@respx.mock
def test_html_adapter_funnel_signature_follows_deduped_links():
    page = ('<a class="card" href="/n/1"><h3>Arsenal sign</h3></a>'
            '<a class="card" href="/n/1"><h3>Arsenal sign</h3></a>'
            '<a class="card" href="/n/2">본문 속 링크</a>')
    respx.get("https://a.test/news").mock(return_value=httpx.Response(200, text=page))
    a = _funnel_adapter()
    asyncio.run(a.fetch())
    assert a.funnel["deduped"] == 2 and a.funnel["titled"] == 1
    assert a.funnel["list_sig"] == list_signature(["https://a.test/n/1", "https://a.test/n/2"])
```

`_funnel_adapter()` 는 `item_selector="a.card"` · `title_selector="h3"` · `base_url="https://a.test"` 이다 (같은 파일 292행).
`from bullet_in.quality import list_signature` 를 import 에 더한다.

- [ ] **Step 2: X 테스트를 더한다**

```python
from bullet_in.adapters.x_playwright import tweet_list_urls


def test_tweet_list_urls_uses_author_and_status_id_and_skips_missing():
    raw = [{"author": "afcstuff", "status_id": "1"}, {"author": "afcstuff", "status_id": ""},
           {"author": "", "status_id": "2"}]
    assert tweet_list_urls(raw) == ["afcstuff/status/1", "/status/2"]
```

- [ ] **Step 3: fmkorea 테스트를 더한다**

`tests/test_fmkorea_adapter.py` 의 respx 픽스처 (`SEARCH_KW1` · `SEARCH_KW2`) 를 그대로 쓰는 테스트 둘을 더한다.
첫 테스트는 기존 정상 경로 테스트와 같은 mock 을 걸고 `fetch()` 뒤 `funnel` 을 본다.

```python
@respx.mock
def test_fmkorea_funnel_counts_search_results_before_filters():
    _mock_search_and_bodies()
    a = _adapter()
    items = asyncio.run(a.fetch())
    # 검색 결과 글은 111 · 222 · 333 셋 (222 는 두 검색어에 겹친다)
    assert a.funnel["keywords"] == 2 and a.funnel["searched"] == 2
    assert a.funnel["listed"] == 3 and a.funnel["passed"] == len(items) == 3
    assert len(a.funnel["list_sig"]) == 16


@respx.mock
def test_fmkorea_funnel_all_searches_430():
    respx.get(url__regex=r"https://fm\.test/s\?.*").mock(return_value=httpx.Response(430))
    a = _adapter()
    assert asyncio.run(a.fetch()) == []
    assert a.funnel == {"keywords": 2, "searched": 0, "listed": 0, "passed": 0, "list_sig": ""}
```

- [ ] **Step 4: 기존 mock 과 어댑터 생성을 함수로 뽑는다**

`tests/test_fmkorea_adapter.py` 의 `test_fmkorea_search_union_dedup` (22행) 안에 있는 `respx.get(...)` 일곱 줄과 `FmkoreaAdapter(...)` 생성을 아래 두 함수로 옮기고, 그 테스트가 두 함수를 부르게 바꾼다.

```python
def _mock_search_and_bodies():
    respx.get("https://fm.test/s?t=title&kw=kw1").mock(return_value=httpx.Response(200, text=SEARCH_KW1))
    respx.get("https://fm.test/s?t=title_content&kw=kw2").mock(return_value=httpx.Response(200, text=SEARCH_KW2))
    respx.get("https://www.fmkorea.com/111").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://www.fmkorea.com/222").mock(return_value=httpx.Response(200, text=PAY_BODY))
    respx.get("https://www.fmkorea.com/333").mock(return_value=httpx.Response(200, text=FREE_BODY))
    respx.get("https://ex.test/a").mock(return_value=httpx.Response(200, text=FREE_ART))
    respx.get("https://www.nytimes.com/athletic/9/b").mock(return_value=httpx.Response(200, text=""))


def _adapter():
    return FmkoreaAdapter(source_id="fmkorea", search_url="https://fm.test/s?t={target}&kw={keyword}",
                          search_keywords=[{"keyword": "kw1", "target": "title"},
                                           {"keyword": "kw2", "target": "title_content"}],
                          base_url="https://www.fmkorea.com")
```

- [ ] **Step 5: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_html_adapter.py tests/test_x_playwright.py tests/test_fmkorea_adapter.py -q
```

Expected: `list_sig` · `tweet_list_urls` · fmkorea `funnel` 이 없어 FAIL.

- [ ] **Step 6: HTML 을 구현한다**

`html.py` `fetch()` 의 첫 줄 (import 다음) 에 `self.funnel = {}` 를 넣는다.
`for a in selected:` 루프가 끝난 바로 뒤 (`out = []` 앞) 에 넣는다.

```python
            # 목록 지문 — 키워드 필터 앞의 링크 묶음 (스펙 2026-10-02 §2.3.2)
            self.funnel["list_sig"] = list_signature(seen)
```

모듈 머리에 `from bullet_in.quality import list_signature` 를 더한다.

- [ ] **Step 7: X 를 구현한다**

모듈 함수로 더한다 (`_scroll_collect` 아래).

```python
def tweet_list_urls(raw_tweets: list[dict]) -> list[str]:
    """타임라인 트윗 주소 묶음 — 필터 전 목록 지문의 재료 (스펙 2026-10-02 §2.3.2)."""
    return [f"{t.get('author') or ''}/status/{t['status_id']}"
            for t in raw_tweets if t.get("status_id")]
```

`__init__` 끝에 `self.funnel: dict = {}` 를 더한다.
`fetch()` 첫 줄 (import 다음) 에 `self.funnel = {}` 를 넣고, `raw_tweets = await _scroll_collect(...)` 바로 다음 줄에 넣는다.

```python
            self.funnel = {"scraped": len(raw_tweets), "passed": 0,
                           "list_sig": list_signature(tweet_list_urls(raw_tweets))}
```

`fetch()` 의 마지막 `return items` 바로 앞에 `self.funnel["passed"] = len(items)` 를 넣는다.
모듈 머리에 `from bullet_in.quality import list_signature` 를 더한다.

- [ ] **Step 8: fmkorea 를 구현한다**

`__init__` 의 `self.relevance_dropped = 0` 아래에 `self.funnel: dict = {}` 를 더한다.
`_discover` 에 여섯 군데를 더하거나 바꾼다 (나머지 줄은 그대로 둔다).

| 자리 (지금 줄) | 바꾸는 내용 |
| --- | --- |
| `per_kw, seen, first = [], set(), True` 다음 줄 | `searched, listed = 0, set()` 를 더한다 |
| `results = []` (검색어 루프 첫 줄) | `results, kw_ok = [], False` 로 바꾼다 |
| `soup = BeautifulSoup(r.text, "html.parser")` 바로 앞 | `kw_ok = True` 를 더한다 (예외 경로는 `break` 로 빠지므로 여기에 닿지 않는다) |
| `post_url = _post_url_from_href(a.get("href", ""), self.base_url)` 다음 줄 | 아래 두 줄을 더한다 |
| `per_kw.append(results)` 바로 앞 | `searched += kw_ok` 를 더한다 |
| `return _round_robin(...)` 바로 앞 | 아래 `self.funnel = {...}` 를 더한다 |

```python
                    if post_url:
                        listed.add(post_url)      # 필터 전 결과 글 (스펙 2026-10-02 §3.1)
```

```python
        self.funnel = {"keywords": len(self.search_keywords), "searched": searched,
                       "listed": len(listed), "passed": 0,
                       "list_sig": list_signature(listed)}
```

`fetch()` 를 바꾼다.

```python
    async def fetch(self) -> list[RawItem]:
        self.funnel = {}
        async with self._client() as c:
            matched = await self._discover(c)
            items = await self._process(c, matched)
        self.funnel["passed"] = len(items)
        return items
```

모듈 머리에 `from bullet_in.quality import list_signature` 를 더한다.

- [ ] **Step 9: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_html_adapter.py tests/test_x_playwright.py tests/test_fmkorea_adapter.py tests/test_collect_fmkorea.py tests/test_watchlist_fmkorea.py -q
```

Expected: 전부 PASS.

- [ ] **Step 10: 커밋한다**

```bash
git add src/bullet_in/adapters tests/test_html_adapter.py tests/test_x_playwright.py tests/test_fmkorea_adapter.py
git commit -m "feat(adapters): X · fmkorea 수집 단계 기록과 세 어댑터의 목록 지문 추가"
```

---

## Task 5: 저장 칼럼과 설정

**Files:**
- Modify: `src/bullet_in/storage/schema.sql` (끝)
- Modify: `src/bullet_in/storage/mariadb.py` (`record_freshness` · `previous_freshness` · `ops_snapshot`)
- Modify: `config/sources.yaml` (최상위 · `freshness_default_hours` 근처)
- Test: `tests/integration/test_source_freshness.py` · `tests/integration/test_ops_snapshot.py`

**Interfaces:**
- Consumes: Task 2 의 `SourceFreshness` 새 필드
- Produces:
  - `previous_freshness()` 값 dict 키 = `age_hours` · `threshold_hours` · `state` · `miss_streak` · `list_sig` · `list_changed_at` · `cap_hours` · `checked_at`
  - `ops_snapshot()` 의 `freshness` 행에 `state` · `miss_streak` · `list_changed_at` · `cap_hours` · 새 키 `latest_funnels: dict[str, dict]`

- [ ] **Step 1: 통합 테스트를 쓴다**

`tests/integration/test_source_freshness.py` 끝에 붙인다.

```python
def test_record_and_previous_freshness_round_trip_new_columns(engine):
    store = MartStore(engine)
    at = datetime(2026, 10, 2, 3, 0)
    [r] = evaluate_freshness({"bbc_sport": at - timedelta(hours=10)}, at, 96.0)
    r.state, r.miss_streak, r.list_sig = "no_response", 1, "abcd1234abcd1234"
    r.list_changed_at, r.cap_hours = at - timedelta(hours=6), 48.0
    store.record_freshness("run-1", at, [r])
    prev = store.previous_freshness()["bbc_sport"]
    assert (prev["state"], prev["miss_streak"], prev["list_sig"]) == ("no_response", 1, "abcd1234abcd1234")
    assert prev["list_changed_at"] == at - timedelta(hours=6)
    assert prev["cap_hours"] == 48.0 and prev["checked_at"] == at


def test_previous_freshness_old_rows_return_none_for_new_columns(engine):
    store = MartStore(engine)
    at = datetime(2026, 10, 2, 0, 0)
    store.record_freshness("run-old", at, evaluate_freshness(
        {"bbc_sport": at - timedelta(hours=2)}, at, 96.0))
    prev = store.previous_freshness()["bbc_sport"]
    assert prev["state"] is None and prev["miss_streak"] is None and prev["list_changed_at"] is None
```

`tests/integration/test_ops_snapshot.py` 의 기존 테스트 `test_ops_snapshot_cold_start_returns_empty_shapes` (130행) 는 스냅샷 dict 를 통째로 비교하므로 새 키를 더한다.

```python
    assert snap == {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [],
                    "player_subjects": [], "articles_total": 0, "high_retention": [],
                    "latest_funnels": {}}
```

같은 파일 끝에 붙인다 (`json` · `text` import 가 없으면 더한다).

```python
def test_ops_snapshot_returns_latest_run_funnels(engine):
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id, started_at, finished_at, fetch_detail) "
            "VALUES ('r9', '2026-10-02 03:00:00', '2026-10-02 03:05:00', :d)"),
            {"d": json.dumps({"errors": {}, "funnels": {"bbc_sport": {"deduped": 7, "titled": 1}}})})
    snap = MartStore(engine).ops_snapshot()
    assert snap["latest_funnels"]["bbc_sport"]["titled"] == 1
```

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/integration/test_source_freshness.py tests/integration/test_ops_snapshot.py -q
```

Expected: 칼럼 없음 · 키 없음으로 FAIL (MariaDB 가 없으면 skip · 그 사실을 기록한다).

- [ ] **Step 3: 스키마를 더한다**

`schema.sql` 끝에 붙인다.

```sql
-- SLO-5 끊김 판정 (스펙 2026-10-02 §3.2) — 추가만 한다 · stale 의 뜻은 그대로
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS state VARCHAR(16) NULL;
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS miss_streak INT NULL;
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS list_sig VARCHAR(16) NULL;
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS list_changed_at DATETIME NULL;
ALTER TABLE source_freshness ADD COLUMN IF NOT EXISTS cap_hours FLOAT NULL;
```

- [ ] **Step 4: 저장 · 읽기를 고친다**

`record_freshness` 의 INSERT 를 바꾼다.

```python
            c.execute(text(
                "INSERT INTO source_freshness (run_id,checked_at,source_id,"
                "last_fetched_at,age_hours,threshold_hours,stale,stored_fetched_at,"
                "state,miss_streak,list_sig,list_changed_at,cap_hours) "
                "VALUES (:rid,:at,:sid,:wm,:age,:thr,:stale,:stored,"
                ":state,:miss,:sig,:changed,:cap)"),
                [{"rid": run_id, "at": checked_at, "sid": r.source_id,
                  "wm": r.last_fetched_at, "age": r.age_hours,
                  "thr": r.threshold_hours, "stale": r.stale,
                  "stored": r.stored_fetched_at, "state": r.state,
                  "miss": r.miss_streak, "sig": r.list_sig,
                  "changed": r.list_changed_at, "cap": r.cap_hours}
                 for r in records])
```

`previous_freshness` 의 SELECT 를 바꾼다.

```python
                "SELECT source_id, age_hours, threshold_hours, state, miss_streak, "
                "list_sig, list_changed_at, cap_hours, checked_at FROM source_freshness "
```

`ops_snapshot` 의 `freshness` SELECT 칼럼 목록에 `state,miss_streak,list_changed_at,cap_hours` 를 더한다.
같은 함수의 `with` 블록 안, 반환 dict 를 만들기 전에 넣고 반환 dict 에 `"latest_funnels": latest_funnels` 를 더한다.

```python
            detail = c.execute(text(
                "SELECT fetch_detail FROM pipeline_runs WHERE finished_at IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1")).scalar()
            if isinstance(detail, (str, bytes)):
                detail = json.loads(detail)
            latest_funnels = dict((detail or {}).get("funnels") or {})
```

- [ ] **Step 5: 설정을 더한다**

`config/sources.yaml` 의 `freshness_default_hours` 줄 바로 아래에 넣는다.

```yaml
# 목록이 이만큼 바뀌지 않으면 「옛 글만 보이는」 고장으로 보고 끊김으로 센다 (스펙 2026-10-02 §2.3).
# 기준은 키워드 필터 앞의 목록이다 — 팀 · 가십 페이지 · X 타임라인 · fmkorea 검색은 이적 기사가
# 없어도 매일 바뀐다 (2026-10-01 실측 · Guardian 목록 20건 중 키워드 통과 1건). 모든 소스 같은 값.
list_unchanged_cap_hours: 48
```

- [ ] **Step 6: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/integration -q
```

Expected: 전부 PASS (MariaDB 가 없으면 skip 수를 보고에 적는다).

- [ ] **Step 7: 커밋한다**

```bash
git add src/bullet_in/storage config/sources.yaml tests/integration
git commit -m "feat(storage): source_freshness 에 끊김 판정 칼럼 다섯과 목록 변화 상한 설정 추가"
```

---

## Task 6: 게시 단계 연결과 알림 문안

**Files:**
- Modify: `src/bullet_in/run.py` (import · `source_responses` 추가 · 신선도 판정 블록 595 ~ 625행)
- Modify: `src/bullet_in/notify.py` (`_FUNNEL_STAGES` · `_funnel_lines` · `build_freshness_alert` · 새 `broken_reason_text`)
- Test: `tests/test_slo5_wiring.py` (새 파일) · `tests/test_notify.py` · `tests/test_run_cliff_alert.py`

**Interfaces:**
- Consumes: Task 1 ~ 3 의 함수 · Task 5 의 `previous_freshness` 키 · `cfg["list_unchanged_cap_hours"]`
- Produces:
  - `run.source_responses(sources: dict, fetched: FetchSummary) -> dict[str, tuple[bool, str]]`
  - `notify.broken_reason_text(r: SourceFreshness, funnel: dict | None, error: str | None, now: datetime | None = None) -> str`
  - `notify.build_freshness_alert(..., broken: bool = False)` — `broken=True` 면 끊김 문안

- [ ] **Step 1: 연결 테스트를 쓴다**

`tests/test_slo5_wiring.py` 를 만든다.

```python
from datetime import datetime
from bullet_in.run import FetchSummary, source_responses

SOURCES = {"bbc_sport": {"adapter": "html"}, "x_ornstein": {"adapter": "x_playwright"},
           "fmkorea": {"adapter": "fmkorea"}, "arsenal_official": {"adapter": "arsenal_api"}}


def _fetched(errors=None, funnels=None):
    return FetchSummary(run_id="r1", started_at_utc=datetime(2026, 10, 2), fetch_sec=1.0,
                        source_counts={}, candidate_counts={}, new_count=0, dup_count=0,
                        blocked_count=0, errors=errors or {}, funnels=funnels or {},
                        success_rate=1.0)


def test_source_responses_reads_errors_and_funnels_per_adapter():
    f = _fetched(errors={"x_ornstein": "Timeout 20000ms"},
                 funnels={"bbc_sport": {"deduped": 7, "titled": 1, "list_sig": "s1"},
                          "fmkorea": {"keywords": 3, "searched": 2, "listed": 40, "list_sig": "s2"}})
    got = source_responses(SOURCES, f)
    assert got["bbc_sport"] == (False, "title_ratio")
    assert got["x_ornstein"] == (False, "error")
    assert got["fmkorea"] == (True, "")
    assert got["arsenal_official"] == (False, "no_record")
```

- [ ] **Step 2: 알림 테스트를 고치고 더한다**

`tests/test_notify.py` · `tests/test_run_cliff_alert.py` 에서 「발견 퍼널: 목록 13 → URL 13 → 제목 7 → 키워드 3」 을 「수집 단계 기록: 목록 13 → URL 13 → 제목 확인 7 → 키워드 3」 으로 바꾼다 (`test_run_cliff_alert.py:46` · `test_notify.py:866` · `:884`).
`test_notify.py:872` 의 부정 단언 `assert "발견 퍼널" not in ...` 도 `assert "수집 단계 기록" not in ...` 으로 바꾼다 — 그대로 두면 아무것도 확인하지 않는 단언이 된다.
`tests/test_notify.py` 858행 머리 주석의 「발견 퍼널 4단」 도 「수집 단계 기록」 으로 바꾼다.
파일 끝에 붙인다.

```python
def _broken_rec(reason, miss=2, changed_h=10.0, sid="bbc_sport"):
    checked = datetime(2026, 10, 2, 6, 0)
    r = SourceFreshness(sid, checked - timedelta(hours=226), 96.0, 226.0, True)
    r.state, r.reason, r.miss_streak, r.cap_hours = "broken", reason, miss, 48.0
    r.list_changed_at = checked - timedelta(hours=changed_h)
    return checked, r


def test_broken_reason_title_ratio_spells_out_counts():
    _, r = _broken_rec("title_ratio")
    text = notify.broken_reason_text(r, {"deduped": 7, "titled": 1}, None)
    assert text == "목록에서 기사 링크 7개를 찾았지만, 제목까지 확인된 것은 1개뿐 (14%) · 2회 연속"


def test_broken_reason_no_record_points_at_the_monitor():
    _, r = _broken_rec("no_record", miss=3)
    assert notify.broken_reason_text(r, None, None) == \
        "수집 단계 기록 없음 · 3회 연속 — 소스가 아니라 감시 기록이 고장 났을 수 있음"


def test_broken_reason_list_unchanged_uses_hours_and_cap():
    checked, r = _broken_rec("list_unchanged", miss=0, changed_h=52.0)
    assert notify.broken_reason_text(r, {"deduped": 20, "titled": 20}, None, now=checked) == \
        "목록은 응답하지만 52시간째 바뀌지 않음 (상한 48시간)"


def test_broken_reason_error_quotes_the_error():
    _, r = _broken_rec("error")
    assert notify.broken_reason_text(r, None, "HTTP 403 Forbidden") == \
        "목록이 2회 연속 응답하지 않음 · 오류: HTTP 403 Forbidden"


def test_build_freshness_alert_broken_title_and_state_counts():
    checked, r = _broken_rec("title_ratio")
    quiet = SourceFreshness("guardian", checked - timedelta(hours=226), 192.0, 226.0, True)
    quiet.state = "quiet"
    alert = notify.build_freshness_alert(
        [r, quiet], 48, targets=[r], sources=_FRESH_SOURCES, run_id="abcdef1234",
        checked_at=checked, funnels={"bbc_sport": {"deduped": 7, "titled": 1}}, broken=True)
    assert alert["title"].startswith("🔌 수집 끊김 — BBC Sport")
    assert "끊김 1 · 응답 없음 0 · 조용함 1 · 정상 0" in alert["description"]
    assert "제목까지 확인된 것은 1개뿐" in str(alert["fields"])


def test_funnel_lines_for_x_and_fmkorea():
    assert notify._funnel_lines({"scraped": 30, "passed": 2, "list_sig": "x"}) == \
        ["수집 단계 기록: 타임라인 트윗 30 → 필터 통과 2"]
    assert notify._funnel_lines({"keywords": 3, "searched": 2, "listed": 40, "passed": 5}) == \
        ["수집 단계 기록: 검색어 2/3 · 결과 글 40 → 필터 통과 5"]
```

- [ ] **Step 3: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_slo5_wiring.py tests/test_notify.py tests/test_run_cliff_alert.py -q
```

Expected: `source_responses` · `broken_reason_text` 없음 · 문구 불일치로 FAIL.

- [ ] **Step 4: notify 를 구현한다**

`_FUNNEL_STAGES` 의 `("titled", "제목")` 을 `("titled", "제목 확인")` 으로 바꾸고, `_funnel_lines` 를 바꾼다.

```python
def _funnel_lines(funnel: dict | None) -> list[str]:
    """수집 단계 기록을 줄로 (스펙 2026-08-14 §8.2 · 2026-10-02 §3.1).

    어댑터마다 키가 다르다 — HTML 은 네 단계, X 는 타임라인 트윗, fmkorea 는 검색."""
    if not funnel:
        return []
    if "scraped" in funnel:
        return [f"수집 단계 기록: 타임라인 트윗 {funnel.get('scraped', 0)} "
                f"→ 필터 통과 {funnel.get('passed', 0)}"]
    if "keywords" in funnel:
        return [f"수집 단계 기록: 검색어 {funnel.get('searched', 0)}/{funnel.get('keywords', 0)} · "
                f"결과 글 {funnel.get('listed', 0)} → 필터 통과 {funnel.get('passed', 0)}"]
    chain = " → ".join(f"{label} {funnel.get(key, 0)}"
                       for key, label in _FUNNEL_STAGES)
    return [f"수집 단계 기록: {chain}",
            "*단마다 남은 수 — 목록이 0이면 셀렉터, 키워드만 0이면 원문이 "
            "조용한 것입니다*"]
```

`build_freshness_alert` 바로 위에 넣는다.

```python
def broken_reason_text(r, funnel: dict | None, error: str | None,
                       now: datetime | None = None) -> str:
    """끊긴 사유를 한 줄로 (스펙 2026-10-02 §4.1.3)."""
    f, n = funnel or {}, r.miss_streak or 0
    if r.reason == "list_unchanged":
        at = now or datetime.utcnow()
        hours = (at - r.list_changed_at).total_seconds() / 3600
        return f"목록은 응답하지만 {hours:.0f}시간째 바뀌지 않음 (상한 {r.cap_hours:g}시간)"
    if r.reason == "error":
        return f"목록이 {n}회 연속 응답하지 않음 · 오류: {(error or '')[:120]}"
    if r.reason == "title_ratio":
        links, titled = int(f.get("deduped", 0)), int(f.get("titled", 0))
        return (f"목록에서 기사 링크 {links}개를 찾았지만, 제목까지 확인된 것은 "
                f"{titled}개뿐 ({titled * 100 // max(links, 1)}%) · {n}회 연속")
    if r.reason == "no_links":
        return f"목록에서 기사 링크를 찾지 못함 · {n}회 연속"
    if r.reason == "no_tweets":
        return f"타임라인 트윗 0개 · {n}회 연속"
    if r.reason == "search_failed":
        return f"검색어 {f.get('keywords', 0)}개 모두 실패 · {n}회 연속"
    if r.reason == "no_results":
        return f"검색 결과 글 0개 · {n}회 연속"
    return f"수집 단계 기록 없음 · {n}회 연속 — 소스가 아니라 감시 기록이 고장 났을 수 있음"
```

`build_freshness_alert` 서명에 `broken: bool = False` 를 더하고, 함수 첫 부분 (`breaches = ...` 앞) 에 끊김 분기를 넣는다.

```python
    if broken:
        counts = {s: sum(1 for r in records if r.state == s)
                  for s in ("broken", "no_response", "quiet", "ok")}
        per_source = []
        for b in targets:
            err = (fetch_errors or {}).get(b.source_id)
            funnel = (funnels or {}).get(b.source_id)
            per_source.append((b.source_id, [
                ("왜 끊김인가", [broken_reason_text(b, funnel, err, now=checked_at)]),
                ("수집 단계 기록", _funnel_lines(funnel)),
                ("다음 알림", [f"끊김이 이어지면 {FRESHNESS_REALERT_HOURS:g}시간마다 다시 알립니다"])]))
        if len(per_source) == 1:
            fields = _section_fields(per_source[0][1])
        else:
            fields = [{"name": _source_field_name(sid, sources),
                       "value": _sectioned(sections), "inline": False}
                      for sid, sections in per_source]
        fields.append({"name": "회차", "value": f"run {run_id[:8]}", "inline": True})
        subject = _title_subject([_source_label(b.source_id, sources) for b in targets])
        return {"title": f"🔌 수집 끊김 — {subject}",
                "description": (f"감시 {len(records)}소스: 끊김 {counts['broken']} · "
                                f"응답 없음 {counts['no_response']} · 조용함 {counts['quiet']} · "
                                f"정상 {counts['ok']}"),
                "color": COLOR_ANOMALY, "fields": fields, "url": RUNBOOK_FRESHNESS,
                "timestamp": checked_at.replace(tzinfo=timezone.utc).isoformat(),
                "footer": "bullet-in", "channel": CHANNEL_TREND}
```

`_section_fields` 는 줄이 없는 구획을 뺀다 (`notify.py:176` 의 「줄이 없는 구획은 빠진다」).

같은 함수의 docstring 에 있는 `quality.freshness_alert_split` 을 `quality.broken_alert_split` 으로 바꾼다 (236행).

- [ ] **Step 5: run.py 를 연결한다**

`run.py` import 의 `freshness_alert_split` 을 `evaluate_states, broken_alert_split, responded, LIST_UNCHANGED_CAP_HOURS` 로 바꾸고, `adapter_funnels` 아래에 넣는다.

```python
def source_responses(sources: dict, fetched: "FetchSummary") -> dict[str, tuple[bool, str]]:
    """소스마다 이번 실행에 목록이 응답했는가 (스펙 2026-10-02 §2.2)."""
    return {sid: responded(s.get("adapter"), fetched.funnels.get(sid),
                           bool(fetched.errors.get(sid)))
            for sid, s in sources.items()}
```

신선도 판정 블록 (595 ~ 625행) 의 `records = evaluate_freshness(...)` 부터 로그 줄까지를 바꾼다.

```python
    records = evaluate_freshness({sid: wm.get(sid) for sid in sources},
                                 checked_at, default_hours, overrides)
    for r in records:
        r.stored_fetched_at = stored_wm.get(r.source_id)
    cap = float(cfg.get("list_unchanged_cap_hours", LIST_UNCHANGED_CAP_HOURS))
    sigs = {sid: (fetched.funnels.get(sid) or {}).get("list_sig") for sid in sources}
    evaluate_states(records, source_responses(sources, fetched), sigs, cap,
                    prev_freshness, checked_at)
    mart.record_freshness(run_id, checked_at, records)
    fresh_targets, fresh_holds = broken_alert_split(records, prev_freshness, checked_at)
    if fresh_targets:
        notify.send_alert(**notify.build_freshness_alert(
            records, default_hours, targets=fresh_targets, sources=sources,
            run_id=run_id, checked_at=checked_at, candidates=fetched.candidate_counts,
            fetch_errors=fetched.errors, funnels=fetched.funnels, broken=True))
    # 안 보낸 이유를 남긴다 — 종전에는 대상이 비면 아무 기록 없이 넘어가 "왜 알림이
    # 안 나갔는가" 를 저널로 답할 수 없었다 (스펙 2026-08-14 §5.4).
    by_state = Counter(r.state for r in records)
    logging.getLogger(__name__).info(
        "신선도 판정: 감시 %d소스 · 끊김 %d · 응답 없음 %d · 조용함 %d · 정상 %d · 발송 %d%s%s",
        len(records), by_state["broken"], by_state["no_response"], by_state["quiet"],
        by_state["ok"], len(fresh_targets),
        "".join(f" [{r.source_id} {r.state} {r.reason}]" for r in records
                if r.state in ("no_response", "quiet", "broken")),
        "".join(f" [{h.source_id} 다음 알림까지 {h.hours_to_next:g}h]" for h in fresh_holds))
```

`Counter` 가 이미 import 돼 있는지 확인한다 (324행에서 쓰고 있다).

이제 아무도 부르지 않는 옛 함수를 지운다.
`quality.py` 에서 `freshness_alert_split` 과 `_realert_level` 을 지우고 (`FRESHNESS_REALERT_HOURS` · `FreshnessHold` 는 남긴다), `tests/test_quality.py` 에서 `freshness_alert_split` 을 부르는 테스트와 import 를 지운다.
그 테스트들만 쓰던 도우미 `_stale` (288행) 도 함께 지운다.
지운 테스트 이름은 커밋 본문에 적는다.

- [ ] **Step 6: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_slo5_wiring.py tests/test_notify.py tests/test_run_cliff_alert.py tests/test_run_stages.py tests/test_quality.py -q
grep -rn "freshness_alert_split\|발견 퍼널" src tests
```

Expected: 테스트 PASS · grep 결과 없음.

- [ ] **Step 7: 커밋한다**

```bash
git add src/bullet_in/run.py src/bullet_in/notify.py src/bullet_in/quality.py tests/test_slo5_wiring.py tests/test_notify.py tests/test_run_cliff_alert.py tests/test_quality.py
git commit -m "feat(run): 게시 단계에서 끊김 판정을 연결하고 사유별 끊김 알림 문안 추가"
```

---

## Task 7: 수집 현황 화면

**Files:**
- Modify: `src/bullet_in/serve/ops_view.py` (`_tiles` · `_slo_rows` · `_freshness` · `build_ops_view` 510행)
- Modify: `src/bullet_in/serve/templates/_dash.html.j2` (114행 `.pill` 규칙)
- Test: `tests/test_ops_view.py`

**Interfaces:**
- Consumes: Task 5 의 스냅샷 `freshness` 새 칼럼 · `latest_funnels`
- Produces: `_freshness(fresh_rows, sources, latest_funnels=None) -> tuple[section, int | None]` · 두 번째 값은 끊김 수 (판정된 행이 없으면 None)

- [ ] **Step 1: 테스트 픽스처를 고치고 테스트를 바꾼다**

`tests/test_ops_view.py` 의 `FRESH` 에서 `r3` 행 셋에 새 칼럼을 더한다 (`r1` 행은 옛 행이라 그대로 둔다).

```python
         {"run_id": "r3", "checked_at": T, "source_id": "bbc_sport",
          "last_fetched_at": datetime(2026, 9, 3, 20, 0), "age_hours": 4.0, "threshold_hours": 96.0, "stale": 0,
          "state": "broken", "miss_streak": 2, "list_changed_at": T, "cap_hours": 48.0},
         {"run_id": "r3", "checked_at": T, "source_id": "fmkorea",
          "last_fetched_at": datetime(2026, 9, 2, 18, 0), "age_hours": 30.0, "threshold_hours": 24.0, "stale": 1,
          "state": "quiet", "miss_streak": 0, "list_changed_at": T, "cap_hours": 48.0},
         {"run_id": "r3", "checked_at": T, "source_id": "never",
          "last_fetched_at": None, "age_hours": None, "threshold_hours": 48.0, "stale": 0,
          "state": "no_response", "miss_streak": 1, "list_changed_at": T, "cap_hours": 48.0}]
```

`SNAPSHOT` 에 `"latest_funnels": {"bbc_sport": {"deduped": 7, "titled": 1}, "fmkorea": {"keywords": 3, "searched": 3, "listed": 40}}` 를 더한다.
타일 테스트 82행을 바꾼다.

```python
    assert tiles["Broken Sources"]["value"] == "1"
    assert tiles["Broken Sources"]["sub"] == "끊긴 소스 (SLO-5)"
```

`test_신선도_표는_임계_대비_비율_순이고_미터를_그린다` 를 아래로 바꾼다.

```python
def test_신선도_표는_상태와_수집_단계를_보인다():
    s = _sec(_view(), "sec-source-freshness")
    body = str(s["body"])
    assert body.index(">fmkorea<") < body.index(">BBC Sport<") < body.index(">never<")
    assert '<span class="pill bad">끊김</span>' in body
    assert '<span class="pill warn">조용함</span>' in body
    assert '<span class="pill warn">응답 없음 1회</span>' in body
    assert "기사 링크 7 · 제목 확인 1" in body and "검색어 3/3 · 글 40" in body
    assert "30.0h / 24h" in body
    assert s["insights"][0] == ("임계는 소스마다 다르다 (24h 에서 96h).", [])
    assert ("끊긴 소스는 BBC Sport 다.", []) in s["insights"]


def test_옛_행만_있으면_slo5_는_판정_이전이다():
    old = [dict(r, state=None) for r in FRESH]
    view = build_ops_view(dict(SNAPSHOT, freshness=old), SOURCES, 0, NOW, gate=GATE, unmatched=None)
    slo5 = [r for r in view["slo"] if r["slo_id"] == "SLO-5"][0]
    assert slo5["value"] == "—" and slo5["status"] == "info"
    assert "판정 이전" in str(_sec(view, "sec-source-freshness")["body"])
```

SLO 표 테스트가 SLO-5 의 측정 문구를 비교하면 「목록 응답 · 목록 변화 · 소스별 상태 (source_freshness.state)」 로 바꾼다.

- [ ] **Step 2: 실패를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_ops_view.py -q
```

Expected: FAIL (타일 이름 · 상태 칸 없음).

- [ ] **Step 3: 구현한다**

`_dash.html.j2` 114행 `.pill.bad{...}` 뒤에 `.pill.warn{color:var(--yellow)}` 를 더한다.
`ops_view.py` 에 상수와 도우미를 `_freshness` 위에 넣는다.

```python
_STATE_PILL = {"broken": ("끊김", "bad"), "no_response": ("응답 없음 1회", "warn"),
               "quiet": ("조용함", "warn"), "ok": ("정상", "ok")}


def _stage_text(funnel: dict | None) -> str:
    """수집 단계 칸 — 어댑터마다 응답 판정에 쓰는 숫자 (스펙 2026-10-02 §4.2.1)."""
    f = funnel or {}
    if "scraped" in f:
        return f"트윗 {f.get('scraped', 0)}"
    if "keywords" in f:
        return f"검색어 {f.get('searched', 0)}/{f.get('keywords', 0)} · 글 {f.get('listed', 0)}"
    if "deduped" in f:
        return f"기사 링크 {f.get('deduped', 0)} · 제목 확인 {f.get('titled', 0)}"
    return "—"
```

`_freshness` 를 바꾼다 (표 칸 둘을 더하고, 끊김 수를 센다).

```python
def _freshness(fresh_rows, sources, latest_funnels=None):
    """절과 함께 최신 실행의 끊김 수를 돌려준다 (타일 · SLO-5 가 같은 값을 쓴다)."""
    title, sub = "Source Freshness", "SLO-5 · 목록 응답과 조용함"
    q = ("소스마다 이번 실행의 목록 응답과 상태를 본다. 미터는 새 원본이 임계 시간의 "
         "어디까지 왔는지, 곧 얼마나 조용한가를 보인다.")
    latest_run = fresh_rows[-1]["run_id"] if fresh_rows else None
    latest = {r["source_id"]: r for r in fresh_rows if r["run_id"] == latest_run}
    history = defaultdict(list)
    for r in fresh_rows:
        if r["age_hours"] is not None:
            history[r["source_id"]].append(float(r["age_hours"]))
    funnels = latest_funnels or {}

    def ratio(r):
        return (r["age_hours"] or 0) / (r["threshold_hours"] or 1)

    def state_cell(r):
        label, cls = _STATE_PILL.get(r.get("state"), ("판정 이전", ""))
        pill = f'<span class="pill {cls}">{label}</span>' if cls else f'<span class="pill">{label}</span>'
        changed, cap = r.get("list_changed_at"), r.get("cap_hours")
        if changed is not None and cap:
            hours = (r["checked_at"] - changed).total_seconds() / 3600
            if hours > cap / 2:
                pill += f' <span class="q">목록 그대로 {hours:.0f}시간</span>'
        return pill

    rows = []
    for sid, r in sorted(latest.items(), key=lambda kv: -ratio(kv[1])):
        disp = C.E(_display(sources, sid))
        stage = C.E(_stage_text(funnels.get(sid)))
        if r["age_hours"] is None:
            rows.append(f'<tr><td>{disp}</td><td>이력 없음</td><td>— / {r["threshold_hours"]:.0f}h</td>'
                        f'<td></td><td></td><td>{stage}</td><td>{state_cell(r)}</td></tr>')
            continue
        rows.append(f'<tr><td>{disp}</td><td>{r["last_fetched_at"]:%m-%d %H:%M}</td>'
                    f'<td>{r["age_hours"]:.1f}h / {r["threshold_hours"]:.0f}h</td>'
                    f'<td>{C.meter(r["age_hours"], r["threshold_hours"])}</td>'
                    f'<td>{C.sparkline(history[sid], w=84, h=18)}</td>'
                    f'<td>{stage}</td><td>{state_cell(r)}</td></tr>')
    body = (('<table class="fresh"><thead><tr><th>소스</th><th>마지막 수집</th><th>경과 / 임계</th>'
             '<th>조용함</th><th>최근 12회</th><th>수집 단계</th><th>상태</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table>") if rows else '<p class="q">이력 없음.</p>')
    ins = []
    thr = [r["threshold_hours"] for r in latest.values()]
    if thr and min(thr) != max(thr):
        ins.append((f"임계는 소스마다 다르다 ({min(thr):.0f}h 에서 {max(thr):.0f}h).", []))
    broken = [_display(sources, s) for s, r in latest.items() if r.get("state") == "broken"]
    if broken:
        ins.append((f"끊긴 소스는 {' · '.join(broken)} 다.", []))
    quiet = [_display(sources, s) for s, r in latest.items() if r.get("state") == "quiet"]
    if quiet:
        ins.append((f"새 원본이 임계보다 오래 없는 조용한 소스는 {' · '.join(quiet)} 다.", []))
    judged = [r for r in latest.values() if r.get("state") is not None]
    broken_count = sum(1 for r in judged if r["state"] == "broken") if judged else None
    return _section("sec-source-freshness", title, sub, q, body, ins), broken_count
```

`build_ops_view` 510행을 바꾼다.

```python
    fresh_sec, stale_count = _freshness(snapshot.get("freshness") or [], sources,
                                        snapshot.get("latest_funnels"))
```

`_tiles` 의 Stale 타일을 바꾼다.

```python
        {"label": "Broken Sources", "value": "—" if stale_count is None else C.fmt(stale_count),
         "sub": "끊긴 소스 (SLO-5)", "spark": ""},
```

`_slo_rows` 의 SLO-5 측정 문구를 `"목록 응답 · 목록 변화 · 소스별 상태 (source_freshness.state)"` 로 바꾼다.
변수 이름 `stale_count` 는 이 PR 에서 바꾸지 않는다 (호출부가 여럿이라 바뀐 줄을 줄인다).

- [ ] **Step 4: 통과를 확인한다**

```bash
uv run --project . --extra dev pytest tests/test_ops_view.py tests/test_charts.py -q
```

Expected: 전부 PASS.

- [ ] **Step 5: 화면을 한 번 렌더해 눈으로 본다**

```bash
uv run --project . --extra dev python - <<'EOF'
from datetime import datetime
from pathlib import Path
import tests.test_ops_view as t
from bullet_in.serve.ops_view import build_ops_view
view = build_ops_view(t.SNAPSHOT, t.SOURCES, 0, t.NOW, gate=t.GATE, unmatched=t.UNMATCHED)
sec = [s for s in t._flat(view) if s["id"] == "sec-source-freshness"][0]
Path("/tmp/fresh_section.html").write_text(str(sec["body"]))
print("ok")
EOF
```

`/tmp/fresh_section.html` 을 열어 표가 일곱 칸으로 깨지지 않는지 본다.

- [ ] **Step 6: 커밋한다**

```bash
git add src/bullet_in/serve tests/test_ops_view.py
git commit -m "feat(serve): 수집 현황 신선도 절에 상태와 수집 단계 칸 · SLO-5 를 끊김 수로"
```

---

## Task 8: dbt Gold SLO-5

**Files:**
- Modify: `dbt/models/staging/stg_source_freshness.sql`
- Modify: `dbt/models/gold/gold_slo_rollup.sql` (16 ~ 19행)
- Modify: `dbt/models/sources.yml` (`stg_article_players` 항목 뒤)
- Test: `tests/test_dbt_gate.py` 의 기존 테스트 · `dbt parse`

**Interfaces:**
- Consumes: Task 5 의 `state` 칼럼

- [ ] **Step 1: 모델을 고친다**

`stg_source_freshness.sql`

```sql
select run_id, checked_at, source_id, age_hours, stale, state
from {{ source('maria', 'source_freshness') }}
```

`gold_slo_rollup.sql` 의 SLO-5 부분

```sql
select 'SLO-5',
       '수집 끊긴 소스 수 (최신 run)',
       coalesce(sum(case when state = 'broken' then 1 else 0 end), 0)
from latest_fresh
```

- [ ] **Step 2: 허용 값 테스트를 더한다**

`sources.yml` 의 `models:` 목록 맨 끝 (마지막 gold 모델 항목 뒤 · 파일 끝) 에 붙인다.

```yaml
  - name: stg_source_freshness
    columns:
      - name: state
        tests:
          - accepted_values:
              arguments:
                values: ['ok', 'quiet', 'no_response', 'broken']
              config:
                # 2026-10-02 배포 전 행은 state 가 비어 있다 — 판정된 행만 본다 (스펙 §4.3).
                where: "state is not null"
```

- [ ] **Step 3: 파싱과 테스트 수를 확인한다**

```bash
cd dbt && uv run --project .. dbt parse --profiles-dir . && uv run --project .. dbt ls --resource-type test --profiles-dir . | wc -l && cd ..
uv run --project . --extra dev pytest tests/test_dbt_gate.py -q
```

Expected: 파싱 성공 · 테스트 22 · pytest PASS.

- [ ] **Step 4: 커밋한다**

```bash
git add dbt/models
git commit -m "feat(dbt): Gold SLO-5 를 끊김 상태 수로 바꾸고 state 허용 값 테스트 추가"
```

---

## Task 9: 런북

**Files:**
- Modify: `docs/runbook/2026-08-20-freshness-threshold-recalibration.md` (끝에 절 추가)

- [ ] **Step 1: 절을 더한다**

파일 끝에 붙인다 (지금 마지막 절이 `## 7.` 이므로 `## 8.` 로 단다).

```markdown
## 8. 상한과 제목 확인 비율 (2026-10-02 추가)

### 8.1. 무엇이 바뀌었나

SLO-5 는 이제 「끊긴 소스」 만 센다 (스펙 `docs/superpowers/specs/2026-10-02-slo5-broken-source-signal-design.md`).

`freshness_hours` 는 끊김 판정에서 빠지고, 수집 현황 화면에서 「조용함」 을 표시하는 기준선이 됐다.
이 런북의 재측정 절차는 조용함 표시선을 고를 때 그대로 쓴다.

### 8.2. 끊김을 정하는 값

| 값 | 위치 | 뜻 |
| --- | --- | --- |
| 무응답 2회 연속 | 코드 (`quality.evaluate_states`) | 목록이 응답하지 않으면 끊김 |
| 제목 확인 비율 절반 | 코드 (`quality.responded`) | HTML 목록에서 제목까지 확인된 링크가 절반보다 적으면 무응답 |
| `list_unchanged_cap_hours: 48` | `config/sources.yaml` | 목록이 48시간 넘게 그대로면 끊김 |

### 8.3. 상한을 다시 볼 때

배포 뒤 「신선도 판정」 로그에서 소스마다 목록이 바뀐 간격을 모은다.
어느 소스든 정상일 때 목록이 48시간 넘게 그대로인 일이 있으면, 그 근거를 적고 상한을 올린다.
상한을 소스마다 다르게 두는 것은 그런 근거가 생긴 뒤에 정한다.
```

- [ ] **Step 2: 서식을 검사하고 커밋한다**

```bash
python3 .claude/hooks/check-doc-format.py docs/runbook/2026-08-20-freshness-threshold-recalibration.md
git add docs/runbook/2026-08-20-freshness-threshold-recalibration.md
git commit -m "docs(runbook): 신선도 임계 런북에 끊김 상한과 제목 확인 비율 절 추가"
```

Expected: 위반 없음.
파일 전체에 옛 위반이 있으면 CI 가 파일 전체를 보므로 그 위반도 이 커밋에서 고친다.

---

## Task 10: 전체 검증과 과거 이력 대입

**Files:** 저장소 밖 스크립트 (세션 스크래치패드)

- [ ] **Step 1: 전체 테스트를 돌린다**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/slo5-broken-signal
uv run --project . --extra dev pytest -q 2>&1 | tail -3
```

Expected: 수집 1,825 (기준선 1,792 + 33 · 2026-10-02 dry run 실측) · 1 skip (기준선과 같음) · 나머지 전부 PASS.

- [ ] **Step 2: 과거 이력 대입 스크립트를 만든다**

운영 DB 를 읽기만 한다.
세션이 운영 조회를 할 수 없으면 사용자가 `! bash /tmp/slo5_replay.sh` 로 실행한다 (짧은 경로에 둔다).
VM 에서 돌리므로 저장소 코드가 아니라 같은 규칙을 스크립트 안에 옮겨 쓴다.

```python
# /tmp/slo5_replay.py — VM 에서 실행 · 09-02 ~ 09-30 무응답 규칙 대입 (스펙 §5.2)
import json, os
from collections import defaultdict
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
ADAPTER = {"bbc_sport": "html", "bbc_gossip": "html", "guardian": "html", "skysports": "html",
           "x_afcstuff": "x", "x_ornstein": "x", "fmkorea": "fmkorea"}
with eng.connect() as c:
    rows = c.execute(text(
        "SELECT run_id, started_at, fetch_detail FROM pipeline_runs "
        "WHERE started_at >= '2026-09-02' AND started_at < '2026-10-01' "
        "AND finished_at IS NOT NULL ORDER BY started_at")).all()
streak, broken, first_bad = defaultdict(int), defaultdict(int), {}
for rid, at, d in rows:
    d = json.loads(d) if isinstance(d, (str, bytes)) else (d or {})
    errs, fun = d.get("errors") or {}, d.get("funnels") or {}
    for sid, kind in ADAPTER.items():
        f = fun.get(sid) or {}
        if sid in errs:
            ok = False
        elif kind == "html":
            ok = bool(f) and f.get("deduped", 0) > 0 and f.get("titled", 0) * 2 >= f.get("deduped", 0)
        else:
            ok = True            # 과거 기록에 X · fmkorea 수집 단계 기록이 없다 — 오류만 본다
        streak[sid] = 0 if ok else streak[sid] + 1
        if streak[sid] >= 2:
            broken[sid] += 1
            first_bad.setdefault(sid, (str(at), f))
print("실행", len(rows))
for sid in ADAPTER:
    print(sid, "끊김 실행", broken[sid], "처음", first_bad.get(sid))
```

```bash
# /tmp/slo5_replay.sh
scp -i ~/.ssh/seoulnow_deploy /tmp/slo5_replay.py ubuntu@155.248.164.17:/tmp/
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "cd ~/bullet-in && set -a && . ./.env && set +a && .venv/bin/python /tmp/slo5_replay.py; rm -f /tmp/slo5_replay.py"
```

- [ ] **Step 3: 결과를 기록한다**

결과 (소스별 끊김 실행 수 · BBC Sport 가 처음 끊김이 된 시각과 그때의 수집 단계 기록) 를 PR 본문 §4 에 싣는다.
기대와 다르면 (예: Guardian 이 끊김) 구현 전에 사용자에게 알리고 멈춘다.

- [ ] **Step 4: 문서만이 아닌 PR 이므로 push 와 PR 생성까지 한다**

```bash
git push origin worktree-slo5-broken-signal
```

PR 본문은 `.github/pull_request_template.md` 의 7섹션으로 쓰고, humanize-korean fast 1회 → `.claude/tools/check-pr-format.py --body <파일> --title "<제목>"` 순서로 검사한다.
Claude 서명 줄은 넣지 않는다.
머지는 사용자가 한다.

---

## 배포 뒤 확인 (머지 뒤 · 이 계획의 범위 밖 메모)

스펙 §5.3 의 순서를 따른다.

- 첫 실행 — 새 칼럼 다섯 · 로그의 상태별 개수 · `ops.html` 상태 칸
- 둘째 실행 — `miss_streak` · `list_changed_at` 이어 적기 · BBC Sport 끊김 알림
- 첫 일주일 — 소스별 목록 변화 간격 (특히 X 두 계정)
- 다음 레이크하우스 적재 — `ops_source_freshness` 칼럼 다섯
- 게이트 dbt 테스트 22종 통과 · judge 「반영 완료」
