# 대시보드 개편 PR 2 — 수집 현황 화면 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집 현황 화면 (`ops.html`) 을 목업 v2.8 대로 다시 만든다.
`Mart.ops_snapshot` 을 넓히고, 뷰모델을 새 모듈에 쓰고, 템플릿이 PR 1 의 공통 조각을 상속하게 하고, SLO-3 · 4 를 게이트 결과 파일에서 읽고, README §4 에 SLO 번호 여섯을 적는다.

**Architecture:** 회차의 `publish` 태스크가 `Mart.ops_snapshot()` 한 번으로 MariaDB 를 읽고 `dbt/target/run_results.json` 을 `dbt_gate.gate_tally` 로 읽어 `serve/ops_view.build_ops_view` 에 넘긴다.
뷰모델이 PR 1 의 `serve/charts.py` 로 SVG 를 그리고 `ops.html.j2` 가 `_dash.html.j2` 를 상속해 절 열을 그린다.
새 표 · 새 파일 · 새 태스크는 없다.
읽기만 늘고 스키마는 안 바뀌므로 첫 회차의 빈 구간이 없다 (스펙 §4).

**Tech Stack:** Python 3.11 · SQLAlchemy (MariaDB) · Jinja2 · markupsafe · pytest.

**Spec:** `docs/superpowers/specs/2026-09-05-dashboard-redesign-design.md` (§3.4 수집 현황 · §3.5 README §4 · §4 빈 구간 · §5 검증) · 목업 v2.8 의 수집 현황 탭 (스펙 §1 의 주소) · 런북 `docs/runbook/2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md` §8.

## Global Constraints

- 정본은 목업 v2.8 이다. 목업과 스펙이 갈리면 목업을 따르고, 목업이 정하지 않은 것만 스펙을 따른다 (스펙 §1).
- 색은 SVG 속성에 적지 않고 CSS 클래스 (`s1` 에서 `s5` · `o1` 에서 `o6` · `dimbar` · `dimseg`) 로만 건다 (스펙 §3.2). 클래스는 PR 1 의 `_dash.html.j2` 에 이미 있다.
- 화면의 시각은 전부 UTC 다. 저장값이 UTC 이고 목업의 「시각」 항목이 「UTC · KST 는 +9시간」 이다.
- `ops.html.j2` 는 `_dash.html.j2` 를 상속하고 `{% block page %}ops{% endblock %}` 를 반드시 정의한다. 탭의 현재 표시가 이 블록으로 갈린다.
- 인사이트 (`.ins`) 는 값에서 만들 수 있는 문장만 싣는다. 「손으로 돌리던 때다」 같은 해석 문장은 목업에 있어도 안 옮긴다 (스펙 §3.3 · PR 1 정정 표).
- `docs/` 문서는 서식 훅 (`.claude/hooks/check-doc-format.py`) 을 통과해야 한다. README 는 훅 대상이 아니다.
- 테스트 이름은 기존 파일의 관례대로 한국어 함수명이다. 통합 테스트 (`tests/integration/`) 와 `tests/test_dbt_gate.py` 는 그 파일의 영어 관례를 따른다.
- 파이썬 환경 · 워크트리 · 브랜치 규율은 메모리 `standing-session-rules` §1 에서 §3 그대로다. `uv run --project <워크트리> --extra dev pytest`.
- 커밋 메시지는 `docs/conventions/2026-06-11-commit-pr-convention.md` 를 따른다. type 은 `feat` · `test` · `docs` · `refactor`, scope 는 `dashboard` · `serve` · `storage` · `gate`. 트레일러는 PR 1 과 같다 (`Co-Authored-By: Claude Fable 5.1 (설계)` · `Co-Authored-By: Claude Sonnet 5 (구현)` · `Claude-Session:`).
- 테스트 기준선은 1,754 (2026-09-05 09:03 KST · 워크트리 `dashboard-pr2` 에서 `uv run --project . --extra dev pytest -q --co`).

## 판정 (스펙 · 목업 · 실물이 갈린 자리)

계획서를 쓰면서 실물과 대조해 정한 것이다.
사용자 확인이 필요한 것은 앞에 ★ 를 붙였다.

| # | 자리 | 판정 | 근거 |
| --- | --- | --- | --- |
| 1 | 뷰모델의 위치 | 새 모듈 `serve/ops_view.py` 에 `build_ops_view` 를 옮겨 쓴다. 이름은 그대로다. | 스펙 §3.4 는 「`build_ops_view` 안에」 라고 했지만 §3.3 이 같은 이유 (`render.py` 2,200줄) 로 행동 화면을 새 모듈에 두었다. `render.py` 의 옛 뷰 코드 (`TIER_BUCKETS` · `spark_points` · `_kpi` · 옛 `build_ops_view`) 는 지운다. |
| 2 | SLO-3 · 4 의 「N종 통과」 | `dbt_gate.gate_tally(path)` 를 새로 둔다. `parse_results` 는 그대로 두고 판정에는 안 쓴다. | 스펙 §3.4 는 「`parse_results` 를 그대로」 라고 했지만 그 결과 (`GateResult`) 에는 통과한 테스트가 없다. 목업이 「unique 테스트 5종 통과 · 게이트 09-04 09:02 UTC」 를 적으므로 총수와 게이트 시각이 필요하다. |
| 3 | SLO-3 · 4 의 비율 | 중복 적재율 = unique 실패 행 합 ÷ 기사 총수. 완전성 = 1 − (not_null 실패 행 최댓값 ÷ 기사 총수). 기사 총수는 `ops_snapshot` 의 `articles_total`. | not_null 열 종 가운데 기사 표가 아닌 것은 셋 (`stg_players.id` · gold 둘) 이고 운영 실측 결측 0 이라 분모를 기사 총수로 둬도 지금은 같다. 경고 (`warn`) 도 「전부 통과」 가 아니므로 실패로 센다. |
| 4 | 신선도 이력 | 기존 12회 창을 그대로 쓴다. 스펙의 「신선도 이력 3일」 은 안 가져온다. | 목업의 Source Freshness 표가 「최근 12회」 스파크라인이고 3일치를 쓰는 절이 없다. 목업이 정본이다. |
| 5 | ★ 성공률의 미터 | Success Rate 타일과 SLO-2 행에 미터를 안 그린다. | 목업은 미터를 그렸지만 `charts.meter` 의 색 규칙이 「찰수록 나쁨」 (신선도용) 이라 99.2% 가 노랑으로 나온다. 목업의 그 색이 실제로 노랑이다. 값과 목표만 적는다. |
| 6 | 옛 절 ③ ④ | 「소스별 수집량 · 번역 · 분류 대기」 와 「Tier 분포」 는 사라진다. `ops_snapshot` 의 `pending` · `tier_counts` 쿼리도 뺀다. | 목업에 없다. 등급 분포는 Credibility Mix 가 주별로 대신한다. |
| 7 | 재작성 잔존율 · 선수 추출 누락 표 | 열째 절 `sec-review-tables` 로 남긴다. | 목업 Coverage by Player 의 인사이트가 「지금대로 아래에 둔다」 고 했다. 그래서 배포 뒤 `class="sec"` 수는 열 (스펙 §5 의 「열여덟」 은 두 화면 합쳐 열아홉이 된다). |
| 8 | ※ 표시 | 안 붙인다. | 스펙 §3.5 「README 표가 머지되면 뗀다」 인데 README 가 같은 PR 이다. |
| 9 | 소스 이름 | `config/sources.yaml` 의 `display_name` 그대로 쓴다. | 목업은 「afcstuff (X)」 로 적었지만 설정은 「afcstuff (aggregator)」 다. 화면이 설정을 고쳐 쓰지 않는다. |
| 10 | SLO-6 의 측정 문구 | 「직전 회차들 대비 ±2σ 드롭 · 스파이크 (`quality.volume_anomalies`)」 | 목업은 「지난 12회 대비」 라고 적었는데 창은 `run.py` 가 넘기는 이력 길이라 문구에 수를 박지 않는다. |
| 11 | 회차 전체의 시작 | `OPS_EPOCH = 2026-06-12` 이고 `started_at >= '2026-06-12'` (UTC). | 런북 §8 셋째 SQL 그대로다. 실측 첫 행은 06-11 21:10 UTC (06-12 06:10 KST) 라 한 행이 빠지는데 목업도 같은 조건이었다. |
| 12 | 회차 SLO 창 | 최근 30회 = `runs_all[-30:]`. 옛 `runs` (최신순 30) 키와 쿼리는 없앤다. | 같은 표를 두 번 읽을 이유가 없다. 통합 테스트는 `runs_all` 로 고친다. |

## 파일 구조

| 파일 | 책임 | 태스크 |
| --- | --- | --- |
| `src/bullet_in/dbt_gate.py` | `GateTally` · `gate_tally(path)` | 1 |
| `tests/test_dbt_gate.py` | 집계 테스트 셋 (기존 파일 끝에 덧붙인다) | 1 |
| `src/bullet_in/storage/mariadb.py` | `ops_snapshot` 확장 (회차 전체 · 지연 · 주별 구성 · 선수 주체 · 기사 총수) | 2 |
| `tests/integration/test_ops_snapshot.py` | 재작성 | 2 |
| `src/bullet_in/serve/ops_view.py` (신설) | 스냅샷 · 게이트 집계를 절 열의 뷰모델로 | 3 |
| `tests/test_ops_view.py` | 재작성 | 3 |
| `src/bullet_in/serve/templates/ops.html.j2` | 재작성 · `_dash.html.j2` 상속 | 4 |
| `src/bullet_in/serve/render.py` | 옛 뷰 코드 삭제 · `render_ops` · `write_ops` (`gate_path`) | 4 |
| `src/bullet_in/run.py` | `publish` 가 `gate_path` 를 넘김 | 4 |
| `tests/test_serve_ops.py` | 재작성 | 4 |
| `README.md` | §4 표에 번호 여섯과 SLO-5 행 | 5 |

---

### Task 0: 워크트리 확인과 기준선

**Files:**
- 없음 (환경만)

- [ ] **Step 1: 워크트리 확인**

워크트리 `.claude/worktrees/dashboard-pr2` (브랜치 `dashboard-pr2`) 는 2026-09-05 09:02 에 `origin/main` (`835b08a`) 에서 손으로 팠고 `.env` 도 복사했다.
없으면 저장소 루트에서 만든다.

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in
git fetch origin
git worktree list | grep dashboard-pr2 || git worktree add -b dashboard-pr2 .claude/worktrees/dashboard-pr2 origin/main
cp .env .claude/worktrees/dashboard-pr2/.env
```

- [ ] **Step 2: 파이썬 환경**

이미 만들었다 (3.11 · `--extra dev`).
없으면 만든다.

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard-pr2
uv venv --python 3.11 --project .
uv sync --project . --extra dev
```

- [ ] **Step 3: 기준선 수집 수와 통합 테스트 접속**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard-pr2
uv run --project . --extra dev pytest -q --co 2>/dev/null | tail -1
docker ps --format '{{.Names}} {{.Status}}' | grep mariadb
```

Expected: `1754 tests collected` · `bullet-in-mariadb-1 Up …`.
수집 수가 다르면 셸이 워크트리 밖에 서 있는 것이다 (규율 §3).
컨테이너가 없으면 `docker compose up -d` 를 먼저 한다. 없으면 통합 테스트가 조용히 skip 된다.

---

### Task 1: `dbt_gate.gate_tally` — unique · not_null 테스트 집계

**Files:**
- Modify: `src/bullet_in/dbt_gate.py:31-62` (`GateResult` 아래에 `GateTally` · `parse_results` 아래에 `gate_tally`)
- Test: `tests/test_dbt_gate.py` (끝에 덧붙인다)

**Interfaces:**
- Consumes: `dbt/target/run_results.json` 의 `results[].unique_id` · `status` · `failures` · `metadata.generated_at`. 이름은 기존 `_short` 로 뽑는다 (`test.bullet_in.unique_stg_articles_url.abc` → `unique_stg_articles_url`).
- Produces: `GateTally(generated_at: str, unique_total: int, unique_failed: list[TestOutcome], not_null_total: int, not_null_failed: list[TestOutcome])` · `gate_tally(path: Path) -> GateTally | None`. 태스크 3 이 `GateTally` 를 받고 태스크 4 의 `write_ops` 가 `gate_tally` 를 부른다.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_dbt_gate.py` 끝에 덧붙인다.
파일 머리의 import 줄에 `GateTally` · `gate_tally` 를 더한다.

```python
def test_gate_tally_counts_unique_and_not_null_and_keeps_failures(tmp_path):
    path = tmp_path / "run_results.json"
    path.write_text(json.dumps({
        "metadata": {"generated_at": "2026-09-05T00:03:04.645664Z"},
        "results": [
            {"unique_id": "test.bullet_in.unique_stg_articles_url.a", "status": "pass", "failures": 0},
            {"unique_id": "test.bullet_in.unique_stg_articles_content_hash.b", "status": "fail", "failures": 3},
            {"unique_id": "test.bullet_in.not_null_stg_articles_url.c", "status": "pass", "failures": 0},
            {"unique_id": "test.bullet_in.not_null_stg_articles_transfer_stage.d", "status": "warn", "failures": 2},
            {"unique_id": "test.bullet_in.not_null_stg_players_id.e", "status": "pass", "failures": 0},
        ]}))
    t = gate_tally(path)
    assert t.generated_at == "2026-09-05T00:03:04.645664Z"
    assert t.unique_total == 2 and [x.name for x in t.unique_failed] == ["unique_stg_articles_content_hash"]
    assert t.unique_failed[0].failures == 3
    # warn 도 「전부 통과」 가 아니다 — 결측 행이 있다는 뜻이라 실패로 센다
    assert t.not_null_total == 3 and [x.name for x in t.not_null_failed] == ["not_null_stg_articles_transfer_stage"]


def test_gate_tally_returns_none_without_file(tmp_path):
    assert gate_tally(tmp_path / "missing.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert gate_tally(tmp_path / "bad.json") is None


def test_gate_tally_ignores_other_tests_and_models(tmp_path):
    path = _write(tmp_path, [
        {"unique_id": "test.bullet_in.accepted_values_stg_articles_tier__0__1.x", "status": "pass", "failures": 0, "message": ""},
        {"unique_id": "test.bullet_in.relationships_stg_article_players_player_id.y", "status": "pass", "failures": 0, "message": ""},
        {"unique_id": "model.bullet_in.stg_articles", "status": "success", "failures": None, "message": ""},
    ])
    t = gate_tally(path)
    assert t.unique_total == 0 and t.not_null_total == 0
    assert t.generated_at == ""
```

