# SLO-1 병렬화 실측 · 기록 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 순차 vs 병렬 fetch speedup 을 1회성 벤치마크로 실측해 README SLO 표를 채우고, 매 런 fetch 구간을 `pipeline_runs.fetch_duration_sec` 으로 상시 기록한다.

**Architecture:** `metrics.benchmark()` 를 어댑터별 순차 계측 + 병렬 1세트 구조로 재설계하고 전용 진입점 `python -m bullet_in.benchmark` 를 추가한다.
run.py 는 fetch 구간만 별도 계측해 pipeline_runs 에 기록하고, ops 뷰와 dbt `slo_rollup` 양쪽에 fetch duration 행을 추가한다.
PR #39 이월 Minor 3건 ( started_at UTC 고정 · ops spec §5.3 정밀화 · stale 배지 스모크 ) 을 동반한다.

**Tech Stack:** Python 3.11 · asyncio · SQLAlchemy + PyMySQL · Jinja2 · dbt-duckdb ( MariaDB attach ) · pytest.

**Spec:** `docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md`

## Global Constraints

- 성능 개선 없음 — 측정 · 기록 트랙 ( spec §2 비목표 ).
- 벤치마크 결과의 DB 적재 없음, 스케줄링 없음 ( 수동 실행 ).
- 문서 ( docs/ 아래 .md ) 는 컨벤션 §2.2 서식 — PostToolUse 훅이 자동 검사.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + Refs + 트레일러.
  트레일러는 실제 작업 모델 병기 — 설계 = Fable 5, 구현 = 태스크별 배정 모델.
- 테스트 픽스처 기대값은 손으로 재계산해 검증 ( `docs/troubleshooting/2026-07-14-plan-artifact-defect-propagation.md` 예방 계약 ).
  기대값과 코드 계약이 충돌하면 구현 우회 금지 — 중단하고 질문.
- 통합 테스트는 DB 없으면 skip ( `tests/integration/conftest.py` 기존 패턴 ).

## 태스크별 모델 배정 ( SDD )

| Task | 성격 | 구현 모델 |
|---|---|---|
| 1 · 2 · 4 · 5 | 국소 코드 | Haiku 4.5 |
| 3 | 통합 ( run.py 흐름 + DB + 시계 ) | Sonnet 5 |
| 6 · 7 | 한국어 문서 | Sonnet 5 |
| 8 | 라이브 검증 · README | 메인 세션 ( Fable 5 ) |

태스크 리뷰 = Sonnet 5, 최종 whole-branch 리뷰 = Fable 5.

---

### Task 1: `metrics.benchmark()` 재설계 — 어댑터별 순차 계측 + 병렬 1세트

**Files:**
- Modify: `src/bullet_in/metrics.py` ( 현재 15줄 전체 교체 수준 )
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `bullet_in.ingest.gather_all(adapters, concurrency) -> tuple[list[RawItem], dict[str, str]]` ( 기존 ).
- Produces: `async def benchmark(adapters, *, gap_sec: float = 60) -> dict` — 반환 키 `sequential_sec` · `parallel_sec` · `speedup_pct` ( 무효 시 None ) · `per_source` · `errors_seq` · `errors_par`.
  Task 2 진입점이 이 시그니처를 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_metrics.py` 를 아래로 교체 ( 기존 `test_speedup_pct_computes_reduction` 유지 ):

```python
import asyncio
import pytest
from bullet_in.metrics import benchmark, speedup_pct


class FakeAdapter:
    """asyncio.sleep 기반 페이크 — 지연·실패를 조절해 benchmark 계약을 검증."""
    def __init__(self, source_id: str, delay: float, fail: bool = False):
        self.source_id = source_id
        self._delay = delay
        self._fail = fail

    async def fetch(self):
        await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return []


def test_speedup_pct_computes_reduction():
    assert speedup_pct(sequential_sec=10.0, parallel_sec=3.0) == 70.0