`_write` 는 그 파일에 이미 있는 헬퍼다 (`metadata` 없이 `results` 만 쓴다).

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_dbt_gate.py -q -k gate_tally`
Expected: FAIL · `ImportError: cannot import name 'gate_tally'`

- [ ] **Step 3: 구현**

`src/bullet_in/dbt_gate.py` 의 `GateResult` 정의 바로 아래에 더한다.

```python
@dataclass(frozen=True)
class GateTally:
    """수집 현황 화면의 SLO-3 · 4 재료 — unique · not_null 테스트가 몇 종이고 무엇이 안 통과했나."""
    generated_at: str                       # dbt 가 적은 ISO 시각 (UTC · 없으면 빈 문자열)
    unique_total: int
    unique_failed: list[TestOutcome]
    not_null_total: int
    not_null_failed: list[TestOutcome]
```

`parse_results` 바로 아래에 더한다.

```python
def gate_tally(path: Path) -> GateTally | None:
    """SLO-3 (중복 적재율) · SLO-4 (필수 필드 완전성) 용 집계.

    `parse_results` 는 차단 · 경고만 남기고 통과를 버린다 — 「unique 5종 전부 통과」 라고
    말하려면 통과한 것도 세야 해서 같은 파일을 따로 읽는다. 경고 (`warn`) 도 결측 행이
    있다는 뜻이라 실패로 센다. 파일이 없거나 못 읽으면 None 이고 화면은 「게이트 결과 없음」
    으로 그린다 (스펙 2026-09-05 §3.4).
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    total = {"unique": 0, "not_null": 0}
    failed: dict[str, list[TestOutcome]] = {"unique": [], "not_null": []}
    for r in data.get("results", []):
        name = _short(r.get("unique_id", ""))
        kind = next((k for k in total if name.startswith(k + "_")), None)
        if kind is None:
            continue
        total[kind] += 1
        if r.get("status") in _BLOCKING or r.get("status") == "warn":
            failed[kind].append(TestOutcome(name, int(r.get("failures") or 0)))
    return GateTally(generated_at=(data.get("metadata") or {}).get("generated_at", ""),
                     unique_total=total["unique"], unique_failed=failed["unique"],
                     not_null_total=total["not_null"], not_null_failed=failed["not_null"])
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_dbt_gate.py -q`
Expected: 기존 21 + 3 = 24 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/dbt_gate.py tests/test_dbt_gate.py
git commit -m "feat(gate): unique · not_null 테스트 집계를 게이트 결과 파일에서 읽는다 (안건 2φ · PR 2)" -m "수집 현황 화면의 SLO-3 · 4 가 「N종 통과 · 게이트 시각」 을 적으려면 통과한 테스트도 세야 하는데 parse_results 는 차단 · 경고만 남긴다. 같은 파일을 읽는 집계 함수를 따로 둔다.

- GateTally 데이터클래스 (게이트 시각 · unique · not_null 의 총수와 실패 목록)
- gate_tally(path) · 파일이 없으면 None · warn 도 실패로 집계
- 테스트 셋 (집계 · 파일 없음 · 다른 테스트 종류 무시)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 1 · 스펙 §3.4
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

---

### Task 2: `Mart.ops_snapshot` 확장

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py:241-282` (`ops_snapshot` 전문 교체 · 파일 머리에 상수 셋)
- Test: `tests/integration/test_ops_snapshot.py` (전문 교체)

**Interfaces:**
- Consumes: `pipeline_runs` · `source_freshness` · `articles` · `article_players` · `players` (스키마 `src/bullet_in/storage/schema.sql`).
- Produces: `ops_snapshot(self, trend_runs: int = 12) -> dict` 의 키 일곱.
  - `runs_all`: 2026-06-12 이후 마감된 회차 전부 · `started_at` 오름차순 · 각 행 `run_id` · `started_at` · `duration_sec` · `fetch_duration_sec` (NULL 가능) · `source_counts` (dict) · `new_count` · `dup_count` · `error_count` · `success_rate`.
  - `freshness`: 그대로 (최근 12회 · `checked_at` 오름차순).
  - `latency`: `(source_id, lag_hours)` 튜플 목록 · 런북 §8 첫째 SQL 그대로.
  - `weekly_mix`: `{yw, tier, stage, n, n_byline}` 목록 · `yw` 는 `YEARWEEK(fetched_at, 3)` 정수 · 07-13 이후.
  - `player_subjects`: `{player_id, ko_name, category, n}` 목록 · `role = 'subject'` 이고 `category IN ('squad', 'external')`.
  - `articles_total`: 정수.
  - `high_retention`: 그대로.
- 없어지는 키: `runs` · `tier_counts` · `pending` (판정 6 · 12).

- [ ] **Step 1: 실패하는 테스트**

`tests/integration/test_ops_snapshot.py` 를 아래로 통째로 바꾼다.
`_seed_runs` · `_seed_freshness` · `_art` 는 그대로다.

```python
import json
from datetime import datetime, timedelta
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.storage.mariadb import MartStore


def _seed_runs(engine, n, base=datetime(2026, 7, 1, 0, 0)):
    rows = [{"rid": f"run-{i:03d}", "t": base + timedelta(hours=6 * i),
             "dur": 60.0 + i,
             "fetch": None if i % 2 == 0 else 4.0 + i,   # NULL 혼재 이력
             # i % 2 회차만 bbc_sport 키 존재 → 희소 표현 (부재 = 0 계약은 뷰모델이 검증)
             "counts": json.dumps({"bbc_sport": 3} if i % 2 else {}),
             "new": i % 3, "dup": 2, "err": 1 if i == n - 1 else 0, "sr": 0.9}
            for i in range(n)]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:fetch,:counts,:new,:dup,:err,:sr)"), rows)


def _seed_freshness(engine, n_runs, base=datetime(2026, 7, 1, 0, 0)):
    rows = []
    for i in range(n_runs):
        at = base + timedelta(hours=6 * i)
        rows.append({"rid": f"run-{i:03d}", "at": at, "sid": "bbc_sport",
                     "wm": at, "age": float(i), "thr": 48.0, "stale": 0})
        # never_source 는 워터마크 없음 → age NULL · stale=0 (판정 계층 계약)
        rows.append({"rid": f"run-{i:03d}", "at": at, "sid": "never_source",
                     "wm": None, "age": None, "thr": 48.0, "stale": 0})
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO source_freshness (run_id,checked_at,source_id,"
            "last_fetched_at,age_hours,threshold_hours,stale) "
            "VALUES (:rid,:at,:sid,:wm,:age,:thr,:stale)"), rows)


def _art(h, url, **kw):
    base = dict(content_hash=h, url=url, source_id="bbc_sport",
                title_original="T", published_at=datetime(2026, 7, 10),
                fetched_at=datetime(2026, 7, 10), tier=2)
    base.update(kw)
    return Article(**base)


def _seed_players(engine):
    """squad · external · manager 하나씩과 주체 · 언급 귀속."""
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO players (id,full_name,surname,ko_name,category,status,transfer_status,origin,added_at) "
            "VALUES (:id,:full,:sur,:ko,:cat,'active','none','seed',:at)"),
            [{"id": 1, "full": "Bruno Guimaraes", "sur": "Guimaraes", "ko": "기마랑이스", "cat": "squad", "at": datetime(2026, 7, 1)},
             {"id": 2, "full": "Julian Alvarez", "sur": "Alvarez", "ko": None, "cat": "external", "at": datetime(2026, 7, 1)},
             {"id": 3, "full": "Mikel Arteta", "sur": "Arteta", "ko": "아르테타", "cat": "manager", "at": datetime(2026, 7, 1)}])
        c.execute(text(
            "INSERT INTO article_players (content_hash,player_id,stage,extracted_at,role) "
            "VALUES (:h,:pid,'rumour',:at,:role)"),
            [{"h": "h1", "pid": 1, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h2", "pid": 1, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h3", "pid": 1, "at": datetime(2026, 7, 10), "role": "mention"},
             {"h": "h1", "pid": 2, "at": datetime(2026, 7, 10), "role": "subject"},
             {"h": "h1", "pid": 3, "at": datetime(2026, 7, 10), "role": "subject"}])


def test_ops_snapshot_returns_all_finished_runs_since_epoch_ascending(engine):
    _seed_runs(engine, 35)
    snap = MartStore(engine).ops_snapshot()
    assert len(snap["runs_all"]) == 35                     # 30 으로 안 자른다 (회차 전체)
    assert snap["runs_all"][0]["run_id"] == "run-000"      # 과거 → 최신
    assert snap["runs_all"][-1]["run_id"] == "run-034"
    assert isinstance(snap["runs_all"][1]["source_counts"], dict)
    assert snap["runs_all"][1]["source_counts"] == {"bbc_sport": 3}   # run-001 (홀수)


def test_ops_snapshot_drops_runs_before_first_live_run(engine):
    # 6시간 간격 셋: run-000 06-11 12:00 · run-001 06-11 18:00 · run-002 06-12 00:00 (경계 포함)
    _seed_runs(engine, 3, base=datetime(2026, 6, 11, 12, 0))
    snap = MartStore(engine).ops_snapshot()
    assert [r["run_id"] for r in snap["runs_all"]] == ["run-002"]


def test_ops_snapshot_freshness_window_and_null_age(engine):
    _seed_freshness(engine, 14)
    snap = MartStore(engine).ops_snapshot()
    run_ids = {r["run_id"] for r in snap["freshness"]}
    assert len(run_ids) == 12                             # 최근 12회 창
    assert "run-000" not in run_ids and "run-001" not in run_ids
    assert snap["freshness"][0]["checked_at"] <= snap["freshness"][-1]["checked_at"]
    nulls = [r for r in snap["freshness"] if r["source_id"] == "never_source"]
    assert nulls and all(r["age_hours"] is None for r in nulls)


def test_ops_snapshot_latency_applies_runbook_filters(engine):
    store = MartStore(engine)
    store.upsert([
        _art("h1", "https://x.test/1", published_at=datetime(2026, 7, 20, 0, 0), fetched_at=datetime(2026, 7, 20, 2, 0)),   # 2.0h
        _art("h2", "https://x.test/2", published_at=datetime(2026, 7, 1, 0, 0), fetched_at=datetime(2026, 7, 10, 0, 0)),    # 07-14 이전 수집
        _art("h3", "https://x.test/3", published_at=datetime(2026, 6, 1, 0, 0), fetched_at=datetime(2026, 7, 20, 0, 0)),    # 30일 초과
        _art("h4", "https://x.test/4", published_at=datetime(2026, 7, 21, 0, 0), fetched_at=datetime(2026, 7, 20, 0, 0)),   # 발행이 수집보다 뒤
    ])
    assert store.ops_snapshot()["latency"] == [("bbc_sport", 2.0)]


def test_ops_snapshot_weekly_mix_and_articles_total(engine):
    store = MartStore(engine)
    store.upsert([
        _art("h1", "https://x.test/1", fetched_at=datetime(2026, 7, 20), tier=4, transfer_stage="rumour", journalist="Kim"),
        _art("h2", "https://x.test/2", fetched_at=datetime(2026, 7, 21), tier=4, transfer_stage="rumour", journalist=None),
        _art("h3", "https://x.test/3", fetched_at=datetime(2026, 7, 22), tier=1, transfer_stage=None, journalist=""),
        _art("h4", "https://x.test/4", fetched_at=datetime(2026, 7, 1), tier=1, transfer_stage="done", journalist="Lee"),   # 07-13 이전
    ])
    snap = store.ops_snapshot()
    rows = sorted(snap["weekly_mix"], key=lambda r: (r["tier"], str(r["stage"])))
    assert rows == [{"yw": 202630, "tier": 1.0, "stage": None, "n": 1, "n_byline": 0},
                    {"yw": 202630, "tier": 4.0, "stage": "rumour", "n": 2, "n_byline": 1}]
    assert snap["articles_total"] == 4                      # 총수는 창과 무관


def test_ops_snapshot_player_subjects_counts_subject_rows_of_squad_and_external_only(engine):
    _seed_players(engine)
    rows = sorted(MartStore(engine).ops_snapshot()["player_subjects"], key=lambda r: r["player_id"])
    assert rows == [{"player_id": 1, "ko_name": "기마랑이스", "category": "squad", "n": 2},     # 언급 1건은 안 센다
                    {"player_id": 2, "ko_name": None, "category": "external", "n": 1}]          # 감독 (3) 은 뺀다


def test_ops_snapshot_cold_start_returns_empty_shapes(engine):
    snap = MartStore(engine).ops_snapshot()
    assert snap == {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [],
                    "player_subjects": [], "articles_total": 0, "high_retention": []}


def test_ops_snapshot_includes_fetch_duration_with_nulls(engine):
    _seed_runs(engine, 3)
    snap = MartStore(engine).ops_snapshot()
    # 오름차순: run-000 (NULL) · run-001 (4.0+1=5.0) · run-002 (NULL) — 손 재계산
    assert snap["runs_all"][0]["fetch_duration_sec"] is None
    assert snap["runs_all"][1]["fetch_duration_sec"] == 5.0


def test_ops_snapshot_excludes_unfinished_runs(engine):
    """마감되지 않은 회차 (finished_at IS NULL) 는 스냅샷에서 제외된다."""
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:fetch,:counts,:new,:dup,:err,:sr)"),
            [{"rid": "run-finished", "t": datetime(2026, 7, 1, 0, 0),
              "dur": 60.0, "fetch": 5.0, "counts": json.dumps({}),
              "new": 1, "dup": 2, "err": 0, "sr": 0.9}])
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,"
            "fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:fetch,:counts,:new,:dup,:err,:sr)"),
            [{"rid": "run-unfinished", "t": datetime(2026, 7, 1, 6, 0),
              "fetch": 5.0, "counts": json.dumps({}),
              "new": 1, "dup": 2, "err": 0, "sr": 0.9}])
    run_ids = [r["run_id"] for r in MartStore(engine).ops_snapshot()["runs_all"]]
    assert "run-finished" in run_ids
    assert "run-unfinished" not in run_ids
```

`Article` 모델에 `journalist` · `transfer_stage` 필드가 있다 (`src/bullet_in/models.py`).
`players` 의 NOT NULL 열은 `full_name` · `surname` · `category` · `status` · `transfer_status` · `origin` · `added_at` 이다.

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/integration/test_ops_snapshot.py -q`
Expected: 9 가운데 8 FAIL (`KeyError: 'runs_all'` 등) · `freshness` 테스트만 PASS. 전부 skip 이면 MariaDB 컨테이너가 없는 것이다 (태스크 0).

- [ ] **Step 3: 구현**

`src/bullet_in/storage/mariadb.py` 머리 (`RETENTION_THRESHOLD` 가 있는 상수 자리) 에 셋을 더한다.

```python
# 수집 현황 화면의 창 셋 (런북 2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md §8).
OPS_EPOCH = datetime(2026, 6, 12)        # 첫 라이브 실행 · 회차 전체의 시작 (UTC)
LATENCY_SINCE = datetime(2026, 7, 14)    # 발행 → 수집 지연 · 그 전 행은 backfill 로 fetched_at 이 옮겨졌다
LATENCY_MAX_DAYS = 30
MIX_SINCE = datetime(2026, 7, 13)        # 주별 구성 · 월요일
```

`ops_snapshot` 을 아래로 바꾼다.

```python
    def ops_snapshot(self, trend_runs: int = 12) -> dict:
        """수집 현황 (ops.html) 집계 스냅샷 — 뷰모델 serve/ops_view 가 읽는다.

        회차는 첫 라이브 실행부터 전부 (오름차순) · 신선도는 최근 trend_runs 회 ·
        지연 · 주별 구성 · 선수 주체는 런북 §8 의 SQL 그대로다 (스펙 2026-09-05 §3.4).
        """
        with self.engine.connect() as c:
            # 회차 행이 두 단계로 적혀 finished_at 이 빈 행이 생길 수 있다 (collect · publish 스펙 2026-09-04 §5.3).
            # 뷰모델이 duration_sec 을 합산하는데 빈 행은 오류가 된다.
            runs_all = [dict(r) for r in c.execute(text(
                "SELECT run_id,started_at,duration_sec,fetch_duration_sec,"
                "source_counts,new_count,dup_count,error_count,success_rate "
                "FROM pipeline_runs WHERE finished_at IS NOT NULL AND started_at >= :epoch "
                "ORDER BY started_at"), {"epoch": OPS_EPOCH}).mappings().all()]
            freshness = [dict(r) for r in c.execute(text(
                "SELECT run_id,checked_at,source_id,last_fetched_at,"
                "age_hours,threshold_hours,stale FROM source_freshness "
                "WHERE run_id IN (SELECT run_id FROM ("
                " SELECT DISTINCT run_id, checked_at FROM source_freshness"
                " ORDER BY checked_at DESC LIMIT :n) w) "
                "ORDER BY checked_at, source_id"),
                {"n": trend_runs}).mappings().all()]
            # 소스 × 주 커버리지는 articles.fetched_at 이 아니라 위 runs_all 의 source_counts 로 그린다 —
            # 재수집 backfill 이 fetched_at 을 옮겨 6월이 빈다 (트러블슈팅 2026-09-04 three-charts §1).
            latency = [(sid, float(h)) for sid, h in c.execute(text(
                "SELECT source_id, TIMESTAMPDIFF(MINUTE, published_at, fetched_at) / 60 "
                "FROM articles WHERE published_at IS NOT NULL AND fetched_at >= :since "
                "AND fetched_at >= published_at "
                "AND TIMESTAMPDIFF(DAY, published_at, fetched_at) <= :max_days"),
                {"since": LATENCY_SINCE, "max_days": LATENCY_MAX_DAYS}).all()]
            weekly_mix = [{"yw": int(yw), "tier": tier, "stage": stage, "n": int(n), "n_byline": int(b)}
                          for yw, tier, stage, n, b in c.execute(text(
                "SELECT YEARWEEK(fetched_at, 3), tier, transfer_stage, COUNT(*), "
                "SUM(journalist IS NOT NULL AND journalist <> '') FROM articles "
                "WHERE fetched_at >= :since "
                "GROUP BY YEARWEEK(fetched_at, 3), tier, transfer_stage"),
                {"since": MIX_SINCE}).all()]
            # 선수 축은 기사 주체 (subject) 만 · 감독 · 임원은 뺀다 (같은 트러블슈팅 §2).
            player_subjects = [{"player_id": pid, "ko_name": ko, "category": cat, "n": int(n)}
                               for pid, ko, cat, n in c.execute(text(
                "SELECT p.id, p.ko_name, p.category, COUNT(*) FROM article_players ap "
                "JOIN players p ON p.id = ap.player_id "
                "WHERE ap.role = 'subject' AND p.category IN ('squad', 'external') "
                "GROUP BY p.id, p.ko_name, p.category")).all()]
            articles_total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar_one()
            high_rows = c.execute(text(
                "SELECT content_hash, outlet, rewrite_retention FROM articles "
                "WHERE rewrite_retention > :thr ORDER BY rewrite_retention DESC"),
                {"thr": RETENTION_THRESHOLD}).mappings().all()
        for r in runs_all:
            r["source_counts"] = (json.loads(r["source_counts"])
                                  if r["source_counts"] else {})
        return {"runs_all": runs_all, "freshness": freshness, "latency": latency,
                "weekly_mix": weekly_mix, "player_subjects": player_subjects,
                "articles_total": int(articles_total),
                "high_retention": [{"content_hash": r["content_hash"],
                                    "outlet": r["outlet"],
                                    "retention": float(r["rewrite_retention"])}
                                   for r in high_rows]}
```

`tier` 는 MariaDB FLOAT 라 `4.0` 으로 온다. 뷰모델이 `_tier_key` 로 `"4"` 를 만든다.

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/integration/test_ops_snapshot.py tests/integration/test_mariadb_store.py -q`
Expected: 9 passed (+ `test_mariadb_store` 전부 passed · 그 파일의 `ops_snapshot()["high_retention"]` 은 그대로다).

이 시점에 `tests/test_ops_view.py` · `tests/test_serve_ops.py` 는 옛 키 (`runs` · `tier_counts` · `pending`) 를 쓰므로 깨진다.
태스크 3 · 4 가 그 둘을 다시 쓴다.
전체 테스트는 태스크 4 끝에서 돌린다.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py tests/integration/test_ops_snapshot.py
git commit -m "feat(storage): 수집 현황 스냅샷에 회차 전체 · 지연 · 주별 구성 · 선수 주체 · 기사 총수 (안건 2φ · PR 2)" -m "수집 현황 화면이 12주 캘린더 · 소스 × 주 · 지연 분포 · 주별 구성 비율 · 선수 축을 그리려면 최근 30회만으로는 모자란다. 런북 §8 의 SQL 셋을 그대로 옮기고, 목업에 없는 절 (소스별 대기 · Tier 분포) 의 쿼리는 뺀다.

- runs_all · 2026-06-12 이후 마감된 회차 전부 (오름차순)
- latency · weekly_mix · player_subjects · articles_total 키 추가
- runs · tier_counts · pending 키 제거
- 통합 테스트 재작성 (8종 · 런북 필터 셋 · 주체 · 감독 제외)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 2 · 스펙 §3.4 · 런북 2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md §8
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

---

### Task 3: 뷰모델 `serve/ops_view.py`

**Files:**
- Create: `src/bullet_in/serve/ops_view.py`
- Test: `tests/test_ops_view.py` (전문 교체)

**Interfaces:**
- Consumes: 태스크 2 의 스냅샷 키 일곱 · 태스크 1 의 `GateTally` · `charts` 함수 (`sparkline` · `line_chart` · `stacked_columns` · `legend` · `hbars` · `heatmap` · `calendar` · `meter` · `dumbbell_log` · `table` · `fmt` · `E`) · `behavior_view` 의 헬퍼 (`_section` · `_fig` · `_two` · `_sents` · `_pct` · `_tier_key` · `TIER_ORDER` · `TIER_KO` · `MISSING_NOTE`) · `sources` (`{source_id: {"display_name": ...}}`) · `unmatched` (`render.unmatched_articles` 의 행 · `date` · `source` · `title`).
- Produces: `build_ops_view(snapshot: dict, sources: dict, anomaly_count: int, now: datetime, *, gate: GateTally | None = None, unmatched=None) -> dict` — 키 `generated_at` · `overview` · `tiles` · `slo` (행 여섯 · `slo_id` · `name` · `target` · `value` · `how` · `status`) · `sections` · `missing_note`.
  `sections` 원소는 PR 1 과 같은 절 dict 이거나 `{"pair": [절, 절]}` 이다.
  절 열 = `sec-slo` · `sec-ingestion-volume` · `sec-source-coverage` · `sec-throughput` · `sec-run-duration` · (`sec-ingestion-latency` · `sec-coverage-by-player` 나란히) · `sec-credibility-mix-stage-mix` · `sec-source-freshness` · `sec-review-tables`.

- [ ] **Step 1: 실패하는 테스트**

`tests/test_ops_view.py` 를 아래로 통째로 바꾼다.
옛 테스트 일곱은 옛 뷰 (표 넷 · `spark_points`) 를 재던 것이라 같이 사라진다.
픽스처 값은 손으로 재계산할 수 있게 작게 잡았고 기대값은 주석에 셈을 적었다.

```python
"""수집 현황 화면의 뷰모델 — 절 열이 목업 v2.8 의 id 로 나오고 값이 손 재계산과 맞는지.