def test_benchmark_sequential_sums_and_parallel_maxes():
    adapters = [FakeAdapter("a", 0.1), FakeAdapter("b", 0.1), FakeAdapter("c", 0.1)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    # 순차 = Σ지연 ≈ 0.3s, 병렬 = max지연 ≈ 0.1s — 여유 있는 경계로 flaky 방지
    assert r["sequential_sec"] >= 0.28
    assert r["parallel_sec"] < r["sequential_sec"]
    assert r["parallel_sec"] < 0.25
    assert r["speedup_pct"] == pytest.approx(
        (1 - r["parallel_sec"] / r["sequential_sec"]) * 100, abs=0.11)


def test_benchmark_per_source_breakdown():
    adapters = [FakeAdapter("fast", 0.01), FakeAdapter("slow", 0.1)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    assert set(r["per_source"]) == {"fast", "slow"}
    assert r["per_source"]["slow"] > r["per_source"]["fast"]


def test_benchmark_isolates_error_sources_per_pass():
    adapters = [FakeAdapter("ok", 0.01), FakeAdapter("bad", 0.01, fail=True)]
    r = asyncio.run(benchmark(adapters, gap_sec=0))
    assert "bad" in r["errors_seq"] and "bad" in r["errors_par"]
    assert "ok" not in r["errors_seq"] and "ok" not in r["errors_par"]


def test_benchmark_empty_adapters_marks_invalid():
    r = asyncio.run(benchmark([], gap_sec=0))
    assert r["sequential_sec"] == 0
    assert r["speedup_pct"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: FAIL — `ImportError: cannot import name 'benchmark'` 는 아니고 ( benchmark 존재 ), `TypeError: benchmark() got an unexpected keyword argument 'gap_sec'` 계열로 신규 4개 실패, 기존 1개 통과.

- [ ] **Step 3: 구현**

`src/bullet_in/metrics.py` 전체를 아래로 교체:

```python
from __future__ import annotations
import asyncio, time
from bullet_in.ingest import gather_all

def speedup_pct(sequential_sec: float, parallel_sec: float) -> float:
    return round((1 - parallel_sec / sequential_sec) * 100, 1)

async def benchmark(adapters, *, gap_sec: float = 60) -> dict:
    """순차(어댑터별 계측) → gap 대기 → 병렬 1세트 벤치마크 (SLO-1, spec §4.1).

    순차 패스를 어댑터별로 나눠 재면 소스별 분해(per_source)가 나와
    최장 소스 지배 여부를 판단할 수 있다. 두 패스의 에러 소스가 다르면
    비교 무효 — 호출자가 errors_seq/errors_par 로 판정한다."""
    per_source: dict[str, float] = {}
    errors_seq: dict[str, str] = {}
    for a in adapters:
        t = time.perf_counter()
        _, errs = await gather_all([a], concurrency=1)
        per_source[a.source_id] = round(time.perf_counter() - t, 2)
        errors_seq.update(errs)
    seq = round(sum(per_source.values()), 2)
    if gap_sec:
        await asyncio.sleep(gap_sec)         # 소스 연속 타격 완화
    t = time.perf_counter()
    _, errors_par = await gather_all(adapters, concurrency=len(adapters) or 1)
    par = round(time.perf_counter() - t, 2)
    return {"sequential_sec": seq, "parallel_sec": par,
            "speedup_pct": speedup_pct(seq, par) if seq > 0 else None,
            "per_source": per_source,
            "errors_seq": errors_seq, "errors_par": errors_par}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_metrics.py -v`
Expected: 5 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/metrics.py tests/test_metrics.py
git commit -m "$(cat <<'EOF'
feat(metrics): benchmark를 어댑터별 순차 계측 + 병렬 1세트로 재설계

미호출 상태였던 benchmark()를 SLO-1 실측에 쓸 수 있게 재설계함. 순차
패스를 어댑터별로 계측해 최장 소스 지배 판단 근거(per_source)를 확보.

- 순차 = 어댑터별 gather_all([a], concurrency=1) 루프 · 합산
- gap_sec 대기 (기본 60s, 테스트 0) 후 병렬 = gather_all(concurrency=N)
- 반환에 per_source · errors_seq · errors_par 추가 (에러 불일치 = 비교 무효)
- sequential_sec = 0 이면 speedup_pct = None (0-나눗셈 가드)

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§4.1)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 벤치마크 진입점 `python -m bullet_in.benchmark`

**Files:**
- Create: `src/bullet_in/benchmark.py`
- Test: `tests/test_benchmark_cli.py`

**Interfaces:**
- Consumes: `metrics.benchmark(adapters, *, gap_sec)` ( Task 1 ) · `adapters.factory.build_adapters(cfg: dict) -> list` ( 기존, enabled 필터 포함 ).
- Produces: CLI 진입점 — Task 7 런북 · Task 8 라이브 검증이 `uv run python -m bullet_in.benchmark` 로 실행.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_benchmark_cli.py` 신규:

```python
import subprocess, sys


def test_benchmark_module_help_exits_zero():
    # 진입점 스모크: 임포트 + argparse 배선만 검증 (라이브 fetch 없음)
    proc = subprocess.run(
        [sys.executable, "-m", "bullet_in.benchmark", "--help"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    assert "--gap" in proc.stdout
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_benchmark_cli.py -v`
Expected: FAIL — `No module named bullet_in.benchmark`.

- [ ] **Step 3: 구현**

`src/bullet_in/benchmark.py` 신규:

```python
from __future__ import annotations
import argparse, asyncio, json
from pathlib import Path
import yaml
from bullet_in.adapters.factory import build_adapters
from bullet_in.metrics import benchmark


def main() -> None:
    ap = argparse.ArgumentParser(
        description="SLO-1 순차 vs 병렬 fetch 벤치마크 (DB 미적재, JSON stdout)")
    ap.add_argument("--gap", type=float, default=60.0,
                    help="순차 · 병렬 패스 사이 대기 초 (기본 60)")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    adapters = build_adapters(cfg)
    result = asyncio.run(benchmark(adapters, gap_sec=args.gap))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_benchmark_cli.py -v`
Expected: 1 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/benchmark.py tests/test_benchmark_cli.py
git commit -m "$(cat <<'EOF'
feat(metrics): SLO-1 벤치마크 전용 진입점 추가

README 측정 방법 문구(metrics.benchmark())와 일치하는 실행 경로를 만듦.
run.py와 분리된 전용 모듈이라 파이프라인 코드와 벤치 분기가 섞이지 않음.

- python -m bullet_in.benchmark — config 어댑터 빌드 → benchmark() → JSON stdout
- --gap 옵션 (기본 60s) · DB 미적재 · Gemini 미관여
- --help 스모크 테스트 (임포트 + argparse 배선)

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§4.2)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `fetch_duration_sec` 상시 기록 + started_at UTC 고정 ( 이월 ① )

**Files:**
- Modify: `src/bullet_in/storage/schema.sql` ( pipeline_runs CREATE 27–31행 + 파일 끝 ALTER )
- Modify: `src/bullet_in/run.py` ( 임포트 · 29–31행 계측 · 98–108행 INSERT )
- Test: `tests/integration/test_pipeline_runs_insert.py` ( 신규 )

**Interfaces:**
- Consumes: `MartStore.ensure_schema()` 가 schema.sql 을 멱등 적용 ( 기존 ).
- Produces: `pipeline_runs.fetch_duration_sec FLOAT` 컬럼 ( Task 4 · 5 가 읽음 ) · run.py 모듈 상수 `RUN_INSERT_SQL: str` ( 통합 테스트가 실문장 검증에 사용 ).
  바인딩 파라미터: `:rid :drid :started :dur :fetch :counts :new :dup :err :sr` — `:started` 는 naive UTC datetime.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/integration/test_pipeline_runs_insert.py` 신규:

```python
import json
from datetime import datetime
from sqlalchemy import create_engine, text
from bullet_in.run import RUN_INSERT_SQL
from tests.integration.conftest import TEST_URL


def _params(rid="bench-run", fetch=7.5):
    return {"rid": rid, "drid": "test",
            "started": datetime(2026, 7, 14, 3, 0, 0),
            "dur": 42.0, "fetch": fetch,
            "counts": json.dumps({"bbc_sport": 2}),
            "new": 2, "dup": 0, "err": 0, "sr": 1.0}


def test_insert_records_fetch_duration_and_started_at_roundtrip(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params())
        row = c.execute(text(
            "SELECT started_at, fetch_duration_sec, "
            "TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) AS drift "
            "FROM pipeline_runs WHERE run_id='bench-run'")).mappings().one()
    assert row["fetch_duration_sec"] == 7.5          # FLOAT 정확 표현값
    assert row["started_at"] == datetime(2026, 7, 14, 3, 0, 0)  # 바인딩 왕복
    assert abs(row["drift"]) <= 60                   # finished_at ≈ UTC now


def test_finished_at_stays_utc_under_kst_session(engine):
    # NOW() 회귀면 finished_at 이 +9h(32400s) 어긋난다 — UTC_TIMESTAMP() 검증
    kst = create_engine(TEST_URL,
                        connect_args={"init_command": "SET time_zone = '+09:00'"})
    with kst.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-kst"))
        drift = c.execute(text(
            "SELECT TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) "
            "FROM pipeline_runs WHERE run_id='bench-kst'")).scalar_one()
    kst.dispose()
    assert abs(drift) <= 60
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_pipeline_runs_insert.py -v`
Expected: FAIL — `ImportError: cannot import name 'RUN_INSERT_SQL'` ( DB 없으면 skip — 그 경우 로컬 docker 기동 후 재실행 ).

- [ ] **Step 3: schema.sql 수정**

pipeline_runs CREATE 의 `duration_sec FLOAT,` 뒤에 컬럼 추가:

```sql
CREATE TABLE IF NOT EXISTS pipeline_runs (
  run_id VARCHAR(64) PRIMARY KEY, dag_run_id VARCHAR(128),
  started_at DATETIME, finished_at DATETIME, duration_sec FLOAT,
  fetch_duration_sec FLOAT,
  source_counts JSON, new_count INT, dup_count INT, error_count INT,
  success_rate FLOAT);
```

파일 끝 ( source_freshness CREATE 뒤 ) 에 멱등 마이그레이션 추가:

```sql
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS fetch_duration_sec FLOAT;
```

- [ ] **Step 4: run.py 수정**

임포트에 datetime 추가 ( 2행 ):

```python
import argparse, asyncio, json, logging, os, time, uuid, yaml
from datetime import datetime, timezone
```

`GEMINI_MODEL` 상수 아래에 INSERT 문 상수 추가 ( 통합 테스트가 실문장을 임포트해 검증 ):

```python
# started_at 은 Python UTC 바인딩 · finished_at 은 UTC_TIMESTAMP() — 세션 TZ 무관 (spec §5)
RUN_INSERT_SQL = (
    "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
    "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
    "error_count,success_rate) "
    "VALUES (:rid,:drid,:started,UTC_TIMESTAMP(),:dur,:fetch,:counts,"
    ":new,:dup,:err,:sr)")
```

29–31행 계측 구간 교체 ( `started_epoch = time.time()` 제거 ):

```python
    t0 = time.perf_counter()
    started_at_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    raw, errors = await gather_all(adapters, concurrency=concurrency)
    fetch_sec = round(time.perf_counter() - t0, 2)
```

98–108행 INSERT 블록 교체:

```python
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL),
            {"rid": run_id,
             "drid": os.environ.get("AIRFLOW_CTX_DAG_RUN_ID", "manual"),
             "started": started_at_utc, "dur": summary["elapsed_sec"],
             "fetch": fetch_sec,
             "counts": json.dumps(stats["source_counts"]),
             "new": len(arts), "dup": stats["dup_count"],
             "err": len(errors), "sr": summary["success_rate"]})
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/integration/test_pipeline_runs_insert.py tests/integration/ -v`
Expected: 신규 2개 passed, 기존 통합 테스트 회귀 없음 ( conftest 가 갱신된 schema.sql 을 적용 ).

Run: `uv run pytest -q`
Expected: 전체 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/storage/schema.sql src/bullet_in/run.py tests/integration/test_pipeline_runs_insert.py
git commit -m "$(cat <<'EOF'
feat(run): fetch 구간 상시 계측 + pipeline_runs 기록 시계 UTC 고정

duration_sec은 enrich 비용이 지배해 병렬화 효과가 안 보이므로 fetch
구간만 별도 계측해 기록함. 같은 INSERT를 고치는 김에 PR #39 이월분인
세션 TZ 의존 잠복 가정(FROM_UNIXTIME · NOW())도 제거.

- fetch_duration_sec FLOAT 컬럼 (CREATE + 멱등 ALTER, transfer_stage 선례)
- gather_all 전후 perf_counter → fetch_sec 기록
- started_at = Python UTC 바인딩 · finished_at = UTC_TIMESTAMP()
- RUN_INSERT_SQL 모듈 상수화 — 통합 테스트가 실문장 검증 (KST 세션 회귀 포함)

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§5)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: ops 뷰 연동 — SLO 롤업 fetch 행 + stale 배지 스모크 ( 이월 ③ )

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py` ( ops_snapshot SELECT, 122–126행 )
- Modify: `src/bullet_in/serve/render.py` ( build_ops_view SLO 블록, 180–197행 )
- Test: `tests/test_serve_ops.py` · `tests/integration/test_ops_snapshot.py`

**Interfaces:**
- Consumes: `pipeline_runs.fetch_duration_sec` ( Task 3 ).
- Produces: `ops_snapshot()["runs"][i]["fetch_duration_sec"]` ( float | None ) · SLO 롤업 행 `{"slo_id": "fetch_duration", "definition": "최근 30회 평균 fetch 시간", "value": "Ns" | "—", "status": "info"}`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_serve_ops.py` — `_snapshot()` 의 runs 항목에 `"fetch_duration_sec": 10.0` 추가 ( duration_sec 뒤 ):

```python
    return {"runs": [{"run_id": "r1", "started_at": NOW, "duration_sec": 80.0,
                      "fetch_duration_sec": 10.0,
                      "source_counts": {"bbc_sport": 4}, "new_count": 4,
                      "dup_count": 2, "error_count": 0, "success_rate": 1.0}],
```

파일 끝에 테스트 3개 추가:

```python
def test_build_ops_view_fetch_duration_row():
    view = build_ops_view(_snapshot(), SOURCES, 0, NOW)
    row = next(s for s in view["slo"] if s["slo_id"] == "fetch_duration")
    # 10.0 하나의 평균 = 10.0 → "10s" (손 재계산)
    assert row["value"] == "10s" and row["status"] == "info"
    assert row["definition"] == "최근 30회 평균 fetch 시간"


def test_build_ops_view_fetch_duration_all_null_shows_dash():
    snap = _snapshot()
    snap["runs"][0]["fetch_duration_sec"] = None      # 기존 13회 이력 = NULL 계약
    view = build_ops_view(snap, SOURCES, 0, NOW)
    row = next(s for s in view["slo"] if s["slo_id"] == "fetch_duration")
    assert row["value"] == "—"


def test_render_ops_stale_badge_renders():
    snap = _snapshot()
    snap["freshness"][0]["stale"] = 1                 # PR #39 이월 ③ — 미검증 경로
    html = render_ops(build_ops_view(snap, SOURCES, 0, NOW))
    assert "✕ 초과" in html and "b-stale" in html
```

`tests/integration/test_ops_snapshot.py` — `_seed_runs` 의 rows dict 에 fetch 값 추가 ( "dur" 뒤 ) 와 INSERT 문 컬럼 반영:

```python
    rows = [{"rid": f"run-{i:03d}", "t": base + timedelta(hours=6 * i),
             "dur": 60.0 + i,
             "fetch": None if i % 2 == 0 else 4.0 + i,   # NULL 혼재 이력
             # i % 2 회차만 bbc_sport 키 존재 → 희소 표현 (부재 = 0 계약은 Task 2 가공에서 검증)
             "counts": json.dumps({"bbc_sport": 3} if i % 2 else {}),
             "new": i % 3, "dup": 2, "err": 1 if i == n - 1 else 0, "sr": 0.9}
            for i in range(n)]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,fetch_duration_sec,source_counts,new_count,dup_count,"
            "error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:fetch,:counts,:new,:dup,:err,:sr)"), rows)
```

테스트 1개 추가:

```python
def test_ops_snapshot_includes_fetch_duration_with_nulls(engine):
    _seed_runs(engine, 3)
    snap = MartStore(engine).ops_snapshot()
    # 최신순: run-002 (i=2, NULL) · run-001 (i=1, 4.0+1=5.0) · run-000 (NULL) — 손 재계산
    assert snap["runs"][0]["fetch_duration_sec"] is None
    assert snap["runs"][1]["fetch_duration_sec"] == 5.0
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_serve_ops.py tests/integration/test_ops_snapshot.py -v`
Expected: 신규 4개 FAIL ( `StopIteration` — fetch_duration 행 없음 · KeyError 계열 ), 기존 통과.

- [ ] **Step 3: ops_snapshot SELECT 에 컬럼 추가**

`src/bullet_in/storage/mariadb.py` 122–126행:

```python
            runs = [dict(r) for r in c.execute(text(
                "SELECT run_id,started_at,duration_sec,fetch_duration_sec,"
                "source_counts,new_count,dup_count,error_count,success_rate "
                "FROM pipeline_runs ORDER BY started_at DESC LIMIT :n"),
                {"n": chart_runs}).mappings().all()]
```

- [ ] **Step 4: build_ops_view SLO 블록에 행 추가**

`src/bullet_in/serve/render.py` — `if runs:` 블록 ( 180행~ ) 에서 `avg_dur` 계산 뒤에 fetch 평균 추가, slo 리스트의 duration 행 뒤에 행 추가:

```python
    if runs:
        avg_sr = sum(r["success_rate"] for r in runs) / len(runs)
        avg_dur = sum(r["duration_sec"] for r in runs) / len(runs)
        fetch_vals = [r["fetch_duration_sec"] for r in runs
                      if r.get("fetch_duration_sec") is not None]  # NULL 이력 제외 (§6)
        avg_fetch = sum(fetch_vals) / len(fetch_vals) if fetch_vals else None
        slo = [
            {"slo_id": "SLO-2", "definition": "최근 30회 평균 success_rate",
             "value": f"{avg_sr * 100:.1f}%",
             "status": "ok" if avg_sr >= 0.9 else "bad"},
            {"slo_id": "SLO-5", "definition": "수집 끊긴 소스 수 (최신 run)",
             "value": "—" if stale_count is None else str(stale_count),
             "status": "info" if stale_count is None else ("ok" if not stale_count else "bad")},
            {"slo_id": "SLO-6", "definition": "현재 회차 이상 감지 소스 수",
             "value": str(anomaly_count),
             "status": "ok" if anomaly_count == 0 else "bad"},
            {"slo_id": "duration", "definition": "최근 30회 평균 소요 시간",
             "value": f"{avg_dur:.0f}s", "status": "info"},
            {"slo_id": "fetch_duration", "definition": "최근 30회 평균 fetch 시간",
             "value": "—" if avg_fetch is None else f"{avg_fetch:.0f}s",
             "status": "info"},
        ]
```

- [ ] **Step 5: 통과 확인**

Run: `uv run pytest tests/test_serve_ops.py tests/integration/test_ops_snapshot.py -v`
Expected: 전부 passed ( 신규 4 + 기존 ).

Run: `uv run pytest -q`
Expected: 전체 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py src/bullet_in/serve/render.py tests/test_serve_ops.py tests/integration/test_ops_snapshot.py
git commit -m "$(cat <<'EOF'
feat(ops): SLO 롤업에 fetch 평균 행 추가 · stale 배지 렌더 스모크

상시 기록되는 fetch_duration_sec을 운영 뷰에서 상시 확인할 수 있게 함.
PR #39 이월 ③(stale=1 배지 렌더 경로 미검증)도 같이 메움.

- ops_snapshot SELECT에 fetch_duration_sec 추가
- SLO 롤업 fetch_duration 행 — NULL 이력 제외 평균, 전부 NULL이면 — 표시
- stale=1 픽스처 렌더 스모크 (✕ 초과 · b-stale)
- 통합 시드에 NULL 혼재 fetch 이력 반영

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§6 · §7)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: dbt 연동 — stg_pipeline_runs 컬럼 + slo_rollup 행

**Files:**
- Modify: `dbt/models/staging/stg_pipeline_runs.sql`
- Modify: `dbt/models/marts/slo_rollup.sql`

**Interfaces:**
- Consumes: `maria.pipeline_runs.fetch_duration_sec` ( Task 3 ).
- Produces: `slo_rollup` 에 `slo_id = 'fetch_duration'` 행 — 기존 unique · not_null 테스트 대상.

- [ ] **Step 1: stg_pipeline_runs.sql 수정**

```sql
select run_id, started_at, duration_sec, fetch_duration_sec,
       new_count, dup_count, error_count, success_rate
from maria.pipeline_runs
```

- [ ] **Step 2: slo_rollup.sql 에 union 행 추가 ( duration 행 뒤 )**

```sql
union all
select 'fetch_duration',
       '최근 30회 평균 fetch_duration_sec',
       avg(fetch_duration_sec)
from recent
```

- [ ] **Step 3: dbt build 로 검증**

Run: `set -a; source .env; set +a; cd dbt && uv run dbt build --profiles-dir . && cd ..`
Expected: PASS — 신규 행 포함 slo_rollup 재생성, `unique_slo_rollup_slo_id` · `not_null_slo_rollup_slo_id` 포함 전체 테스트 통과.
비고: `avg()` 는 NULL 자동 제외 — 전부 NULL 이면 value 가 NULL 인 행이 남지만 slo_id 는 not_null 이라 테스트 영향 없음.

- [ ] **Step 4: 커밋**

```bash
git add dbt/models/staging/stg_pipeline_runs.sql dbt/models/marts/slo_rollup.sql
git commit -m "$(cat <<'EOF'
feat(dbt): slo_rollup에 fetch_duration 행 추가

ops 뷰와 이원 경로인 dbt 마트에도 같은 정의의 행을 추가해 지표 정의를
맞춤 (ops spec §5 표 = 양쪽 단일 기준 계약).

- stg_pipeline_runs에 fetch_duration_sec 컬럼 반영
- slo_rollup에 fetch_duration 행 (avg는 NULL 자동 제외)

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§6)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: ops spec §5.3 "같은 12회 창" 정밀화 ( 이월 ② )

**Files:**
- Modify: `docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md` ( 93행 )

**Interfaces:**
- Consumes: 없음 ( 문서만 ).
- Produces: 없음.

- [ ] **Step 1: 93행 교체**

현재:

```markdown
- **12회** — 신선도 추세 · 소스별 합계. SLO-6 이상 탐지의 히스토리 창과 동일 = 알림과 뷰가 같은 창을 본다.
```

교체 ( 정정 표식 포함 ):

```markdown
- **12회** — 신선도 추세 · 소스별 합계. SLO-6 이상 탐지와 같은 크기의 창이지만 위상이 한 회차 다르다:
  SLO-6 은 현재 런 INSERT 전 직전 12회 ( run.py 조회 시점 ), 뷰는 INSERT 후 최근 12회 ( 현재 런 포함 ).
  ( 정정 2026-07-14: 원문 "같은 창을 본다" 가 이 한 회차 차이를 숨겨 정밀화 — PR #39 최종 리뷰 이월 ② )
```

- [ ] **Step 2: 서식 훅 통과 확인**

저장 시 PostToolUse 훅 ( `check-doc-format.py` ) 이 통과해야 한다.
실패하면 지적된 행만 §2.2 규칙으로 수정.

- [ ] **Step 3: 커밋**

```bash
git add docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md
git commit -m "$(cat <<'EOF'
docs(spec): ops 뷰 §5.3 12회 창 표현 정밀화 (PR #39 이월 ②)

"알림과 뷰가 같은 창을 본다"는 표현이 한 회차 어긋남(SLO-6 = INSERT 전
직전 12회, 뷰 = INSERT 후 현재 런 포함 12회)을 숨겨 정정함.

- 같은 크기 · 한 회차 위상차로 사실대로 기술 + 정정 표식(일자 · 사유)

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§7)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 벤치마크 런북 초안

**Files:**
- Create: `docs/runbook/2026-07-14-slo1-benchmark.md`

**Interfaces:**
- Consumes: Task 2 진입점.
- Produces: 실측 로그 섹션 — Task 8 이 3회 실측값 · 중앙값을 기입.

- [ ] **Step 1: 런북 작성**

아래 뼈대로 작성한다 — "실측 로그" 표의 값 칸은 Task 8 이 채우므로 비워 둔다 ( 이 계획서가 미리 결과값을 적지 않는 것은 결함 전파 예방 계약 ).

```markdown
# SLO-1 병렬화 벤치마크 런북 (2026-07-14)

`python -m bullet_in.benchmark` 로 순차 vs 병렬 fetch speedup 을 실측하는 절차와 해석 기준.
설계: `docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md`.

## 1. 실행 절차

- 사전: `set -a; source .env; set +a` ( X 쿠키 · 자격 필요 — afcstuff 어댑터 ).
- 실행: `uv run python -m bullet_in.benchmark` ( 순차 → 60s 대기 → 병렬, JSON stdout ).
- 서로 다른 시간대에 3회 실행 ( 최소 1시간 간격 권장 ) → speedup_pct 중앙값을 README §4 에 기입.

## 2. 소스 부하 주의

- 1세트 = enabled 소스별 2회 타격 ( 순차 1 + 병렬 1 ).
- fmkorea 는 430 rate-limit 이력, afcstuff 는 Playwright 로그인이 세트당 2회 발생.
- 단시간 반복 실행 금지 — 스크립트 내 반복 대신 시간대 분산 3회가 이 이유.

## 3. 결과 해석

- `errors_seq` · `errors_par` 의 소스 집합이 다르면 그 회차는 비교 무효 — 폐기하고 재실행.
- `speedup_pct = null` 은 순차 합계 0 ( 전 소스 실패 ) — 환경 점검 후 재실행.
- `per_source` 최댓값이 병렬 시간의 하한 — 최장 소스가 지배하면 70% 미달이 구조적일 수 있다.
  그 경우 README 목표를 실측 기반으로 갱신하고 아래 로그에 사유를 남긴다 ( spec §3.4 ).

## 4. 한계

- 순차 → 병렬 순서 고정이라 서버 측 캐시 워밍이 병렬 패스에 유리할 수 있다.
  완전 제거는 불가 — 3회 중앙값으로 완화한다.

## 5. 실측 로그

| 회차 | 일시 (UTC) | sequential_sec | parallel_sec | speedup_pct | 비고 |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

- 중앙값: ( Task 8 기입 )
- 최장 소스: ( per_source 기준, Task 8 기입 )
```

- [ ] **Step 2: 서식 훅 통과 확인**

저장 시 PostToolUse 훅 통과 확인. 실패 시 지적 행만 수정.

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-07-14-slo1-benchmark.md
git commit -m "$(cat <<'EOF'
docs(runbook): SLO-1 벤치마크 실행 · 해석 런북

벤치마크가 라이브 소스를 2회씩 타격하므로 절차 · 부하 주의 · 해석
기준을 실측 전에 문서화함. 실측 로그는 라이브 검증 단계에서 기입.

- 절차 = 시간대 분산 3회 (최소 1시간 간격) → 중앙값 README 기입
- 부하 = fmkorea 430 · afcstuff Playwright 로그인 세트당 2회
- 해석 = 에러 집합 불일치 폐기 · per_source 최장 소스 지배 판단
- 한계 = 순차 → 병렬 순서 고정의 캐시 워밍 편향

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§10)
Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: 라이브 검증 + README SLO 표 기입 ( 메인 세션 )

**Files:**
- Modify: `README.md` ( §4, 61–69행 )
- Modify: `docs/runbook/2026-07-14-slo1-benchmark.md` ( §5 실측 로그 )

**Interfaces:**
- Consumes: Task 1–7 전부.
- Produces: PR 준비 완료 상태.

- [ ] **Step 1: 전체 테스트 · dbt 게이트**

Run: `uv run pytest -q`
Expected: 전체 통과.

Run: `set -a; source .env; set +a; cd dbt && uv run dbt build --profiles-dir . && cd ..`
Expected: PASS.

- [ ] **Step 2: 벤치마크 실측 3회**

`set -a; source .env; set +a; uv run python -m bullet_in.benchmark` 를 시간대를 나눠 3회 실행.
각 회차 직후 런북 §5 표에 일시 · sequential_sec · parallel_sec · speedup_pct 기입.
에러 집합 불일치 회차는 폐기 · 재실행 ( 런북 §3 ).
세션 내 간격 확보가 어려우면 회차 일정을 사용자와 조율한다.

- [ ] **Step 3: README §4 갱신**

3회 speedup_pct 의 중앙값을 손으로 산출해 표에 `실측` 컬럼을 추가:

```markdown
| 지표 | 목표 | 측정 방법 | 실측 |
|---|---|---|---|
| 병렬화 수집 시간 단축 | 순차 대비 ~70%↓ | `metrics.benchmark()` (concurrency=1 vs N 벤치마크) | N%↓ (2026-07-XX, 3회 중앙값) |
| 중복 적재율 | 0% | content_hash UNIQUE + dbt `unique` 테스트 | — |
| 일일 수집 성공률 | ≥ 99% | `pipeline_runs.success_rate` (재시도 · 소스 격리 포함) | — |
| 필수 필드 완전성 | ≥ 99% | dbt `not_null` 테스트 통과율 | — |
| 수집량 이상 감지 | 전일 대비 ±2σ 알림 | `quality.volume_anomaly` | — |
```

- N% · 날짜는 실측값으로 치환.
- 61행 인용문을 실측 반영으로 갱신: `> 목표치와 측정 방법. 병렬화 실측 절차는 docs/runbook/2026-07-14-slo1-benchmark.md.`
- 중앙값이 70% 미만이면 목표 셀을 `순차 대비 ~N%↓ (실측 기반 재조정)` 으로 갱신하고 사유를 런북 §5 에 기록 ( spec §3.4 ).

- [ ] **Step 4: 종단 실행 + ops 뷰 육안 확인**

Run: `set -a; source .env; set +a; uv run python -m bullet_in.run --concurrency 8`
Expected: summary 출력, 에러 없음.

확인:
- `pipeline_runs` 최신 행에 `fetch_duration_sec` 값 존재 · `started_at` 이 UTC 근방.
- `site/ops.html` SLO 롤업에 "최근 30회 평균 fetch 시간" 행 노출 ( 브라우저 육안 ).

- [ ] **Step 5: 커밋**

```bash
git add README.md docs/runbook/2026-07-14-slo1-benchmark.md
git commit -m "$(cat <<'EOF'
docs(readme): SLO 표 실측 컬럼 추가 · SLO-1 병렬화 실측값 기입

벤치마크 3회 중앙값으로 README SLO 공란을 채움. 실측 로그 · 사유는
런북 §5에 기록.

- README §4 실측 컬럼 + SLO-1 중앙값 (측정일 · 3회 중앙값 표기)
- 런북 실측 로그 3회 + 중앙값 · 최장 소스 기입

Refs: docs/superpowers/specs/2026-07-14-slo1-parallel-speedup-design.md (§10)
Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

비고: 실측 결과에 따라 커밋 본문 불릿은 실제 값 기준으로 조정한다 ( 70% 미달 시 목표 재조정 불릿 추가 ).

---

## Self-Review 결과

- **Spec coverage**: §3.1–§3.4 ( Task 1 · 2 · 7 · 8 ) · §4 ( Task 1 · 2 ) · §5 ( Task 3 ) · §6 ( Task 4 · 5 ) · §7 ( Task 4 · 6 ) · §8 ( Task 1 가드 · Task 4 NULL · Task 7 한계 ) · §9 ( 각 Task 테스트 + Task 8 ) · §10–§11 ( Task 7 · 8 ) — 전 섹션 매핑 확인.
- **Placeholder**: Task 7 런북 실측 로그 빈 칸 · Task 8 의 "N%" 는 라이브 실측으로만 채울 수 있는 값 — 의도된 런타임 기입 지점이며 기입 주체 ( Task 8 ) 를 명시함.
- **Type consistency**: `RUN_INSERT_SQL` 바인딩 키 ( :started · :fetch ) 가 Task 3 run.py · 통합 테스트에서 동일, `fetch_duration_sec` 키가 Task 3 → 4 → 5 에서 동일, `benchmark()` 반환 키가 Task 1 → 2 → 7 에서 동일함을 확인.