픽스처는 작게 잡았다. 기대값은 전부 주석의 셈으로 따라갈 수 있다.
"""
from datetime import datetime

from bullet_in.dbt_gate import GateTally, TestOutcome
from bullet_in.serve.ops_view import NO_GATE, UNNAMED, build_ops_view

NOW = datetime(2026, 9, 5, 0, 10)                                  # UTC


def _run(rid, t, new, dup, err=0, dur=100.0, fetch=60.0, counts=None, sr=1.0):
    return {"run_id": rid, "started_at": t, "duration_sec": dur, "fetch_duration_sec": fetch,
            "source_counts": counts or {}, "new_count": new, "dup_count": dup,
            "error_count": err, "success_rate": sr}


RUNS = [_run("r0", datetime(2026, 8, 27, 0, 0), 10, 0, counts={"bbc_sport": 10}),          # 주 08/24
        _run("r1", datetime(2026, 9, 3, 0, 0), 4, 40, counts={"bbc_sport": 3, "fmkorea": 1}),
        _run("r2", datetime(2026, 9, 3, 3, 0), 2, 38, err=1, dur=300.0, sr=0.9, counts={"fmkorea": 2}),
        _run("r3", datetime(2026, 9, 4, 0, 0), 6, 54, dur=120.0, fetch=None, counts={"bbc_sport": 6})]
T = datetime(2026, 9, 4, 0, 2)
FRESH = [{"run_id": "r1", "checked_at": datetime(2026, 9, 3, 0, 2), "source_id": "bbc_sport",
          "last_fetched_at": datetime(2026, 9, 2, 20, 0), "age_hours": 4.0, "threshold_hours": 96.0, "stale": 0},
         {"run_id": "r3", "checked_at": T, "source_id": "bbc_sport",
          "last_fetched_at": datetime(2026, 9, 3, 20, 0), "age_hours": 4.0, "threshold_hours": 96.0, "stale": 0},
         {"run_id": "r3", "checked_at": T, "source_id": "fmkorea",
          "last_fetched_at": datetime(2026, 9, 2, 18, 0), "age_hours": 30.0, "threshold_hours": 24.0, "stale": 1},
         {"run_id": "r3", "checked_at": T, "source_id": "never",
          "last_fetched_at": None, "age_hours": None, "threshold_hours": 48.0, "stale": 0}]
LATENCY = [("bbc_sport", 1.0), ("bbc_sport", 3.0), ("bbc_sport", 100.0), ("fmkorea", 20.0)]
MIX = [{"yw": 202636, "tier": 4.0, "stage": "rumour", "n": 6, "n_byline": 3},        # 주 08/31
       {"yw": 202636, "tier": 1.0, "stage": "official", "n": 4, "n_byline": 4},
       {"yw": 202635, "tier": 2.0, "stage": None, "n": 5, "n_byline": 0}]            # 주 08/24 · 단계 없음 → 기타
SUBJECTS = [{"player_id": 1, "ko_name": "기마랑이스", "category": "squad", "n": 149},
            {"player_id": 2, "ko_name": "알바레스", "category": "external", "n": 103},
            {"player_id": 3, "ko_name": None, "category": "external", "n": 60},
            {"player_id": 4, "ko_name": "", "category": "external", "n": 45}]
GATE = GateTally(generated_at="2026-09-04T21:03:00.000000Z", unique_total=5, unique_failed=[],
                 not_null_total=10, not_null_failed=[TestOutcome("not_null_stg_articles_transfer_stage", 2)])
SNAPSHOT = {"runs_all": RUNS, "freshness": FRESH, "latency": LATENCY, "weekly_mix": MIX,
            "player_subjects": SUBJECTS, "articles_total": 200,
            "high_retention": [{"content_hash": "a" * 64, "outlet": "The Athletic", "retention": 0.934}]}
EMPTY = {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [], "player_subjects": [],
         "articles_total": 0, "high_retention": []}
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}, "fmkorea": {"display_name": "fmkorea"},
           "dead": {"display_name": "Dead"}}
UNMATCHED = [{"date": "2026-09-03", "source": "bbc_sport", "title": "추출 실패 기사"}]
IDS = ["sec-slo", "sec-ingestion-volume", "sec-source-coverage", "sec-throughput", "sec-run-duration",
       "sec-ingestion-latency", "sec-coverage-by-player", "sec-credibility-mix-stage-mix",
       "sec-source-freshness", "sec-review-tables"]


def _view(snapshot=SNAPSHOT, gate=GATE, anomaly=0):
    return build_ops_view(snapshot, SOURCES, anomaly, NOW, gate=gate, unmatched=UNMATCHED)


def _flat(view):
    return [s for item in view["sections"] for s in (item["pair"] if "pair" in item else [item])]


def _sec(view, id_):
    return next(s for s in _flat(view) if s["id"] == id_)


def test_절_열이_목업의_id_순서로_나온다():
    view = _view()
    assert [s["id"] for s in _flat(view)] == IDS
    assert all(not s["missing"] for s in _flat(view))          # 수집 현황에는 빈 구간이 없다 (스펙 §4)
    assert view["generated_at"] == "2026-09-05 00:10 UTC"


def test_타일_여섯은_최근_30회에서_만든다():
    tiles = {t["label"]: t for t in _view()["tiles"]}
    assert len(tiles) == 6
    assert tiles["신규 · 최근 회차"]["value"] == "6" and tiles["신규 · 최근 회차"]["sub"] == "09-04 00:00 UTC"
    assert tiles["Dedup Rate · 4회"]["value"] == "86%"          # 132 / (22 + 132) = 85.7
    assert tiles["Success Rate · 4회"]["value"] == "97.5%"      # (1 + 1 + .9 + 1) / 4
    assert tiles["Run Duration p50 · 4회"]["value"] == "120초"  # [100, 100, 120, 300] 의 p50
    assert tiles["Run Duration p50 · 4회"]["sub"] == "fetch 60초"
    assert tiles["Stale Sources"]["value"] == "1"
    assert tiles["Runs · 12주"]["value"] == "4"                 # 06-12 에서 09-05 = 86일 = 12주
    assert tiles["Runs · 12주"]["sub"] == "에러 회차 1 · 기대 8/일"


def test_slo_여섯_행의_값과_상태():
    rows = {r["slo_id"]: r for r in _view()["slo"]}
    assert list(rows) == ["SLO-1", "SLO-2", "SLO-3", "SLO-4", "SLO-5", "SLO-6"]
    assert rows["SLO-1"]["value"] == "56.5%↓" and rows["SLO-1"]["status"] == "ok"
    assert rows["SLO-2"]["value"] == "97.5%" and rows["SLO-2"]["status"] == "bad"      # 목표 99%
    assert rows["SLO-3"]["value"] == "0%" and rows["SLO-3"]["status"] == "ok"
    assert rows["SLO-3"]["how"] == "dbt unique 테스트 5종 통과 · 게이트 09-04 21:03 UTC"
    assert rows["SLO-4"]["value"] == "99.0%" and rows["SLO-4"]["status"] == "ok"       # 1 − 2 / 200
    assert "10종 가운데 1종 결측 2행" in rows["SLO-4"]["how"]
    assert rows["SLO-5"]["value"] == "1" and rows["SLO-5"]["status"] == "bad"
    assert rows["SLO-6"]["value"] == "0" and rows["SLO-6"]["status"] == "ok"
    body = str(_sec(_view(), "sec-slo")["body"])
    assert body.count("<tr>") == 7 and "✕ 미달" in body           # 머리 1 + 행 6


def test_게이트_결과가_없으면_3_4_는_참고_행이다():
    rows = {r["slo_id"]: r for r in _view(gate=None)["slo"]}
    assert rows["SLO-3"]["value"] == NO_GATE and rows["SLO-3"]["status"] == "info"
    assert rows["SLO-4"]["value"] == NO_GATE and rows["SLO-4"]["status"] == "info"


def test_unique_실패는_중복_적재율로_바뀐다():
    gate = GateTally(generated_at="", unique_total=5, unique_failed=[TestOutcome("unique_stg_articles_url", 3)],
                     not_null_total=10, not_null_failed=[])
    rows = {r["slo_id"]: r for r in _view(gate=gate)["slo"]}
    assert rows["SLO-3"]["value"] == "1.50%" and rows["SLO-3"]["status"] == "bad"     # 3 / 200
    assert rows["SLO-4"]["value"] == "100.0%"


def test_수집량_표는_회차가_있는_날만_적는다():
    body = str(_sec(_view(), "sec-ingestion-volume")["body"])
    assert body.count("<tr><td>2026-") == 3
    # 09-03: 신규 4 + 2 · 중복 40 + 38 · 회차 2 · 에러 1 · p50 of [100, 300] = 300
    assert "<tr><td>2026-09-03</td><td>6</td><td>78</td><td>2</td><td>1</td><td>300</td></tr>" in body
    assert "기대 8" in body and ">Airflow<" in body               # 기준선과 전환 표시


def test_소스_커버리지는_회차_기록의_소스별_건수를_주로_묶는다():
    body = str(_sec(_view(), "sec-source-coverage")["body"])
    assert "BBC Sport · 08/31\n9건" in body                      # 3 + 6
    assert "fmkorea · 08/31\n3건" in body                        # 1 + 2
    assert "BBC Sport · 08/24\n10건" in body
    assert "Dead · 08/31\n0건" in body                           # 설정에만 있는 소스도 행이 있다
    cats = [c for c in ("BBC Sport", "fmkorea", "Dead") if f">{c}<" in body]
    assert body.index(">BBC Sport<") < body.index(">fmkorea<") < body.index(">Dead<")   # 합 내림차순


def test_처리량은_주별_합과_중복률이다():
    s = _sec(_view(), "sec-throughput")
    body = str(s["body"])
    assert "08/31\n12건 · 신규" in body and "08/24\n10건 · 신규" in body
    assert "08/31\n92% · Dedup Rate" in body                     # 132 / 144
    assert s["insights"][0] == ("12주 합은 신규 22건 · 중복 차단 132건이다.", ["중복이 신규의 6배다."])


def test_소요_절은_밴드_에러_표시_주별_구성을_그린다():
    s = _sec(_view(), "sec-run-duration")
    body = str(s["body"])
    assert body.count('class="fail"') == 1 and "09/03\n에러 회차 1회" in body
    assert 'class="band s1"' in body
    # 주 08/31: fetch (60 + 60 + 0) / 3 = 40 · 나머지 ((100−60) + (300−60) + 120) / 3 = 133.33
    assert "08/31\n40초 · 수집 (fetch)\n133.33초 · 번역 · 게이트 · 배포" in body
    assert s["insights"][0][0] == "지난 4회 p50 은 120초이고 fetch 가 60초다."
    assert s["insights"][1][0] == "1,000초를 넘긴 회차는 0회다."


def test_지연은_소스별_p50_p95_를_p50_순으로_로그_축에_그린다():
    s = _sec(_view(), "sec-ingestion-latency")
    body = str(s["body"])
    assert "BBC Sport\np50 3.0h · p95 100.0h\n기사 3건" in body
    assert body.index(">BBC Sport<") < body.index(">fmkorea<")
    assert s["insights"][1][0] == "회차 간격 (3시간) 안에 드는 소스는 1곳이다."


def test_선수_축은_주체만_세고_이름_없는_후보는_한_줄로_모은다():
    s = _sec(_view(), "sec-coverage-by-player")
    body = str(s["body"])
    assert "기마랑이스\n149건" in body and "알바레스\n103건" in body
    assert f"{UNNAMED}\n105건" in body                            # 60 + 45
    assert 'class="bar s1"' in body and 'class="bar s2"' in body and "dimbar dim" in body
    assert "357건만 세고" in " ".join(s["question"])              # 149 + 103 + 60 + 45


def test_구성_비율은_숫자를_적은_히트맵이고_빈_단계는_기타다():
    s = _sec(_view(), "sec-credibility-mix-stage-mix")
    body = str(s["body"])
    assert "4 타블로이드 · 08/31\n60%" in body and "1 최상 · 08/31\n40%" in body
    assert "루머 · 08/31\n60%" in body and "공식 · 완료 · 08/31\n40%" in body
    assert "기타 · 08/24\n100%" in body
    assert "08/31\n70% · 식별률" in body                          # 7 / 10
    assert s["insights"] == [("등급 4 비중이 가장 높은 주는 08/31 (60%) 다.", []),
                             ("기자 식별률은 0% 에서 70% 사이다.", [])]


def test_신선도_표는_임계_대비_비율_순이고_미터를_그린다():
    s = _sec(_view(), "sec-source-freshness")
    body = str(s["body"])
    assert body.index(">fmkorea<") < body.index(">BBC Sport<") < body.index(">never<")   # 1.25 · 0.04 · 0
    assert "✕ 초과" in body and 'class="fill bad"' in body
    assert "30.0h / 24h" in body and "이력 없음" in body
    assert s["insights"][0] == ("임계는 소스마다 다르다 (24h 에서 96h).", [])
    assert s["insights"][1] == ("임계를 넘은 소스는 fmkorea 다.", [])


def test_확인_대상_절은_두_표를_그대로_둔다():
    body = str(_sec(_view(), "sec-review-tables")["body"])
    assert f'href="article/{"a" * 64}.html">aaaaaaaa<' in body and ">0.93<" in body
    assert "추출 실패 기사" in body
    assert "재작성 잔존율 확인 대상 (1건)" in body and "선수 추출 누락 (1건)" in body


def test_빈_스냅샷이면_타일이_없고_절은_전부_그려진다():
    view = build_ops_view(EMPTY, SOURCES, 0, NOW, gate=None, unmatched=None)
    assert view["tiles"] == []
    assert [s["id"] for s in _flat(view)] == IDS
    rows = {r["slo_id"]: r for r in view["slo"]}
    assert rows["SLO-2"]["status"] == "info" and rows["SLO-5"]["status"] == "info"
    assert "아직 없다" in str(_sec(view, "sec-ingestion-latency")["body"])


def test_개요는_기사_총수와_기간을_적는다():
    ov = dict((lab, (txt, subs)) for lab, txt, subs in _view()["overview"])
    assert ov["기간"][0] == "2026-06-12 첫 라이브 실행부터 12주 (86일)."
    assert ("articles", "기사 200건 · 등급 · 이적 단계 · 발행 시각.") in ov["데이터 원천"][1]


def test_설명문은_문장마다_줄을_가른다():
    for s in _flat(_view()):
        assert len(s["question"]) >= 1 and all(q.endswith(".") for q in s["question"])
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_ops_view.py -q`
Expected: FAIL · `ImportError` (`bullet_in.serve.ops_view` 없음 · `serve/__init__.py` 가 있어 `ModuleNotFoundError` 가 아니다).

- [ ] **Step 3: 구현**

`src/bullet_in/serve/ops_view.py` 를 만든다.

```python
"""수집 현황 화면의 뷰모델 — MariaDB 스냅샷과 게이트 집계를 절 열의 값 · SVG 로 바꾼다.

화면 (`ops.html.j2`) 은 이 모듈이 돌려주는 dict 만 본다.
절 순서와 `id` 는 목업 v2.8 그대로이고, 마지막 절은 기존 두 표 (재작성 잔존율 · 선수 추출 누락) 다.
시각은 전부 UTC 다 — 저장값이 UTC 이고 목업도 UTC 로 그렸다.
스냅샷 키가 비어도 (첫 회차 · 로컬) 절은 전부 그리고 타일만 비운다 (스펙 §4 · 빈 구간 없음).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from markupsafe import Markup

from bullet_in.dbt_gate import GateTally
from bullet_in.serve import charts as C
from bullet_in.serve.behavior_view import (MISSING_NOTE, TIER_KO, TIER_ORDER, _fig, _pct, _section,
                                           _tier_key, _two)

OPS_EPOCH = date(2026, 6, 12)              # 첫 라이브 실행 · 회차 전체의 시작 (storage.mariadb.OPS_EPOCH 와 같은 날)
MIX_SINCE = date(2026, 7, 13)              # 주별 구성의 시작 (월요일 · storage.mariadb.MIX_SINCE)
EXPECTED_RUNS_PER_DAY = 8
RECENT_RUNS = 30                           # 타일 · SLO-2 의 창
EVENTS = (("2026-09-04", "Airflow"),)      # 회차가 Airflow 로 옮겨 간 날 (2026-09-04 15:51 KST)
SLO2_TARGET = 0.99
SLO4_TARGET = 0.99
# SLO-1 은 회차마다 안 재므로 런북 값을 고정으로 적는다 (README §4 · 런북 2026-07-14-slo1-benchmark.md).
SLO1_VALUE = "56.5%↓"
SLO1_HOW = "벤치마크 3회 중앙값 · 2026-07-15 · 회차마다 안 잰다"
STAGE_GROUPS = (("루머", ("rumour",)), ("관심", ("interest",)), ("협상", ("negotiating",)),
                ("합의 · 메디컬", ("agreed", "personal_terms", "medical")),
                ("공식 · 완료", ("official", "done")), ("무산", ("collapsed",)),
                ("기타", ("other", None)))
UNNAMED = "이름 미확정 (후보 명단)"
NO_GATE = "게이트 결과 없음"
NONE_YET = '<p class="q">아직 없다.</p>'


# --- 작은 헬퍼 -----------------------------------------------------------------

def _monday(d: date) -> date:
    return d - timedelta(d.isoweekday() - 1)


def _weeks(start: date, end: date) -> list[date]:
    out, d = [], _monday(start)
    while d <= end:
        out.append(d)
        d += timedelta(7)
    return out


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(i) for i in range((end - start).days + 1)]


def _wl(d: date) -> str:
    """주 · 날짜 라벨 — 08/31"""
    return f"{d:%m/%d}"


def _pctile(vals, q) -> float:
    """가장 가까운 순위 백분위 — 값이 없으면 0."""
    s = sorted(vals)
    return s[int(q * (len(s) - 1) + 0.5)] if s else 0.0


def _yw_monday(yw: int) -> date:
    """YEARWEEK(x, 3) 정수 → 그 주 월요일"""
    return date.fromisocalendar(yw // 100, yw % 100, 1)


def _display(sources, sid) -> str:
    return (sources or {}).get(sid, {}).get("display_name") or sid


def _by_day(runs_all) -> dict[date, list[dict]]:
    out = defaultdict(list)
    for r in runs_all:
        out[r["started_at"].date()].append(r)
    return out


def _by_week(runs_all) -> dict[date, list[dict]]:
    out = defaultdict(list)
    for r in runs_all:
        out[_monday(r["started_at"].date())].append(r)
    return out


def _gate_at(iso: str) -> str:
    try:
        return f"{datetime.fromisoformat(iso.replace('Z', '+00:00')):%m-%d %H:%M} UTC"
    except ValueError:
        return iso or "시각 없음"


# --- 타일 ---------------------------------------------------------------------

def _tiles(runs_all, recent, stale_count, span_weeks) -> list[dict]:
    if not recent:
        return []
    top = recent[-1]
    n = len(recent)
    new, dup = sum(r["new_count"] for r in recent), sum(r["dup_count"] for r in recent)
    rates = [_pct(r["dup_count"], r["new_count"] + r["dup_count"]) for r in recent]
    durs = [r["duration_sec"] for r in recent]
    fetch = [r["fetch_duration_sec"] for r in recent if r.get("fetch_duration_sec") is not None]
    sr = sum(r["success_rate"] for r in recent) / n
    errs = sum(1 for r in runs_all if r["error_count"] > 0)
    return [
        {"label": "신규 · 최근 회차", "value": C.fmt(top["new_count"]),
         "sub": f"{top['started_at']:%m-%d %H:%M} UTC",
         "spark": Markup(C.sparkline([r["new_count"] for r in recent]))},
        {"label": f"Dedup Rate · {n}회", "value": f"{_pct(dup, new + dup)}%",
         "sub": "중복 차단 ÷ (신규 + 중복)", "spark": Markup(C.sparkline(rates))},
        {"label": f"Success Rate · {n}회", "value": f"{sr * 100:.1f}%",
         "sub": f"SLO-2 목표 {SLO2_TARGET * 100:.0f}%", "spark": ""},
        {"label": f"Run Duration p50 · {n}회", "value": f"{_pctile(durs, .5):.0f}초",
         "sub": f"fetch {_pctile(fetch, .5):.0f}초" if fetch else "fetch 이력 없음",
         "spark": Markup(C.sparkline(durs))},
        {"label": "Stale Sources", "value": "—" if stale_count is None else C.fmt(stale_count),
         "sub": "임계 초과 소스 (SLO-5)", "spark": ""},
        {"label": f"Runs · {span_weeks}주", "value": C.fmt(len(runs_all)),
         "sub": f"에러 회차 {C.fmt(errs)} · 기대 {EXPECTED_RUNS_PER_DAY}/일", "spark": ""},
    ]


# --- SLO ----------------------------------------------------------------------

def _slo_rows(recent, stale_count, anomaly_count, gate: GateTally | None, articles_total: int) -> list[dict]:
    def row(i, name, target, value, how, status):
        return {"slo_id": f"SLO-{i}", "name": name, "target": target, "value": value, "how": how, "status": status}

    rows = [row(1, "병렬화 수집 시간 단축", "순차 대비 ≥ 55%↓", SLO1_VALUE, SLO1_HOW, "ok")]
    if recent:
        sr = sum(r["success_rate"] for r in recent) / len(recent)
        rows.append(row(2, "회차 성공률", f"≥ {SLO2_TARGET * 100:.0f}%", f"{sr * 100:.1f}%",
                        f"최근 {len(recent)}회 평균 success_rate", "ok" if sr >= SLO2_TARGET else "bad"))
    else:
        rows.append(row(2, "회차 성공률", f"≥ {SLO2_TARGET * 100:.0f}%", "—", "회차 이력 없음", "info"))
    total = articles_total or 1
    if gate is None:
        rows.append(row(3, "중복 적재율", "0%", NO_GATE, "dbt unique 테스트", "info"))
        rows.append(row(4, "필수 필드 완전성", f"≥ {SLO4_TARGET * 100:.0f}%", NO_GATE, "dbt not_null 테스트", "info"))
    else:
        at = _gate_at(gate.generated_at)
        dups = sum(t.failures for t in gate.unique_failed)
        how3 = (f"dbt unique 테스트 {gate.unique_total}종 "
                + ("통과" if not gate.unique_failed else f"가운데 {len(gate.unique_failed)}종 실패")
                + f" · 게이트 {at}")
        rows.append(row(3, "중복 적재율", "0%", "0%" if not dups else f"{dups / total * 100:.2f}%", how3,
                        "ok" if not gate.unique_failed else "bad"))
        worst = max((t.failures for t in gate.not_null_failed), default=0)
        comp = 1 - worst / total
        how4 = (f"dbt not_null 테스트 {gate.not_null_total}종 "
                + ("통과" if not gate.not_null_failed
                   else f"가운데 {len(gate.not_null_failed)}종 결측 {worst}행")
                + " · 같은 게이트")
        rows.append(row(4, "필수 필드 완전성", f"≥ {SLO4_TARGET * 100:.0f}%", f"{comp * 100:.1f}%", how4,
                        "ok" if comp >= SLO4_TARGET else "bad"))
    rows.append(row(5, "소스 신선도", "끊긴 소스 0", "—" if stale_count is None else C.fmt(stale_count),
                    "source_freshness 워터마크 · 임계 초과 소스 수",
                    "info" if stale_count is None else ("ok" if not stale_count else "bad")))
    rows.append(row(6, "수집량 이상", "이상 소스 0", C.fmt(anomaly_count),
                    "직전 회차들 대비 ±2σ 드롭 · 스파이크 (quality.volume_anomalies)",
                    "ok" if anomaly_count == 0 else "bad"))
    return rows


_PILL = {"ok": '<span class="pill ok">✓ 충족</span>', "bad": '<span class="pill bad">✕ 미달</span>',
         "info": '<span class="pill">참고</span>'}


def _slo(rows, gate):
    q = ("회차 성공률 · 중복 적재율 · 필수 필드 완전성 · 소스 신선도 · 수집량 이상 · 병렬화 여섯 지표가 각자의 목표치를 지금 지키는지 확인한다. "
         "2 · 5 · 6 은 회차마다 코드가 직접 재고 3 · 4 는 회차 끝 dbt 게이트가 낸 테스트 결과에서 읽으며 1 은 벤치마크로 잰 값이다.")
    body = ('<table class="fresh"><thead><tr><th>#</th><th>지표</th><th>목표</th><th class="num">현재</th>'
            '<th>측정</th><th>상태</th></tr></thead><tbody>'
            + "".join(f"<tr><td>{r['slo_id']}</td><td>{C.E(r['name'])}</td><td>{C.E(r['target'])}</td>"
                      f"<td class=\"num\">{C.E(r['value'])}</td><td>{C.E(r['how'])}</td><td>{_PILL[r['status']]}</td></tr>"
                      for r in rows)
            + "</tbody></table>")
    ins = []
    bad = [r["slo_id"] for r in rows if r["status"] == "bad"]
    if bad:
        ins.append((f"미달은 {' · '.join(bad)} 이다.", []))
    ins.append(("SLO-3 · 4 는 직전 회차 게이트의 값이다." if gate else "SLO-3 · 4 는 게이트 결과 파일이 생기면 채워진다.",
                ["게이트가 막히면 두 행이 ✕ 로 바뀌고 배포가 멈춘다."]))
    return _section("sec-slo", "SLO", "여섯 지표 · 목표 · 현재", q, body, ins)


# --- 절 -----------------------------------------------------------------------

def _volume(runs_all, today: date, span_weeks: int):
    title, sub = "Ingestion Volume", "일별 신규 기사 · 회차 수"
    q = (f"{span_weeks}주 동안 하루에 몇 건씩 새 기사가 들어왔는지 캘린더로 본다. "
         f"회차가 하루 {EXPECTED_RUNS_PER_DAY}회를 채웠는지 기준선과 함께 확인한다.")
    days = _days(OPS_EPOCH, today)
    by = _by_day(runs_all)
    new = {d.isoformat(): sum(r["new_count"] for r in by.get(d, [])) for d in days}
    counts = [len(by.get(d, [])) for d in days]
    events = [(days.index(date.fromisoformat(d)), lab) for d, lab in EVENTS if date.fromisoformat(d) in days]
    body = (_two(_fig("일별 신규 기사 (캘린더)", C.calendar(new, OPS_EPOCH, today, w=520)),
                 _fig(f"일별 회차 수 (기대 {EXPECTED_RUNS_PER_DAY})",
                      C.line_chart([_wl(d) for d in days], [("회차", counts)], unit="회",
                                   ref=EXPECTED_RUNS_PER_DAY, events=events, w=520, h=190)))
            + C.table(["날짜", "신규", "중복", "회차", "에러 회차", "p50 소요"],
                      [(d.isoformat(), new[d.isoformat()], sum(r["dup_count"] for r in by[d]), len(by[d]),
                        sum(1 for r in by[d] if r["error_count"] > 0),
                        f"{_pctile([r['duration_sec'] for r in by[d]], .5):.0f}")
                       for d in days if d in by]))
    ins = []
    if by:
        top = max(new, key=new.get)
        ins.append((f"하루 최고는 {top[5:]} 의 {C.fmt(new[top])}건이다.", []))
        short = sum(1 for d in days if d in by and len(by[d]) < EXPECTED_RUNS_PER_DAY)
        ins.append((f"회차가 {EXPECTED_RUNS_PER_DAY}회에 못 미친 날은 {short}일이다.", []))
    return _section("sec-ingestion-volume", title, sub, q, body, ins)


def _coverage(runs_all, sources, today: date, span_weeks: int):
    title, sub = "Source Coverage", "소스 × 주 신규 기사"
    q = ("소스마다 주 단위로 새 기사 수를 보고 어느 소스가 언제 살아 있었는지 확인한다. "
         "회차 기록에 남은 소스별 건수라 재수집으로 날짜가 옮겨진 것과는 상관이 없다. "
         "빈 칸이 이어지면 셀렉터가 깨졌거나 차단당한 구간이다.")
    weeks = _weeks(OPS_EPOCH, today)
    cells = defaultdict(int)
    for r in runs_all:
        wk = _monday(r["started_at"].date())
        for sid, n in r["source_counts"].items():
            cells[(sid, wk)] += n
    sids = set(sources or {}) | {sid for sid, _ in cells}
    total = {sid: sum(v for (s, _), v in cells.items() if s == sid) for sid in sids}
    rows = sorted(sids, key=lambda s: (-total[s], s))
    full = {(s, w): cells.get((s, w), 0) for s in rows for w in weeks}
    body = C.heatmap(rows, weeks, full, w=980, unit="건", rowlab=lambda s: _display(sources, s), collab=_wl)
    ins = []
    if rows and total[rows[0]]:
        ins.append((f"{span_weeks}주 합이 가장 큰 소스는 {_display(sources, rows[0])} {C.fmt(total[rows[0]])}건이다.", []))
        gappy = []
        for s in rows:
            seen = False
            for w in weeks[:-1]:                     # 이번 주는 아직 진행 중이라 안 센다
                if full[(s, w)]:
                    seen = True
                elif seen:
                    gappy.append(s)
                    break
        if gappy:
            ins.append((f"살아난 뒤 빈 주가 있는 소스는 {' · '.join(_display(sources, s) for s in gappy)} 다.", []))
    return _section("sec-source-coverage", title, sub, q, body, ins)


def _throughput(runs_all, today: date, span_weeks: int):
    title, sub = "Throughput", "주별 신규 · 중복 차단"
    q = "들어온 것 가운데 새 기사가 얼마이고 같은 원문이 다시 들어온 것이 얼마인지 주마다 본다."
    weeks = _weeks(OPS_EPOCH, today)
    per = _by_week(runs_all)
    new = [sum(r["new_count"] for r in per.get(w, [])) for w in weeks]
    dup = [sum(r["dup_count"] for r in per.get(w, [])) for w in weeks]
    labels = [_wl(w) for w in weeks]
    rate = [_pct(d, n + d) for n, d in zip(new, dup)]
    body = _two(_fig("주별 신규 기사 (건)", C.stacked_columns(labels, [("신규", new, "s1")], unit="건")),
                _fig("Dedup Rate · 중복 차단 ÷ (신규 + 중복) · %",
                     C.line_chart(labels, [("Dedup Rate", rate)], unit="%", w=520, h=190)))
    tn, td = sum(new), sum(dup)
    # 주 수는 타일 · 개요와 같은 span_weeks 다 — 주 열 (월요일 수) 로 세면 한 화면에 12주와 13주가 섞인다
    ins = ([(f"{span_weeks}주 합은 신규 {C.fmt(tn)}건 · 중복 차단 {C.fmt(td)}건이다.",
             [f"중복이 신규의 {td / tn:.0f}배다."] if tn else [])] if tn or td else [])
    return _section("sec-throughput", title, sub, q, body, ins)


def _duration(runs_all, today: date):
    title, sub = "Run Duration", "p10 에서 p90 밴드 · p50 선 · 주별 구성"
    q = "회차에 걸린 시간이 어떻게 분포하는지 보고 그 시간이 수집과 번역 · 게이트 · 배포로 어떻게 나뉘는지 확인한다."
    days = _days(OPS_EPOCH, today)
    by = _by_day(runs_all)

    def pq(d, q_):
        return _pctile([r["duration_sec"] for r in by.get(d, [])], q_)

    p50 = [pq(d, .5) for d in days]
    band = ([pq(d, .1) for d in days], [pq(d, .9) for d in days])
    fails = []
    for i, d in enumerate(days):
        k = sum(1 for r in by.get(d, []) if r["error_count"] > 0)
        if k:
            fails.append((i, f"에러 회차 {k}회"))
    events = [(days.index(date.fromisoformat(d)), lab) for d, lab in EVENTS if date.fromisoformat(d) in days]
    weeks = _weeks(OPS_EPOCH, today)
    per = _by_week(runs_all)

    def avg(w, f):
        rs = per.get(w, [])
        return sum(f(r) for r in rs) / len(rs) if rs else 0

    fetch = [avg(w, lambda r: r.get("fetch_duration_sec") or 0) for w in weeks]        # NULL 이력은 0 (옛 13회)
    rest = [avg(w, lambda r: r["duration_sec"] - (r.get("fetch_duration_sec") or 0)) for w in weeks]
    body = _two(_fig("하루 p50 (초) · 밴드 p10 에서 p90 · ✕ 에러 회차",
                     C.line_chart([_wl(d) for d in days], [("p50", p50)], unit="초", band=band, fails=fails,
                                  events=events, w=520, h=190)),
                _fig("주별 회차당 평균 소요 구성 (초)",
                     C.stacked_columns([_wl(w) for w in weeks],
                                       [("수집 (fetch)", fetch, "s1"), ("번역 · 게이트 · 배포", rest, "s2")], unit="초")
                     + C.legend([("수집 (fetch)", "s1"), ("번역 · 게이트 · 배포", "s2")])))
    ins = []
    recent = runs_all[-RECENT_RUNS:]
    if recent:
        fv = [r["fetch_duration_sec"] for r in recent if r.get("fetch_duration_sec") is not None]
        ins.append((f"지난 {len(recent)}회 p50 은 {_pctile([r['duration_sec'] for r in recent], .5):.0f}초이고"
                    + (f" fetch 가 {_pctile(fv, .5):.0f}초다." if fv else " fetch 이력은 없다."), []))
        ins.append((f"1,000초를 넘긴 회차는 {C.fmt(sum(1 for r in runs_all if r['duration_sec'] > 1000))}회다.", []))
    return _section("sec-run-duration", title, sub, q, body, ins)


def _latency(latency, sources):
    title, sub = "Ingestion Latency", "발행 → 수집 지연 · 소스별 p50 · p95"
    q = ("기사가 발행된 뒤 우리가 받기까지 걸린 시간을 소스마다 본다. "
         "3시간 회차의 이론 하한은 1.5시간이다. "
         "07-14 이후에 수집한 것만 세고 30일 넘는 것은 뺐다.")
    by = defaultdict(list)
    for sid, h in latency:
        by[sid].append(h)
    # p95 하한 0.5 — 로그 축의 아래 끝 (charts.dumbbell_log 의 lo) 과 같아지면 눈금이 0 으로 나뉜다
    rows = sorted(((_display(sources, s), _pctile(v, .5), max(_pctile(v, .95), 0.5), len(v)) for s, v in by.items()),
                  key=lambda r: r[1])
    body = C.dumbbell_log(rows, w=560) if rows else NONE_YET
    ins = []
    if rows:
        ins.append((f"p50 이 가장 짧은 소스는 {rows[0][0]} {rows[0][1]:.1f}시간이고 "
                    f"가장 긴 소스는 {rows[-1][0]} {rows[-1][1]:.1f}시간이다.", []))
        ins.append((f"회차 간격 (3시간) 안에 드는 소스는 {sum(1 for r in rows if r[1] <= 3)}곳이다.", []))
    return _section("sec-ingestion-latency", title, sub, q, body, ins)


def _players(subjects):
    title, sub = "Coverage by Player", "기사 주체 기준 · 상위 10"
    total = sum(r["n"] for r in subjects)
    q = (f"누구 이야기가 가장 많이 들어오는지 본다. "
         f"기사의 주체 (subject) 로 귀속된 {C.fmt(total)}건만 세고 본문에 스친 언급 (mention) 은 뺀다. "
         "감독 · 임원은 축에서 뺀다.")
    named = sorted((r for r in subjects if r.get("ko_name")), key=lambda r: -r["n"])[:10]
    rows = [{"lab": r["ko_name"], "n": r["n"], "cls": "s1" if r["category"] == "squad" else "s2"} for r in named]
    unnamed = sum(r["n"] for r in subjects if not r.get("ko_name"))
    if unnamed:
        rows.append({"lab": UNNAMED, "n": unnamed, "cls": "dimbar"})
    body = ((C.hbars(rows, value="n", label="lab", unit="건", dim_label=UNNAMED) if rows else NONE_YET)
            + C.legend([("아스날 스쿼드", "s1"), ("외부 선수 (영입 링크)", "s2"), ("이름 미확정", "dimbar")]))
    ins = []
    if named:
        ins.append((f"{named[0]['ko_name']} 가 {C.fmt(named[0]['n'])}건으로 1위다.", []))
    if unnamed:
        ins.append((f"한국어 표기가 아직 안 붙은 후보 명단 인물이 주체 {C.fmt(unnamed)}건이다.", []))
    return _section("sec-coverage-by-player", title, sub, q, body, ins)


def _mix(weekly_mix, today: date):
    title, sub = "Credibility Mix · Stage Mix", "주별 구성 비율 · %"
    q = ("들어오는 기사의 공신력 등급 구성과 이적 단계 구성이 주마다 어떻게 바뀌는지 본다. "
         "칸의 숫자는 그 주 기사 가운데 그 등급 · 단계가 차지하는 비율이다.")
    weeks = _weeks(MIX_SINCE, today)
    tot, byline = defaultdict(int), defaultdict(int)
    tier, stage = defaultdict(int), defaultdict(int)
    for r in weekly_mix:
        w = _yw_monday(r["yw"])
        tot[w] += r["n"]
        byline[w] += r["n_byline"]
        tier[(_tier_key(r["tier"]), w)] += r["n"]
        grp = next((g for g, keys in STAGE_GROUPS if r["stage"] in keys), "기타")
        stage[(grp, w)] += r["n"]

    def cells(keys, src):
        return {(k, w): (_pct(src.get((k, w), 0), tot[w]) if tot.get(w) else None) for k in keys for w in weeks}

    groups = [g for g, _ in STAGE_GROUPS]
    labels = [_wl(w) for w in weeks]
    rate = [_pct(byline[w], tot[w]) if tot.get(w) else 0 for w in weeks]
    body = ('<div class="two">'
            + _fig("공신력 등급 (0 에서 4) · 주별 비율 %",
                   C.heatmap(list(TIER_ORDER), weeks, cells(TIER_ORDER, tier), w=500, unit="%", show_text=True,
                             rowlab=lambda t: TIER_KO[t], collab=_wl))
            + _fig("이적 단계 (루머 → 무산) · 주별 비율 %",
                   C.heatmap(groups, weeks, cells(groups, stage), w=500, unit="%", show_text=True, collab=_wl))
            + _fig("기자 식별률 (바이라인이 잡힌 기사 비율 · %)",
                   C.line_chart(labels, [("식별률", rate)], unit="%", w=640, h=170,
                                annotate=(0, len(labels) - 1) if labels else ()))
            + "</div>")
    ins = []
    if tot:
        w4 = max((w for w in weeks if tot.get(w)), key=lambda w: tier.get(("4", w), 0) / tot[w])
        ins.append((f"등급 4 비중이 가장 높은 주는 {_wl(w4)} ({_pct(tier.get(('4', w4), 0), tot[w4])}%) 다.", []))
        rs = [r for w, r in zip(weeks, rate) if tot.get(w)]
        ins.append((f"기자 식별률은 {min(rs)}% 에서 {max(rs)}% 사이다.", []))
    return _section("sec-credibility-mix-stage-mix", title, sub, q, body, ins)


def _freshness(fresh_rows, sources):
    """절과 함께 최신 회차의 stale 수를 돌려준다 (타일 · SLO-5 가 같은 값을 쓴다)."""
    title, sub = "Source Freshness", "SLO-5 · 임계 대비 경과"
    q = "소스마다 마지막 수집이 임계 시간의 어디까지 왔는지 미터로 본다. 미터가 다 차면 수집이 끊겼다."
    latest_run = fresh_rows[-1]["run_id"] if fresh_rows else None
    latest = {r["source_id"]: r for r in fresh_rows if r["run_id"] == latest_run}
    history = defaultdict(list)
    for r in fresh_rows:                              # 부재 회차 없음 = 진짜 결측
        if r["age_hours"] is not None:
            history[r["source_id"]].append(float(r["age_hours"]))

    def ratio(r):
        return (r["age_hours"] or 0) / (r["threshold_hours"] or 1)

    rows = []
    for sid, r in sorted(latest.items(), key=lambda kv: -ratio(kv[1])):
        disp = C.E(_display(sources, sid))
        if r["age_hours"] is None:
            rows.append(f'<tr><td>{disp}</td><td>이력 없음</td><td>— / {r["threshold_hours"]:.0f}h</td>'
                        f'<td></td><td></td><td><span class="pill">이력 없음</span></td></tr>')
            continue
        pill = '<span class="pill bad">✕ 초과</span>' if r["stale"] else '<span class="pill ok">✓ 신선</span>'
        rows.append(f'<tr><td>{disp}</td><td>{r["last_fetched_at"]:%m-%d %H:%M}</td>'
                    f'<td>{r["age_hours"]:.1f}h / {r["threshold_hours"]:.0f}h</td>'
                    f'<td>{C.meter(r["age_hours"], r["threshold_hours"])}</td>'
                    f'<td>{C.sparkline(history[sid], w=84, h=18)}</td><td>{pill}</td></tr>')
    body = (('<table class="fresh"><thead><tr><th>소스</th><th>마지막 수집</th><th>경과 / 임계</th>'
             '<th>임계 대비</th><th>최근 12회</th><th>상태</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table>") if rows else '<p class="q">이력 없음.</p>')
    ins = []
    thr = [r["threshold_hours"] for r in latest.values()]
    if thr:
        ins.append((f"임계는 소스마다 다르다 ({min(thr):.0f}h 에서 {max(thr):.0f}h).", []))
    stale = [_display(sources, s) for s, r in latest.items() if r["stale"]]
    if stale:
        ins.append((f"임계를 넘은 소스는 {' · '.join(stale)} 다.", []))
    stale_count = sum(1 for r in latest.values() if r["stale"]) if latest else None
    return _section("sec-source-freshness", title, sub, q, body, ins), stale_count


def _review(high, unmatched):
    title, sub = "확인 대상", "재작성 잔존율 · 선수 추출 누락"
    q = ("사람이 볼 두 표다. "
         "재작성 잔존율이 임계를 넘은 기사는 원문 문장이 그대로 남았을 수 있다. "
         "영입 단계는 있는데 귀속 선수가 0명인 기사는 어느 선수 페이지에도 실리지 않아 재추출 대상이다.")
    ht = (('<table class="fresh"><thead><tr><th>기사</th><th>언론사</th><th class="num">잔존율</th></tr></thead><tbody>'
           + "".join(f'<tr><td><a class="alink" href="article/{r["content_hash"]}.html">{r["content_hash"][:8]}</a></td>'
                     f'<td>{C.E(r["outlet"] or "—")}</td><td class="num">{r["retention"]:.2f}</td></tr>' for r in high)
           + "</tbody></table>") if high else '<p class="q">임계값 초과 없음.</p>')
    ut = (('<table class="fresh"><thead><tr><th>날짜</th><th>소스</th><th>제목</th></tr></thead><tbody>'
           + "".join(f'<tr><td>{C.E(r["date"])}</td><td>{C.E(r["source"])}</td><td>{C.E(r["title"])}</td></tr>'
                     for r in unmatched)
           + "</tbody></table>") if unmatched else '<p class="q">없음.</p>')
    body = _two(_fig(f"재작성 잔존율 확인 대상 ({len(high)}건)", ht), _fig(f"선수 추출 누락 ({len(unmatched)}건)", ut))
    return _section("sec-review-tables", title, sub, q, body, [])


# --- 조립 ---------------------------------------------------------------------

def _overview(articles_total: int, span_weeks: int, span_days: int):
    return [
        ("데이터 원천", "MariaDB (silver) 의 표 셋과 회차 끝 dbt 게이트의 테스트 결과.",
         [("pipeline_runs", "회차마다 한 행 · 신규 · 중복 · 에러 · 소요 시간 · 소스별 건수."),
          ("source_freshness", "회차 × 소스의 마지막 수집 시각과 임계."),
          ("articles", f"기사 {C.fmt(articles_total)}건 · 등급 · 이적 단계 · 발행 시각."),
          ("dbt 게이트", "unique · not_null 테스트 결과 (SLO-3 · 4).")]),
        ("기간", f"{OPS_EPOCH.isoformat()} 첫 라이브 실행부터 {span_weeks}주 ({span_days}일).", []),
        ("갱신", "3시간마다 회차가 끝날 때 다시 그린다.", []),
        ("시각", "UTC · KST 는 +9시간.", []),
    ]


def build_ops_view(snapshot: dict, sources: dict, anomaly_count: int, now: datetime, *,
                   gate: GateTally | None = None, unmatched=None) -> dict:
    """스냅샷 · 게이트 집계를 화면이 그릴 dict 로. 키가 비어도 절은 전부 그린다."""
    runs_all = snapshot.get("runs_all") or []
    recent = runs_all[-RECENT_RUNS:]
    today = now.date()
    span_days = (today - OPS_EPOCH).days + 1
    span_weeks = span_days // 7
    articles_total = snapshot.get("articles_total") or 0
    fresh_sec, stale_count = _freshness(snapshot.get("freshness") or [], sources)
    slo = _slo_rows(recent, stale_count, anomaly_count, gate, articles_total)
    sections = [
        _slo(slo, gate),
        _volume(runs_all, today, span_weeks),
        _coverage(runs_all, sources, today, span_weeks),
        _throughput(runs_all, today, span_weeks),
        _duration(runs_all, today),
        {"pair": [_latency(snapshot.get("latency") or [], sources),
                  _players(snapshot.get("player_subjects") or [])]},
        _mix(snapshot.get("weekly_mix") or [], today),
        fresh_sec,
        _review(snapshot.get("high_retention") or [], list(unmatched or [])),
    ]
    return {"generated_at": f"{now:%Y-%m-%d %H:%M} UTC",
            "overview": _overview(articles_total, span_weeks, span_days),
            "tiles": _tiles(runs_all, recent, stale_count, span_weeks),
            "slo": slo, "sections": sections, "missing_note": MISSING_NOTE}
```

`behavior_view` 의 밑줄 헬퍼를 가져다 쓴다.
같은 패키지의 두 화면이 같은 절 dict 모양을 내야 매크로 하나로 그릴 수 있고, PR 1 코드를 옮기거나 고치지 않기 위해서다 (수술적 변경).
순환 import 는 없다.
`behavior_view` 는 `render` 를 모듈 수준에서 가져오지만 `render` 는 `ops_view` 를 함수 안에서만 가져온다 (태스크 4).

- [ ] **Step 4: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_ops_view.py -q`
Expected: 16 passed.

기대값이 하나라도 다르면 픽스처의 셈 (주석) 을 먼저 다시 한다.
`charts` 의 툴팁 문자열 형식 (`라벨\n값단위 · 이름`) 은 PR 1 의 `tests/test_charts.py` 가 고정한 것이라 뷰모델이 아니라 기대 문자열이 틀렸을 가능성이 크다.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/serve/ops_view.py tests/test_ops_view.py
git commit -m "feat(serve): 수집 현황 뷰모델 · 절 열과 타일 여섯을 목업 v2.8 대로 (안건 2φ · PR 2)" -m "수집 현황 화면의 뷰모델을 새 모듈에 둔다. render.py 가 2,200줄이라 행동 화면과 같은 이유로 갈랐고, 절 dict 모양은 행동 화면과 같아 공통 매크로 하나로 그린다.

- 타일 여섯 (최근 30회 · 신규 · 중복률 · 성공률 · p50 소요 · 끊긴 소스 · 회차 수)
- 절 열 (SLO 여섯 행 · 캘린더 · 소스 × 주 · 처리량 · 소요 밴드 · 지연 · 선수 축 · 구성 비율 · 신선도 · 확인 대상 두 표)
- SLO-3 · 4 는 게이트 집계 (GateTally) 에서 · 없으면 참고 행
- 테스트 16종 (손 재계산 픽스처)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 3 · 스펙 §3.4 · 목업 v2.8 수집 현황 탭
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

---

### Task 4: 템플릿 `ops.html.j2` · 렌더 연결 · 옛 뷰 코드 삭제

이 태스크는 셋으로 쪼개 커밋한다 (4a 템플릿 · 렌더 · `run.py` · 4b 옛 코드 삭제 · 4c 전체 테스트).
리뷰는 한 번에 받는다.

**Files:**
- Modify: `src/bullet_in/serve/templates/ops.html.j2` (전문 교체)
- Modify: `src/bullet_in/serve/render.py:829-975` (옛 뷰 코드 삭제) · `:2151-2152` (`render_ops`) · `:2183-2191` (`write_ops`)
- Modify: `src/bullet_in/run.py:645-647` (`write_ops` 호출)
- Test: `tests/test_serve_ops.py` (전문 교체)

**Interfaces:**
- Consumes: 태스크 3 의 `build_ops_view` · 태스크 1 의 `gate_tally` · PR 1 의 `_dash.html.j2` · `_dash_macros.html.j2`.
- Produces: `render_ops(view: dict) -> str` · `write_ops(snapshot, sources, out_dir, anomaly_count, now, unmatched=None, gate_path=None) -> None`.
  `render.py` 에서 `TIER_BUCKETS` · `ETC_TIER_LABEL` · `spark_points` · `_kpi` · 옛 `build_ops_view` 가 사라진다.
  다른 곳에서 안 쓴다 (2026-09-05 grep · `render.py` 와 두 테스트 파일 밖에 없다).

#### 4a. 템플릿 · 렌더 · `run.py`

- [ ] **Step 1: 실패하는 테스트**

`tests/test_serve_ops.py` 를 아래로 통째로 바꾼다.
옛 테스트 여덟은 옛 템플릿 (JS 금지 · 표 넷) 을 재던 것이라 같이 사라진다.

```python
"""수집 현황 화면 — 템플릿이 공통 뼈대를 상속하고 게이트 파일을 읽어 그리는지."""
import json
from datetime import datetime

from bullet_in.serve.ops_view import build_ops_view
from bullet_in.serve.render import render_ops, write_ops

NOW = datetime(2026, 9, 5, 0, 10)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}
SNAPSHOT = {"runs_all": [{"run_id": "r1", "started_at": datetime(2026, 9, 4, 0, 0), "duration_sec": 80.0,
                          "fetch_duration_sec": 10.0, "source_counts": {"bbc_sport": 4}, "new_count": 4,
                          "dup_count": 2, "error_count": 0, "success_rate": 1.0}],
            "freshness": [{"run_id": "r1", "checked_at": datetime(2026, 9, 4, 0, 2), "source_id": "bbc_sport",
                           "last_fetched_at": datetime(2026, 9, 3, 22, 0), "age_hours": 2.1,
                           "threshold_hours": 96.0, "stale": 0}],
            "latency": [("bbc_sport", 2.0)], "weekly_mix": [], "player_subjects": [],
            "articles_total": 10, "high_retention": []}
EMPTY = {"runs_all": [], "freshness": [], "latency": [], "weekly_mix": [], "player_subjects": [],
         "articles_total": 0, "high_retention": []}


def _html(snapshot=SNAPSHOT):
    return render_ops(build_ops_view(snapshot, SOURCES, 0, NOW))


def test_수집_현황_탭이_선택되고_행동_지표로_가는_링크가_있다():
    html = _html()
    assert 'href="ops.html" aria-current="page">수집 현황' in html
    assert 'href="behavior.html">행동 지표' in html
    assert "<title>bullet-in 수집 현황</title>" in html


def test_절_열이_id_와_svg_로_렌더된다():
    html = _html()
    assert html.count('class="sec"') == 10
    for id_ in ("sec-slo", "sec-ingestion-volume", "sec-source-freshness", "sec-review-tables"):
        assert f'id="{id_}"' in html
    assert html.count("<svg") >= 10
    assert "2026-09-05 00:10 UTC" in html


def test_검색엔진에_안_실린다():
    # 운영 뷰는 공개 화면에서 링크하지 않고 색인도 막는다 (2026-08-23 공개 준비). 접근 차단이 아니다.
    assert '<meta name="robots" content="noindex,nofollow">' in _html()


def test_툴팁_목차_js_가_공통_뼈대에서_온다():
    html = _html()
    assert "<script" in html and 'id="tip"' in html and 'id="toc"' in html
    assert "app.js" not in html                                   # 사이트 JS 는 안 싣는다 (스펙 §3.3)


def test_write_ops_는_게이트_파일을_읽어_slo_3_4_를_채운다(tmp_path):
    gate = tmp_path / "run_results.json"
    gate.write_text(json.dumps({"metadata": {"generated_at": "2026-09-04T21:03:00Z"}, "results": [
        {"unique_id": "test.bullet_in.unique_stg_articles_url.a", "status": "pass", "failures": 0},
        {"unique_id": "test.bullet_in.unique_stg_articles_content_hash.b", "status": "pass", "failures": 0},
        {"unique_id": "test.bullet_in.not_null_stg_articles_url.c", "status": "pass", "failures": 0}]}))
    write_ops(SNAPSHOT, SOURCES, tmp_path, anomaly_count=0, now=NOW, gate_path=gate)
    html = (tmp_path / "ops.html").read_text(encoding="utf-8")
    assert "dbt unique 테스트 2종 통과 · 게이트 09-04 21:03 UTC" in html
    assert "dbt not_null 테스트 1종 통과 · 같은 게이트" in html


def test_write_ops_는_게이트_파일이_없어도_그린다(tmp_path):
    write_ops(SNAPSHOT, SOURCES, tmp_path, anomaly_count=0, now=NOW, gate_path=tmp_path / "missing.json")
    html = (tmp_path / "ops.html").read_text(encoding="utf-8")
    assert "게이트 결과 없음" in html and "bullet-in 수집 현황" in html


def test_빈_스냅샷도_페이지가_나온다():
    html = _html(EMPTY)
    assert html.count('class="sec"') == 10 and "회차 이력이 아직 없다" in html
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --project . --extra dev pytest tests/test_serve_ops.py -q`
Expected: 7 FAIL (`render_ops() missing 1 required positional argument` 또는 옛 템플릿의 `view.kpi` 오류).

- [ ] **Step 3: 템플릿**

`src/bullet_in/serve/templates/ops.html.j2` 를 아래로 통째로 바꾼다.

```jinja
{#- 수집 현황 화면 — 뷰모델 (serve/ops_view.build_ops_view) 만 읽는다.
    절 순서 · id 는 목업 v2.8 그대로이고 마지막 절은 기존 두 표 (재작성 잔존율 · 선수 추출 누락) 다.
    시각은 UTC (스펙 2026-09-05 §3.4 · 목업 「시각」 항목). -#}
{% extends "_dash.html.j2" %}
{% import "_dash_macros.html.j2" as dash with context %}
{% block title %}bullet-in 수집 현황{% endblock %}
{% block page %}ops{% endblock %}
{% block meta %}{{ view.generated_at }} 생성 · 인라인 SVG · 시각은 UTC{% endblock %}
{% block content %}
<div class="ov">
{% for lab, txt, subs in view.overview %}
  <div class="ov-item"><div class="ov-lab">{{ lab }}</div><div class="ov-txt">{{ txt }}</div>
  {% if subs %}<ul class="ov-sub">{% for l, x in subs %}<li><b>{{ l }}</b>: {{ x }}</li>{% endfor %}</ul>{% endif %}</div>
{% endfor %}
</div>
{% if view.tiles %}
<div class="tiles">
{% for t in view.tiles %}
  <div class="tile"><div class="tl">{{ t.label }}</div><div class="tv">{{ t.value }}</div><div class="ts">{{ t.sub }}</div>{{ t.spark }}</div>
{% endfor %}
</div>
{% else %}
<p class="missing">회차 이력이 아직 없다.</p>
{% endif %}
{% for item in view.sections %}
{% if item.pair %}<div class="two-sec">{% for s in item.pair %}{{ dash.section(s) }}{% endfor %}</div>
{% else %}{{ dash.section(item) }}{% endif %}
{% endfor %}
{% endblock %}
```

`_dash.html.j2` 의 `<style>` 은 이미 `{% raw %}` 로 감싸 있다 (PR 1 정정 · `{#` 함정).
이 파일에는 CSS 가 없다.

- [ ] **Step 4: `render.py` 의 `render_ops` · `write_ops`**

`render_ops` (2151행) 를 아래로 바꾼다.

```python
def render_ops(view: dict) -> str:
    """수집 현황 화면. 뷰모델은 serve/ops_view 가 만들고 여기서는 템플릿만 부른다."""
    return _env().get_template("ops.html.j2").render(view=view, missing_note=view["missing_note"])
```

`write_ops` (2183행) 를 아래로 바꾼다.

```python
def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime,
              unmatched: list[dict] | None = None,
              gate_path: str | Path | None = None) -> None:
    """수집 현황 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임.

    gate_path 는 직전 회차 게이트의 `dbt/target/run_results.json` 이다 — 회차의 gate
    태스크가 publish 뒤에 돌아 이번 회차 것은 아직 없다 (스펙 2026-09-05 §2). 없으면
    SLO-3 · 4 가 「게이트 결과 없음」 으로 그려진다.
    """
    from bullet_in.dbt_gate import gate_tally
    from bullet_in.serve.ops_view import build_ops_view
    gate = gate_tally(Path(gate_path)) if gate_path else None
    view = build_ops_view(snapshot, sources, anomaly_count, now, gate=gate, unmatched=unmatched)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view), encoding="utf-8")
```

함수 안 import 는 `render_behavior` 와 같은 이유다.
`ops_view` 가 `behavior_view` 를, `behavior_view` 가 `render` 를 모듈 수준에서 가져오므로 `render` 쪽이 늦게 가져와야 순환이 안 생긴다.

- [ ] **Step 5: `run.py`**

645행에서 647행을 아래로 바꾼다.

```python
        write_ops(mart.ops_snapshot(), sources, "site",
                  anomaly_count=len(anomalies), now=mart.db_now(),
                  unmatched=unmatched_articles(rows, pstore.linked_hashes()),
                  gate_path=Path("dbt") / "target" / "run_results.json")
```

`Path` 는 `run.py` 6행에 이미 있다.
`gate()` 가 같은 경로 (`Path("dbt")` 아래 `target/run_results.json`) 에 쓴다.

- [ ] **Step 6: 통과 확인**

Run: `uv run --project . --extra dev pytest tests/test_serve_ops.py tests/test_ops_view.py -q`
Expected: 23 passed.

- [ ] **Step 7: 커밋 4a**

```bash
git add src/bullet_in/serve/templates/ops.html.j2 src/bullet_in/serve/render.py src/bullet_in/run.py tests/test_serve_ops.py
git commit -m "feat(dashboard): 수집 현황 화면을 공통 뼈대 위에 · 게이트 결과 파일로 SLO-3 · 4 (안건 2φ · PR 2)" -m "수집 현황 템플릿이 행동 지표 화면과 같은 뼈대 (_dash.html.j2) 를 상속해 상단 · 탭 · 목차 · 툴팁을 공유한다. publish 가 직전 회차 게이트의 run_results.json 경로를 넘겨 SLO-3 · 4 를 채운다.

- ops.html.j2 재작성 · {% block page %}ops{% endblock %}
- render_ops(view) · write_ops(gate_path=) · run.py 가 dbt/target/run_results.json 을 넘김
- 테스트 7종 (탭 · 절 열 · noindex · JS · 게이트 파일 유무 · 빈 스냅샷)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 4 · 스펙 §3.3 · §3.4
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

#### 4b. 옛 뷰 코드 삭제

- [ ] **Step 1: 지운다**

`src/bullet_in/serve/render.py` 에서 아래를 지운다.
829행 `# ---- 운영 뷰 (ops.html) 뷰모델 ----` 부터 옛 `build_ops_view` 의 `return` 끝 (`"high_retention_count": len(high)}` · 975행 부근) 까지.
그 안에 `TIER_BUCKETS` · `ETC_TIER_LABEL` · `spark_points` · `_kpi` · 옛 `build_ops_view` 가 있다.
그 아래 `TRANSFER_WINDOWS` 주석부터는 그대로 둔다.

```bash
grep -n "TIER_BUCKETS\|ETC_TIER_LABEL\|spark_points\|_kpi\|def build_ops_view" src/bullet_in/serve/render.py
```

Expected: 아무것도 안 나온다.

- [ ] **Step 2: 고아 import 확인**

```bash
uv run --project . --extra dev python -m pyflakes src/bullet_in/serve/render.py 2>/dev/null || uv run --project . --extra dev python -c "import bullet_in.serve.render"
```

`pyflakes` 가 없으면 import 만 확인한다.
지운 코드가 쓰던 이름 가운데 다른 곳이 안 쓰는 것 (있다면) 만 import 에서 뺀다.
지운 블록은 `datetime` 과 표준 내장만 썼으므로 보통 뺄 것이 없다.

- [ ] **Step 3: 커밋 4b**

```bash
git add src/bullet_in/serve/render.py
git commit -m "refactor(serve): 옛 수집 현황 뷰 코드 삭제 (안건 2φ · PR 2)" -m "뷰모델이 serve/ops_view 로 옮겨 가 render.py 의 옛 코드 (TIER_BUCKETS · spark_points · _kpi · 옛 build_ops_view) 를 아무도 안 쓴다.

- render.py 829행에서 975행 삭제 (약 150줄)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 4b
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

#### 4c. 전체 테스트와 렌더 한 번

- [ ] **Step 1: 전체 테스트**

```bash
cd /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard-pr2
uv run --project . --extra dev pytest -q 2>&1 | tail -3
```

Expected: `--co` 1,769 · 실행 1,768 passed 안팎 (1,754 − 옛 `test_ops_view` 7 − 옛 `test_serve_ops` 8 − 옛 통합 6 + 새 16 + 7 + 9 + 게이트 3). 2026-09-05 에 계획서 코드를 그대로 꺼내 돌린 실측이다.
skip 은 Playwright · Airflow 것뿐이어야 한다.
수집 수가 1,754 와 같으면 셸이 워크트리 밖이다 (규율 §3).

- [ ] **Step 2: 렌더를 실제로 한 번 돌린다**

계획서 코드는 렌더를 한 번 돌려야 잡히는 결함이 있다 (트러블슈팅 `2026-09-05-what-only-showed-up-when-the-plan-was-run.md`).
로컬 MariaDB 는 기사 · 회차가 거의 없지만 템플릿 · 매크로 · 뷰모델의 조립은 검증된다.

```bash
set -a; source .env; set +a
uv run --project . python - <<'EOF'
import os
from pathlib import Path
from sqlalchemy import create_engine
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore
from bullet_in.serve.render import write_ops
mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
write_ops(mart.ops_snapshot(), load_sources("config/sources.yaml"), "/tmp/ops-local", anomaly_count=0,
          now=mart.db_now(), unmatched=[], gate_path=Path("dbt/target/run_results.json"))
html = Path("/tmp/ops-local/ops.html").read_text()
print("sec", html.count('class="sec"'), "svg", html.count("<svg"), "bytes", len(html))
EOF
```

Expected: `sec 10` · 예외 없음.
`/tmp/ops-local/ops.html` 을 브라우저로 열어 절 열이 보이고 탭 「수집 현황」 이 선택돼 있는지 눈으로 본다.

---

### Task 5: README §4 에 SLO 번호 여섯

**Files:**
- Modify: `README.md:90-102` (§4 표)

- [ ] **Step 1: 표를 바꾼다**

지금 표 (다섯 행 · 번호 없음) 를 아래로 바꾼다.
실측 열의 낡은 값 (07-19 · 358건) 은 그대로 둔다 (안건 `2χ` 의 몫 · 스펙 §3.5).
SLO-2 를 둘째로 올리고 SLO-5 행을 새로 넣는다.

```markdown
## 4. 정량 지표 (SLO)

> 목표치와 측정 방법. 병렬화 실측 절차 · 로그는 [SLO-1 벤치마크 런북](docs/runbook/2026-07-14-slo1-benchmark.md), SLO-2 · 3 · 4 · 6 은 [SLO 측정 런북](docs/runbook/2026-07-19-slo-measurement.md). 번호는 수집 현황 화면 (`ops.html`) 의 SLO 표와 같다.

| 번호 | 지표 | 목표 | 측정 방법 | 실측 |
|---|---|---|---|---|
| SLO-1 | 병렬화 수집 시간 단축 | 순차 대비 ≥ 55%↓ (실측 기반 재조정¹) | `metrics.benchmark()` (concurrency=1 vs N 벤치마크) | 56.5%↓ (2026-07-15, 3회 중앙값) |
| SLO-2 | 일일 수집 성공률 | ≥ 99% | `pipeline_runs.success_rate` (재시도 · 소스 격리 포함) | 99.3% (2026-07-19, 17회 평균) |
| SLO-3 | 중복 적재율 | 0% | content_hash UNIQUE + dbt `unique` 테스트 | 0% (2026-07-19, mart 358건 dbt PASS + SQL 교차) |
| SLO-4 | 필수 필드 완전성 | ≥ 99% | dbt `not_null` 테스트 통과율 | 100% (2026-07-19, mart 358건) |
| SLO-5 | 소스 신선도 | 끊긴 소스 0 | `source_freshness` 워터마크 · 소스별 임계 초과 여부 (회차마다) | 회차마다 수집 현황 화면 SLO 표에 |
| SLO-6 | 수집량 이상 감지 | 전일 대비 ±2σ 알림 | `quality.volume_anomaly` | 가동 (실발송 검증 2026-07-13) |
```

각주 `¹` 줄은 그대로 둔다.

- [ ] **Step 2: 다른 곳의 SLO 언급과 어긋나지 않는지**

```bash
grep -n "SLO-[0-9]" README.md
```

Expected: 63행의 「신선도는 자체 워터마크 감시 (SLO-5)」 가 새 표의 SLO-5 와 맞는다.
다른 번호가 나오면 새 표와 대조한다.

- [ ] **Step 3: 커밋**

```bash
git add README.md
git commit -m "docs(readme): §4 SLO 표에 번호 여섯과 소스 신선도 행 (안건 2φ · PR 2)" -m "수집 현황 화면의 SLO 표가 SLO-1 에서 6 을 쓰는데 README 표에는 번호가 없고 신선도 행도 없었다. 번호를 붙이고 SLO-5 행을 더한다. 실측 열의 낡은 값은 README 개편 (안건 2χ) 에서 갱신한다.

- 번호 열 신설 · SLO-2 를 둘째로
- SLO-5 소스 신선도 행 (source_freshness 워터마크 · 임계 초과 소스 0)

Refs: 안건 2φ · docs/superpowers/plans/2026-09-05-dashboard-ops-screen.md 태스크 5 · 스펙 §3.5
Co-Authored-By: Claude Fable 5.1 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01TepUKdcHxnEbxiCMAJqgVK"
```

---

### Task 6: VM 재현 · PR · 배포 뒤 확인

**Files:**
- 없음 (검증 · PR 본문 · 메모리)

- [ ] **Step 1: VM 임시 클론에서 운영 데이터로 한 번 그린다**

절차는 런북 `docs/runbook/2026-09-05-reproducing-a-baseline-from-a-pr-branch-on-the-vm.md` 그대로다.
다른 점은 `build_gold` 대신 `write_ops` 를 부르고 `run_results.json` 을 주 체크아웃에서 복사해 온다는 것이다.
읽기만 하므로 운영 상태를 안 바꾼다.
회차 정각 (KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21시) 앞뒤 5분은 피한다.

```bash
git -C /Users/aryijq/Documents/01_DE_project/bullet-in/.claude/worktrees/dashboard-pr2 push -u origin dashboard-pr2
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 '
  set -e
  rm -rf /tmp/bi-dash
  git clone -q --depth 1 --branch dashboard-pr2 https://github.com/benidjor/bullet-in /tmp/bi-dash
  cd /tmp/bi-dash && cp ~/bullet-in/.env . && set -a && . ./.env && set +a
  cp ~/bullet-in/dbt/target/run_results.json /tmp/bi-dash/run_results.json
  ~/.local/bin/uv run --python 3.11 --project . python - <<"EOF"
import os, re
from pathlib import Path
from sqlalchemy import create_engine
from bullet_in.score import load_sources
from bullet_in.storage.mariadb import MartStore
from bullet_in.serve.render import write_ops
mart = MartStore(create_engine(os.environ["MARIADB_URL"]))
write_ops(mart.ops_snapshot(), load_sources("config/sources.yaml"), "site", anomaly_count=0,
          now=mart.db_now(), unmatched=[], gate_path=Path("run_results.json"))
html = Path("site/ops.html").read_text()
print("sec", html.count("class=\"sec\""), "svg", html.count("<svg"), "bytes", len(html))
print("tiles", re.findall(r"class=\"tv\">([^<]*)<", html))
for m in re.findall(r"<td>(SLO-\d)</td><td>[^<]*</td><td>[^<]*</td><td class=\"num\">([^<]*)</td>", html):
    print(*m)
EOF
' 2>&1 | tee /private/tmp/claude-501/-Users-aryijq-Documents-01-DE-project-bullet-in/cef7d0b0-d0da-485c-b842-86e629da9c4d/scratchpad/vm-ops-reproduction.txt
```

Expected:

- `sec 10` · `svg` 30 이상 · 예외 없음.
- 타일 여섯이 목업 (2026-09-04 19:24 KST) 과 같은 자릿수다. 목업 값 = 신규 1 · Dedup 98% · Success 99.2% · p50 127초 · Stale 0 · Runs 384 (에러 20). 회차가 더 쌓였으므로 Runs 는 390 안팎이다.
- SLO-1 `56.5%↓` · SLO-2 99% 안팎 · SLO-3 `0%` · SLO-4 `100.0%` · SLO-5 `0` · SLO-6 `0` (여기서는 `anomaly_count=0` 을 넘겼다).

값이 자릿수부터 다르면 표가 아니라 스냅샷 SQL 과 런북 §8 이 어디서 갈리는지 먼저 찾는다.
받은 파일 `site/ops.html` 을 `scp` 로 내려 브라우저로 한 번 본다.

```bash
scp -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17:/tmp/bi-dash/site/ops.html /private/tmp/claude-501/-Users-aryijq-Documents-01-DE-project-bullet-in/cef7d0b0-d0da-485c-b842-86e629da9c4d/scratchpad/ops-vm.html
```

- [ ] **Step 2: 임시 클론 정리**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'rm -rf /tmp/bi-dash'
```

- [ ] **Step 3: PR 본문**

7절 구조 (컨벤션 §2) · `--body-file` · Claude 서명 없음.
§4 검증에 VM 재현 출력 (타일 · SLO 여섯 줄) 과 전체 테스트 수를 붙인다.
§5 에 이 계획서의 「판정」 표 가운데 ★ 항목 (성공률 미터) 을 사용자 결정으로 적는다.
게시 전에 둘을 거친다.

```bash
python3 .claude/tools/check-pr-format.py --body <본문 파일> --title "feat(dashboard): 수집 현황 화면을 목업 v2.8 대로 — 스냅샷 확장 · 뷰모델 · SLO 여섯 (안건 2φ · PR 2)"
```

humanize-korean fast 1회 (명사형 불릿 · 수치 · 경로 · 코드 블록 · 표는 변경 금지로 명시).

```bash
gh pr create --base main --head dashboard-pr2 --title "<위 제목>" --body-file <본문 파일>
```

- [ ] **Step 4: 머지 뒤 (사용자가 머지한다)**

- 다음 회차의 `advance` 가 코드를 받는다. `publish` 가 바로 새 화면을 그린다. 빈 구간이 없다 (스펙 §4). SLO-3 · 4 는 직전 회차 게이트 값이다.
- 확인: `curl -sL https://bullet-in.pages.dev/ops.html | grep -c 'class="sec"'` → `10` · `grep -c "<svg"` → 30 이상 · `curl -sL https://bullet-in.pages.dev/behavior.html | grep -c 'class="sec"'` → `9` (행동 화면이 안 깨졌는지).
- 워크트리 · 로컬 브랜치 · 원격 브랜치 · `git worktree prune` 넷을 지운다 (규율 §2 · 저장소 루트에서).
- 메모리: `dashboard-redesign-track-2026-09-04` 에 PR 번호 · 재현 결과 · 판정 표의 결정을 적고, 안건 표 2φ 행을 ✅ 로 (열린 안건 27 → 26) 고친다. 색인 머리말의 수를 함께 고친다.
- 그 뒤 순서 = 2χ README (이 화면 캡처 포함) → 런북 §6.5 첫 24시간 PR → v9 슬라이드.

---

## 자체 검토 (2026-09-05)

- 스펙 §3.4 `ops_snapshot` 확장 (회차 전체 · 지연 · 주별 구성 · 선수 상위 10) → 태스크 2. 「신선도 이력 3일」 은 판정 4 로 안 한다.
- 스펙 §3.4 소스 × 주는 `source_counts` 로 · 선수 축은 `subject` · `squad` `external` → 태스크 2 의 SQL · 태스크 3 의 `_coverage` · `_players`.
- 스펙 §3.4 뷰모델 여섯 (캘린더 · 소스 × 주 · 처리량 · 소요 밴드 · 지연 · 주별 구성) → 태스크 3 의 `_volume` · `_coverage` · `_throughput` · `_duration` · `_latency` · `_mix`.
- 스펙 §3.4 SLO-3 · 4 는 `run_results.json` 에서 · 없으면 `info` · 게이트 시각 병기 → 태스크 1 · 3 (`_slo_rows`) · 4 (`gate_path`).
- 스펙 §3.4 SLO-1 고정값 → `SLO1_VALUE` · `SLO1_HOW`.
- 스펙 §3.5 README §4 번호 여섯 · SLO-5 행 · ※ 제거 → 태스크 5 · 판정 8.
- 스펙 §3.3 `ops.html.j2` 가 `_dash.html.j2` 상속 · `{% block page %}` → 태스크 4.
- 스펙 §4 빈 구간 없음 → `build_ops_view` 가 빈 키에서도 절 열을 그린다 · 테스트 「빈_스냅샷」.
- 스펙 §5 `tests/test_ops_view.py` · `test_serve_ops.py` · 배포 뒤 `curl` 로 절 수 → 태스크 3 · 4 · 6.
- 목업의 절 아홉 + 「지금대로 아래에 둔다」 두 표 → 절 열 (판정 7).
- 타입 대조: `GateTally` 필드 이름 (`unique_total` · `unique_failed` · `not_null_total` · `not_null_failed` · `generated_at`) 이 태스크 1 · 3 · 4 에서 같다. 스냅샷 키 일곱이 태스크 2 · 3 · 4 의 픽스처에서 같다. `write_ops` 의 `gate_path` 키워드가 태스크 4 · 6 에서 같다.
- 자리 표시자 없음 (TBD · 나중에 · 적절히 없음).
