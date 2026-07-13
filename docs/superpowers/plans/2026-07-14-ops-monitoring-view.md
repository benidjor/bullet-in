# 수집 현황 모니터링 뷰 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매 파이프라인 회차 `site/ops.html` 운영 뷰를 생성하고 dbt 마트 `tier_distribution` · `slo_rollup` 을 추가한다.

**Architecture:** run.py 가 `pipeline_runs` INSERT 후 `MartStore.ops_snapshot()` 으로 MariaDB 를 직접 집계하고, 순수 함수로 뷰모델 · SVG 좌표를 만들어 Jinja2 정적 페이지로 렌더한다.
dbt 마트는 뷰와 독립적으로 기존 수동 게이트 안에서 동작한다.
spec: `docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md` ( 지표 정의 §5 · 데이터 계약 §6 이 단일 기준 ).

**Tech Stack:** Python 3.11 · SQLAlchemy ( text SQL ) · Jinja2 · dbt-duckdb ( mysql_scanner attach ) · pytest.

## Global Constraints

- 브라우저 JS · 외부 차트 라이브러리 금지 — SVG 좌표는 파이썬이 계산 ( spec §3.2 ).
- 화면 표기: "번역 · 분류 대기" · "수집 끊긴 소스" · "✕ 초과 / ✓ 신선" ( spec §3.3 ).
- `source_counts` 는 부재 = 0, `source_freshness` 부재 회차는 진짜 결측 ( spec §6.1 ).
- `age_hours` · `stale` 은 저장값 그대로 표시, 재계산 금지 ( spec §6.2 ).
- 시각은 `MartStore.db_now()` ( UTC ) 재사용, 화면에 "UTC" 명기.
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + 실제 작업 모델 트레일러 ( 컨벤션 §1.1 · §1.3 ).
- `docs/` 아래 .md 는 서식 훅 ( §2.2 ) 통과 필수.
- 확정 목업 ( 구현 기준 ): `docs/superpowers/specs/assets/2026-07-14-ops-view-mockup.html`.
- 베이스라인: `uv run pytest -q` = 213 passed · 1 skipped ( 2026-07-14, DB 미기동 환경 ).

**모델 배정 ( SDD 실행 시 )**: Task 1–3 · 5 구현 = Haiku 4.5, Task 4 · 6 구현 = Sonnet 5, 태스크 리뷰 = Sonnet 5, 최종 whole-branch 리뷰 = Fable 5.
커밋 트레일러에 실제 배정 모델을 반영한다.

---

### Task 1: MartStore.ops_snapshot 집계 메서드

**Files:**
- Modify: `src/bullet_in/storage/mariadb.py` ( import 블록 + 클래스 끝에 메서드 추가 )
- Modify: `tests/integration/conftest.py` ( clean fixture 에 pipeline_runs 삭제 추가 )
- Test: `tests/integration/test_ops_snapshot.py` ( 신규 )

**Interfaces:**
- Consumes: 기존 `MartStore.engine`, `pipeline_runs` · `source_freshness` · `articles` 테이블 ( `schema.sql` ).
- Produces: `MartStore.ops_snapshot(chart_runs: int = 30, trend_runs: int = 12) -> dict`.
  반환 키: `runs` ( list[dict], 최신순, `source_counts` 는 파싱된 dict ) · `freshness` ( list[dict], checked_at 오름차순 ) · `tier_counts` ( dict ) · `pending` ( dict[source_id, {"translate": int, "stage": int}] ).
  Task 2 의 `build_ops_view()` 가 이 dict 를 그대로 입력으로 받는다.

- [ ] **Step 1: conftest clean fixture 에 pipeline_runs 정리 추가**

`tests/integration/conftest.py` 의 `clean` fixture 를 수정:

```python
@pytest.fixture(autouse=True)
def clean(engine):
    with engine.begin() as c:
        c.execute(text("DELETE FROM articles"))
        c.execute(text("DELETE FROM source_freshness"))
        c.execute(text("DELETE FROM pipeline_runs"))
    yield
```

- [ ] **Step 2: 실패하는 통합 테스트 작성**

`tests/integration/test_ops_snapshot.py` 신규:

```python
import json
from datetime import datetime, timedelta
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.storage.mariadb import MartStore


def _seed_runs(engine, n, base=datetime(2026, 7, 1, 0, 0)):
    rows = [{"rid": f"run-{i:03d}", "t": base + timedelta(hours=6 * i),
             "dur": 60.0 + i,
             # i % 2 회차만 bbc_sport 키 존재 → 희소 표현 (부재 = 0 계약은 Task 2 가공에서 검증)
             "counts": json.dumps({"bbc_sport": 3} if i % 2 else {}),
             "new": i % 3, "dup": 2, "err": 1 if i == n - 1 else 0, "sr": 0.9}
            for i in range(n)]
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,finished_at,"
            "duration_sec,source_counts,new_count,dup_count,error_count,success_rate) "
            "VALUES (:rid,'test',:t,:t,:dur,:counts,:new,:dup,:err,:sr)"), rows)


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


def test_ops_snapshot_limits_runs_newest_first_and_parses_counts(engine):
    _seed_runs(engine, 35)
    snap = MartStore(engine).ops_snapshot()
    assert len(snap["runs"]) == 30
    assert snap["runs"][0]["run_id"] == "run-034"        # 최신 우선
    assert isinstance(snap["runs"][1]["source_counts"], dict)
    assert snap["runs"][1]["source_counts"] == {"bbc_sport": 3}  # run-033 (홀수)


def test_ops_snapshot_freshness_window_and_null_age(engine):
    _seed_freshness(engine, 14)
    snap = MartStore(engine).ops_snapshot()
    run_ids = {r["run_id"] for r in snap["freshness"]}
    assert len(run_ids) == 12                             # 최근 12회 창
    assert "run-000" not in run_ids and "run-001" not in run_ids
    assert snap["freshness"][0]["checked_at"] <= snap["freshness"][-1]["checked_at"]
    nulls = [r for r in snap["freshness"] if r["source_id"] == "never_source"]
    assert nulls and all(r["age_hours"] is None for r in nulls)


def test_ops_snapshot_tier_counts_and_pending(engine):
    store = MartStore(engine)
    store.upsert([_art("h1", "https://x.test/1", title_ko="번역됨", transfer_stage="rumor"),
                  _art("h2", "https://x.test/2"),
                  _art("h3", "https://x.test/3", tier=3)])
    snap = store.ops_snapshot()
    assert snap["tier_counts"] == {2.0: 2, 3.0: 1}
    # rows_missing_translation (title_ko IS NULL) · rows_missing_stage 와 동일 술어
    assert snap["pending"]["bbc_sport"] == {"translate": 2, "stage": 2}


def test_ops_snapshot_cold_start_returns_empty_shapes(engine):
    snap = MartStore(engine).ops_snapshot()
    assert snap == {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `set -a; source .env; set +a; uv run pytest tests/integration/test_ops_snapshot.py -v`
Expected: FAIL — `AttributeError: 'MartStore' object has no attribute 'ops_snapshot'` ( DB 미기동이면 skip 되므로 `docker compose up -d` 선행 ).

- [ ] **Step 4: ops_snapshot 구현**

`src/bullet_in/storage/mariadb.py` — 파일 상단 import 에 `json` 추가:

```python
from __future__ import annotations
import json
from datetime import datetime
```

클래스 끝 ( `record_freshness` 아래 ) 에 추가:

```python
    def ops_snapshot(self, chart_runs: int = 30, trend_runs: int = 12) -> dict:
        """운영 뷰 (ops.html) 집계 스냅샷. 지표 정의는 spec §5 표가 기준.
        pending 은 rows_missing_translation/stage 와 동일 술어로 카운트."""
        with self.engine.connect() as c:
            runs = [dict(r) for r in c.execute(text(
                "SELECT run_id,started_at,duration_sec,source_counts,"
                "new_count,dup_count,error_count,success_rate "
                "FROM pipeline_runs ORDER BY started_at DESC LIMIT :n"),
                {"n": chart_runs}).mappings().all()]
            freshness = [dict(r) for r in c.execute(text(
                "SELECT run_id,checked_at,source_id,last_fetched_at,"
                "age_hours,threshold_hours,stale FROM source_freshness "
                "WHERE run_id IN (SELECT run_id FROM ("
                " SELECT DISTINCT run_id, checked_at FROM source_freshness"
                " ORDER BY checked_at DESC LIMIT :n) w) "
                "ORDER BY checked_at, source_id"),
                {"n": trend_runs}).mappings().all()]
            tier_rows = c.execute(text(
                "SELECT tier, COUNT(*) FROM articles GROUP BY tier")).all()
            pending_rows = c.execute(text(
                "SELECT source_id, SUM(title_ko IS NULL), "
                "SUM(transfer_stage IS NULL) FROM articles "
                "GROUP BY source_id")).all()
        for r in runs:
            r["source_counts"] = (json.loads(r["source_counts"])
                                  if r["source_counts"] else {})
        return {"runs": runs, "freshness": freshness,
                "tier_counts": {t: int(n) for t, n in tier_rows},
                "pending": {sid: {"translate": int(tr), "stage": int(st)}
                            for sid, tr, st in pending_rows}}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/integration/test_ops_snapshot.py -v`
Expected: 4 PASS.

- [ ] **Step 6: 전체 회귀 확인**

Run: `uv run pytest -q`
Expected: 기존 213 + 신규 4 통과 ( DB 기동 시 ).

- [ ] **Step 7: 커밋**

```bash
git add src/bullet_in/storage/mariadb.py tests/integration/conftest.py tests/integration/test_ops_snapshot.py
git commit  # feat(storage): 운영 뷰 집계 스냅샷 ops_snapshot
```

---

### Task 2: 뷰모델 · SVG 좌표 순수 함수

**Files:**
- Modify: `src/bullet_in/serve/render.py` ( `facet_counts` 아래에 함수군 추가 )
- Test: `tests/test_ops_view.py` ( 신규 )

**Interfaces:**
- Consumes: Task 1 의 `ops_snapshot()` 반환 dict, `load_sources()` 반환 dict ( `{source_id: {display_name, ...}}`, enabled 만 포함 ).
- Produces:
  `build_ops_view(snapshot: dict, sources: dict, anomaly_count: int, now: datetime) -> dict`
  · `spark_points(values: list[float], width: int = 84, height: int = 18) -> str`.
  뷰모델 키 계약 ( Task 3 템플릿이 사용 ):
  `generated_at` ( str ) · `kpi` ( dict: new · dup · err · success · stale · pending — 값은 표시용 str, 콜드 스타트 = "—" ) ·
  `runs_chart` ( list[dict]: h ( int 0–100 ) · err ( bool ) · label ( str ), 과거→최신 ) ·
  `freshness` ( list[dict]: display · last · age · thr · points · status ( "fresh" | "stale" | "none" ) ) ·
  `volume` ( list[dict]: display · total · bar_pct · translate · stage ) ·
  `tiers` ( list[dict]: label · count · pct ) ·
  `slo` ( list[dict]: slo_id · definition · value · status ( "ok" | "bad" | "info" ) ).

- [ ] **Step 1: 실패하는 단위 테스트 작성**

`tests/test_ops_view.py` 신규:

```python
from datetime import datetime
from bullet_in.serve.render import build_ops_view, spark_points

NOW = datetime(2026, 7, 14, 9, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"},
           "fmkorea": {"display_name": "fmkorea"},
           "dead_source": {"display_name": "Dead"}}


def _run(rid, t, counts, new=5, dup=2, err=0, sr=1.0, dur=80.0):
    return {"run_id": rid, "started_at": t, "duration_sec": dur,
            "source_counts": counts, "new_count": new, "dup_count": dup,
            "error_count": err, "success_rate": sr}


def _fresh(rid, t, sid, age, stale=0, thr=48.0):
    return {"run_id": rid, "checked_at": t, "source_id": sid,
            "last_fetched_at": t if age is not None else None,
            "age_hours": age, "threshold_hours": thr, "stale": stale}


def _snapshot():
    t = datetime(2026, 7, 13, 0, 0)
    runs = [_run("r3", datetime(2026, 7, 14, 6, 0), {"bbc_sport": 4}, err=1),
            _run("r2", datetime(2026, 7, 14, 0, 0), {}),                    # 부분 부재
            _run("r1", datetime(2026, 7, 13, 18, 0), {"bbc_sport": 2, "fmkorea": 7})]
    fresh = [_fresh("r1", t, "bbc_sport", 5.0),
             _fresh("r2", datetime(2026, 7, 13, 6, 0), "bbc_sport", 11.0),
             _fresh("r3", datetime(2026, 7, 13, 12, 0), "bbc_sport", 26.0, stale=1, thr=24.0),
             _fresh("r3", datetime(2026, 7, 13, 12, 0), "never", None)]
    return {"runs": runs, "freshness": fresh,
            "tier_counts": {1.0: 4, 2.0: 3, 99.0: 1},
            "pending": {"fmkorea": {"translate": 5, "stage": 2}}}


def test_volume_counts_absent_rounds_as_zero_and_shows_dead_sources():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    by_name = {v["display"]: v for v in view["volume"]}
    assert by_name["BBC Sport"]["total"] == 6      # 4 + 0(부재) + 2
    assert by_name["fmkorea"]["total"] == 7        # 0(부재) + 0(부재) + 7
    assert by_name["Dead"]["total"] == 0           # 전 회차 부재도 행 노출


def test_freshness_null_age_is_none_status_and_partial_history_kept():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    rows = {v["display"]: v for v in view["freshness"]}
    assert rows["never"]["status"] == "none"       # 빨강 금지 → 중립
    assert rows["never"]["points"] == ""
    assert rows["BBC Sport"]["status"] == "stale"  # 최신 run(r3) 저장값 그대로
    assert rows["BBC Sport"]["points"]             # 있는 회차만으로 좌표 생성


def test_kpi_from_latest_run_and_pending_total():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=2, now=NOW)
    assert view["kpi"]["new"] == "5" and view["kpi"]["err"] == "1"
    assert view["kpi"]["stale"] == "1"
    assert view["kpi"]["pending"] == "7"           # 5 + 2
    slo6 = [s for s in view["slo"] if s["slo_id"] == "SLO-6"][0]
    assert slo6["value"] == "2"


def test_tier_out_of_range_folds_into_etc():
    view = build_ops_view(_snapshot(), SOURCES, anomaly_count=0, now=NOW)
    etc = [t for t in view["tiers"] if t["label"].startswith("기타")][0]
    assert etc["count"] == 1


def test_cold_start_renders_dashes_without_crash():
    empty = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}
    view = build_ops_view(empty, SOURCES, anomaly_count=0, now=NOW)
    assert view["kpi"]["new"] == "—" and view["runs_chart"] == []
    assert view["generated_at"].endswith("UTC")


def test_spark_points_guards_zero_and_single_values():
    assert spark_points([]) == ""
    assert spark_points([0, 0, 0])                 # 전부 0 → 평평, 예외 없음
    assert " " not in spark_points([5.0])          # 단일값 → 점 1개
    pts = spark_points([1.0, 2.0, 3.0])
    assert len(pts.split(" ")) == 3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_ops_view.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_ops_view'`.

- [ ] **Step 3: 구현**

`src/bullet_in/serve/render.py` — `facet_counts` 함수 아래에 추가 ( 기존 코드 무변경 ):

```python
# ---- 운영 뷰 (ops.html) 뷰모델 ----
# 지표 정의 · 데이터 계약: docs/superpowers/specs/2026-07-14-ops-monitoring-view-design.md §5 · §6

TIER_BUCKETS = [(1.0, "Tier 1 — 공식 · 1군 언론"),
                (2.0, "Tier 2 — 2군 · 애그리게이터"),
                (3.0, "Tier 3 — ITK · 루머")]
ETC_TIER_LABEL = "기타 (0 · 1.5 · 4)"


def spark_points(values: list[float], width: int = 84, height: int = 18) -> str:
    if not values:
        return ""
    vmin, vmax = min(values), max(values)
    span = max(vmax - vmin, 1)                      # 전부 동일값 → 분모 1 (평평한 선)
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = 0 if n == 1 else i * width / (n - 1)
        y = (height - 2) - (v - vmin) / span * (height - 4)
        pts.append(f"{x:.0f},{y:.0f}")
    return " ".join(pts)


def _kpi(runs: list[dict], stale_count: int | None, pending_total: int) -> dict:
    if not runs:
        return {"new": "—", "dup": "—", "err": "—", "success": "—",
                "stale": "—", "pending": str(pending_total)}
    top = runs[0]
    return {"new": str(top["new_count"]), "dup": str(top["dup_count"]),
            "err": str(top["error_count"]),
            "success": f"{top['success_rate'] * 100:.0f}%",
            "stale": "—" if stale_count is None else str(stale_count),
            "pending": str(pending_total)}


def build_ops_view(snapshot: dict, sources: dict, anomaly_count: int,
                   now: datetime) -> dict:
    runs = snapshot["runs"]                          # 최신순
    chrono = list(reversed(runs))                    # 차트는 과거 → 최신

    max_new = max((r["new_count"] for r in chrono), default=0) or 1
    runs_chart = [{
        "h": round(r["new_count"] / max_new * 100),
        "err": r["error_count"] > 0,
        "label": (f"{r['started_at']:%m-%d %H:%M} UTC · 신규 {r['new_count']}"
                  f" · 중복 {r['dup_count']} · 에러 {r['error_count']}"),
    } for r in chrono]

    fresh_rows = snapshot["freshness"]               # checked_at 오름차순
    latest_run = fresh_rows[-1]["run_id"] if fresh_rows else None
    latest = {r["source_id"]: r for r in fresh_rows if r["run_id"] == latest_run}
    history: dict[str, list[float]] = {}
    for r in fresh_rows:                              # 부재 회차 없음 = 진짜 결측 (§6.1)
        if r["age_hours"] is not None:
            history.setdefault(r["source_id"], []).append(float(r["age_hours"]))
    freshness = []
    for sid, row in sorted(latest.items()):
        disp = sources.get(sid, {}).get("display_name") or sid
        if row["age_hours"] is None:
            freshness.append({"display": disp, "last": "이력 없음", "age": "—",
                              "thr": f"{row['threshold_hours']:.0f}h",
                              "points": "", "status": "none"})
            continue
        freshness.append({
            "display": disp,
            "last": f"{row['last_fetched_at']:%m-%d %H:%M}",
            "age": f"{row['age_hours']:.1f}h",
            "thr": f"{row['threshold_hours']:.0f}h",
            "points": spark_points(history.get(sid, [])),
            "status": "stale" if row["stale"] else "fresh",   # 저장값 그대로 (§6.2)
        })
    stale_count = (sum(1 for r in latest.values() if r["stale"])
                   if latest else None)

    trend = runs[:12]                                 # 신선도 추세와 같은 12회 창
    totals = {sid: sum(r["source_counts"].get(sid, 0) for r in trend)  # 부재 = 0 (§6.1)
              for sid in sources}
    max_total = max(totals.values(), default=0) or 1
    pending = snapshot["pending"]
    volume = [{
        "display": sources.get(sid, {}).get("display_name") or sid,
        "total": total,
        "bar_pct": round(total / max_total * 100),
        "translate": pending.get(sid, {}).get("translate", 0),
        "stage": pending.get(sid, {}).get("stage", 0),
    } for sid, total in sorted(totals.items(), key=lambda kv: -kv[1])]
    pending_total = sum(p["translate"] + p["stage"] for p in pending.values())

    tier_counts = snapshot["tier_counts"]
    total_articles = sum(tier_counts.values()) or 1
    known = {t for t, _ in TIER_BUCKETS}
    tiers = [{"label": label, "count": tier_counts.get(t, 0),
              "pct": round(tier_counts.get(t, 0) / total_articles * 100)}
             for t, label in TIER_BUCKETS]
    etc = sum(n for t, n in tier_counts.items() if t not in known)
    tiers.append({"label": ETC_TIER_LABEL, "count": etc,
                  "pct": round(etc / total_articles * 100)})

    if runs:
        avg_sr = sum(r["success_rate"] for r in runs) / len(runs)
        avg_dur = sum(r["duration_sec"] for r in runs) / len(runs)
        slo = [
            {"slo_id": "SLO-2", "definition": "최근 30회 평균 success_rate",
             "value": f"{avg_sr * 100:.1f}%",
             "status": "ok" if avg_sr >= 0.9 else "bad"},
            {"slo_id": "SLO-5", "definition": "수집 끊긴 소스 수 (최신 run)",
             "value": "—" if stale_count is None else str(stale_count),
             "status": "ok" if not stale_count else "bad"},
            {"slo_id": "SLO-6", "definition": "현재 회차 이상 감지 소스 수",
             "value": str(anomaly_count),
             "status": "ok" if anomaly_count == 0 else "bad"},
            {"slo_id": "duration", "definition": "최근 30회 평균 소요 시간",
             "value": f"{avg_dur:.0f}s", "status": "info"},
        ]
    else:
        slo = []

    return {"generated_at": f"{now:%Y-%m-%d %H:%M} UTC",
            "kpi": _kpi(runs, stale_count, pending_total),
            "runs_chart": runs_chart, "freshness": freshness,
            "volume": volume, "tiers": tiers, "slo": slo}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_ops_view.py -v`
Expected: 6 PASS.

- [ ] **Step 5: 전체 회귀 후 커밋**

Run: `uv run pytest -q` → 통과 확인.

```bash
git add src/bullet_in/serve/render.py tests/test_ops_view.py
git commit  # feat(serve): 운영 뷰 뷰모델 · SVG 좌표 순수 함수
```

---

### Task 3: ops.html.j2 템플릿 · render_ops · write_ops

**Files:**
- Create: `src/bullet_in/serve/templates/ops.html.j2`
- Modify: `src/bullet_in/serve/render.py` ( 파일 끝에 `render_ops` · `write_ops` 추가 )
- Test: `tests/test_serve_ops.py` ( 신규 )

**Interfaces:**
- Consumes: Task 2 의 `build_ops_view()` 뷰모델 키 계약 · Task 1 의 `ops_snapshot()` dict.
- Produces:
  `render_ops(view: dict) -> str` ·
  `write_ops(snapshot: dict, sources: dict, out_dir: str | Path, anomaly_count: int, now: datetime) -> None` ( `out_dir/ops.html` 생성 ).
  Task 4 의 run.py 가 `write_ops` 를 호출한다.

- [ ] **Step 1: 실패하는 렌더 스모크 테스트 작성**

`tests/test_serve_ops.py` 신규:

```python
from datetime import datetime
from bullet_in.serve.render import build_ops_view, render_ops, write_ops

NOW = datetime(2026, 7, 14, 9, 12, 0)
SOURCES = {"bbc_sport": {"display_name": "BBC Sport"}}


def _snapshot():
    return {"runs": [{"run_id": "r1", "started_at": NOW, "duration_sec": 80.0,
                      "source_counts": {"bbc_sport": 4}, "new_count": 4,
                      "dup_count": 2, "error_count": 0, "success_rate": 1.0}],
            "freshness": [{"run_id": "r1", "checked_at": NOW,
                           "source_id": "bbc_sport", "last_fetched_at": NOW,
                           "age_hours": 2.1, "threshold_hours": 48.0, "stale": 0}],
            "tier_counts": {2.0: 4}, "pending": {}}


def test_render_ops_contains_tiles_sections_and_labels():
    html = render_ops(build_ops_view(_snapshot(), SOURCES, 0, NOW))
    assert "수집 끊긴 소스" in html and "번역 · 분류 대기" in html
    for title in ("회차별 수집량", "소스별 신선도", "소스별 수집량",
                  "tier 분포", "SLO 롤업"):
        assert title in html
    assert "2026-07-14 09:12 UTC" in html
    assert "<script" not in html                     # JS 금지 계약
    assert "polyline" in html                        # 스파크라인 존재


def test_render_ops_cold_start_survives():
    empty = {"runs": [], "freshness": [], "tier_counts": {}, "pending": {}}
    html = render_ops(build_ops_view(empty, SOURCES, 0, NOW))
    assert "이력 없음" in html and "—" in html


def test_write_ops_creates_file(tmp_path):
    write_ops(_snapshot(), SOURCES, tmp_path, anomaly_count=0, now=NOW)
    out = tmp_path / "ops.html"
    assert out.exists() and "bullet-in 수집 현황" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_serve_ops.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_ops'`.

- [ ] **Step 3: 템플릿 작성**

`src/bullet_in/serve/templates/ops.html.j2` 신규 — 독립 문서 ( `_layout.html.j2` 미사용, 사이드바 · app.js 무관 ).
확정 목업 `docs/superpowers/specs/assets/2026-07-14-ops-view-mockup.html` 의 구조 · 팔레트를 따른다:

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bullet-in 수집 현황</title>
<style>
  :root { --surface:#fcfcfb; --ink:#0b0b0b; --sec:#52514e; --mut:#898781;
          --grid:#e1e0d9; --line:#c3c2b7; --blue:#2a78d6; --red:#d03b3b;
          --ok-bg:rgba(12,163,12,.12); --ok-fg:#006300;
          --crit-bg:rgba(208,59,59,.12); --crit-fg:#d03b3b;
          --none-bg:rgba(137,135,129,.15); --none-fg:#52514e; }
  @media (prefers-color-scheme: dark) {
    :root { --surface:#1a1a19; --ink:#fff; --sec:#c3c2b7; --grid:#2c2c2a;
            --line:#383835; --blue:#3987e5; --ok-fg:#0ca30c; --none-fg:#c3c2b7; }
  }
  body { margin:0 auto; max-width:860px; padding:24px 16px; background:var(--surface);
         color:var(--ink); font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
  header { display:flex; justify-content:space-between; align-items:baseline; }
  h1 { font-size:18px; margin:0; }
  .mut { color:var(--mut); font-size:11px; }
  h2 { font-size:14px; margin:22px 0 6px; }
  table { width:100%; border-collapse:collapse; margin:4px 0; }
  th { text-align:left; font-weight:600; color:var(--mut); font-size:10px;
       text-transform:uppercase; letter-spacing:.04em; padding:4px 8px;
       border-bottom:1px solid var(--line); }
  td { padding:4px 8px; border-bottom:1px solid var(--grid);
       font-variant-numeric:tabular-nums; }
  .sec { color:var(--sec); }
  .badge { display:inline-block; padding:0 6px; border-radius:8px;
           font-size:11px; font-weight:600; }
  .b-fresh { background:var(--ok-bg); color:var(--ok-fg); }
  .b-stale { background:var(--crit-bg); color:var(--crit-fg); }
  .b-none  { background:var(--none-bg); color:var(--none-fg); }
  .tiles { display:flex; gap:8px; margin:14px 0; flex-wrap:wrap; }
  .tile { flex:1 1 110px; border:1px solid var(--grid); border-radius:8px;
          padding:8px 10px; }
  .tile .v { font-size:22px; font-weight:700; }
  .tile .v.bad { color:var(--red); }
  .tile .k { font-size:9px; color:var(--mut); text-transform:uppercase;
             letter-spacing:.04em; }
  .bars { display:flex; align-items:flex-end; gap:2px; height:56px; margin:6px 0 2px; }
  .bars div { flex:1; background:var(--blue); border-radius:3px 3px 0 0; min-height:2px; }
  .bars div.err { background:var(--red); }
  .hbar { height:12px; background:var(--blue); border-radius:3px;
          display:inline-block; vertical-align:middle; }
  footer { margin-top:20px; border-top:1px solid var(--grid); padding-top:8px; }
  footer a { color:var(--sec); }
</style>
</head>
<body>
<header>
  <h1>bullet-in 수집 현황</h1>
  <span class="mut">생성: {{ view.generated_at }}</span>
</header>

<div class="tiles">
  <div class="tile"><div class="v">{{ view.kpi.new }}</div><div class="k">신규 (최근 회차)</div></div>
  <div class="tile"><div class="v">{{ view.kpi.dup }}</div><div class="k">중복 차단</div></div>
  <div class="tile"><div class="v">{{ view.kpi.err }}</div><div class="k">에러</div></div>
  <div class="tile"><div class="v">{{ view.kpi.success }}</div><div class="k">성공률</div></div>
  <div class="tile"><div class="v{{ ' bad' if view.kpi.stale not in ('0', '—') }}">{{ view.kpi.stale }}</div><div class="k">수집 끊긴 소스</div></div>
  <div class="tile"><div class="v">{{ view.kpi.pending }}</div><div class="k">번역 · 분류 대기</div></div>
</div>

<h2>① 회차별 수집량 (최근 30회)</h2>
{% if view.runs_chart %}
<div class="bars">
  {% for b in view.runs_chart %}<div class="{{ 'err' if b.err }}" style="height:{{ b.h }}%" title="{{ b.label }}"></div>{% endfor %}
</div>
<div class="mut">막대 = 회차 신규 건수 · 빨강 = 에러 있던 회차 · 마우스를 올리면 회차 상세</div>
{% else %}<p class="mut">이력 없음</p>{% endif %}

<h2>② 소스별 신선도</h2>
{% if view.freshness %}
<table>
  <tr><th>소스</th><th>마지막 수집</th><th>경과 / 임계</th><th>age 추세 (12회)</th><th>상태</th></tr>
  {% for f in view.freshness %}
  <tr>
    <td>{{ f.display }}</td><td class="sec">{{ f.last }}</td>
    <td>{{ f.age }} / {{ f.thr }}</td>
    <td>{% if f.points %}<svg width="84" height="18"><polyline points="{{ f.points }}" fill="none" stroke="{{ 'var(--red)' if f.status == 'stale' else 'var(--blue)' }}" stroke-width="2"><title>최근 12회 age_hours 추세</title></polyline></svg>{% endif %}</td>
    <td>{% if f.status == 'fresh' %}<span class="badge b-fresh">✓ 신선</span>{% elif f.status == 'stale' %}<span class="badge b-stale">✕ 초과</span>{% else %}<span class="badge b-none">이력 없음</span>{% endif %}</td>
  </tr>
  {% endfor %}
</table>
{% else %}<p class="mut">이력 없음</p>{% endif %}

<h2>③ 소스별 수집량 · 번역 · 분류 대기 (최근 12회)</h2>
{% if view.volume %}
<table>
  <tr><th>소스</th><th>수집량 (12회 합)</th><th>번역 대기</th><th>분류 대기</th></tr>
  {% for v in view.volume %}
  <tr><td style="width:130px">{{ v.display }}</td>
      <td><span class="hbar" style="width:{{ [v.bar_pct, 2] | max }}%"></span> {{ v.total }}</td>
      <td>{{ v.translate }}</td><td>{{ v.stage }}</td></tr>
  {% endfor %}
</table>
<div class="mut">번역 대기 = 한국어 제목 · 본문 아직 없음 · 분류 대기 = 영입 단계 태그 아직 없음</div>
{% else %}<p class="mut">이력 없음</p>{% endif %}

<h2>④ tier 분포 (전체 기사)</h2>
<table>
  {% for t in view.tiers %}
  <tr><td style="width:200px">{{ t.label }}</td>
      <td><span class="hbar" style="width:{{ [t.pct, 2] | max }}%"></span> {{ t.pct }}% ({{ t.count }})</td></tr>
  {% endfor %}
</table>

<h2>⑤ SLO 롤업 (최근 30회 기준)</h2>
{% if view.slo %}
<table>
  <tr><th>SLO</th><th>정의</th><th>현재</th><th>상태</th></tr>
  {% for s in view.slo %}
  <tr><td>{{ s.slo_id }}</td><td class="sec">{{ s.definition }}</td><td>{{ s.value }}</td>
      <td>{% if s.status == 'ok' %}<span class="badge b-fresh">✓</span>{% elif s.status == 'bad' %}<span class="badge b-stale">✕</span>{% else %}<span class="mut">참고치</span>{% endif %}</td></tr>
  {% endfor %}
</table>
{% else %}<p class="mut">이력 없음</p>{% endif %}

<footer><a href="index.html">← 기사 페이지로</a></footer>
</body>
</html>
```

- [ ] **Step 4: render_ops · write_ops 구현**

`src/bullet_in/serve/render.py` 파일 끝에 추가:

```python
def render_ops(view: dict) -> str:
    return _env().get_template("ops.html.j2").render(view=view)


def write_ops(snapshot: dict, sources: dict, out_dir: str | Path,
              anomaly_count: int, now: datetime) -> None:
    """운영 뷰 site/ops.html 생성. 실패 격리는 호출부 (run.py) 책임."""
    view = build_ops_view(snapshot, sources, anomaly_count, now)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ops.html").write_text(render_ops(view), encoding="utf-8")
```

- [ ] **Step 5: 테스트 통과 · 회귀 확인**

Run: `uv run pytest tests/test_serve_ops.py tests/test_ops_view.py -v` → 전부 PASS.
Run: `uv run pytest -q` → 회귀 없음.

- [ ] **Step 6: 커밋**

```bash
git add src/bullet_in/serve/templates/ops.html.j2 src/bullet_in/serve/render.py tests/test_serve_ops.py
git commit  # feat(serve): 운영 뷰 정적 페이지 render_ops · write_ops
```

---

### Task 4: run.py 연결 · index 푸터 링크

**Files:**
- Modify: `src/bullet_in/run.py` ( import + `pipeline_runs` INSERT 블록 뒤 )
- Modify: `src/bullet_in/serve/templates/index.html.j2` ( content 블록 끝 )
- Modify: `src/bullet_in/serve/static/style.css` ( 파일 끝 )
- Test: `tests/test_serve_render.py` ( 푸터 링크 단언 추가 )

**Interfaces:**
- Consumes: Task 3 의 `write_ops(snapshot, sources, out_dir, anomaly_count, now)` · Task 1 의 `ops_snapshot()` · 기존 `anomalies` ( `volume_anomalies` 반환 list ) · `MartStore.db_now()`.
- Produces: 없음 ( 종단 연결 태스크 ).

- [ ] **Step 1: 실패하는 푸터 링크 테스트 추가**

`tests/test_serve_render.py` 끝에 추가:

```python
def test_index_footer_links_to_ops_page():
    html = render_index([_row()], SOURCES, NOW)
    assert '<a href="ops.html">수집 현황</a>' in html
```

Run: `uv run pytest tests/test_serve_render.py::test_index_footer_links_to_ops_page -v`
Expected: FAIL — assert 불일치.

- [ ] **Step 2: index 푸터 · CSS 추가**

`src/bullet_in/serve/templates/index.html.j2` — `{% endblock %}` 직전 ( 카드 그리드 `</div>` 뒤 ) 에 추가:

```html
<footer class="sitefoot"><a href="ops.html">수집 현황</a></footer>
```

`src/bullet_in/serve/static/style.css` 파일 끝에 추가:

```css
/* 운영 뷰 진입 푸터 */
.sitefoot { margin: 24px 0 8px; text-align: center; font-size: 12px; }
.sitefoot a { color: var(--muted, #898781); text-decoration: none; }
.sitefoot a:hover { text-decoration: underline; }
```

Run: `uv run pytest tests/test_serve_render.py -v`
Expected: 전부 PASS.

- [ ] **Step 3: run.py 연결**

`src/bullet_in/run.py` — import 수정 ( 기존 줄 교체 ):

```python
import argparse, asyncio, json, logging, os, time, uuid, yaml
```

```python
from bullet_in.serve.render import write_site, write_ops
```

`pipeline_runs` INSERT 블록 ( `with engine.begin() as c:` ... ) 바로 뒤 · `print(summary)` 앞에 추가:

```python
    # 운영 뷰 (ops.html): pipeline_runs 기록 후 DB 한 경로로 집계 · 렌더.
    # 실패해도 파이프라인은 계속 (spec §4 실패 격리).
    try:
        write_ops(mart.ops_snapshot(), sources, "site",
                  anomaly_count=len(anomalies), now=mart.db_now())
    except Exception:
        logging.getLogger(__name__).warning(
            "ops 뷰 생성 실패 — 파이프라인은 계속 진행", exc_info=True)
```

- [ ] **Step 4: 전체 회귀 확인**

Run: `uv run pytest -q`
Expected: 전부 통과 ( run.py 는 라이브 검증 대상 — Task 7 ).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/run.py src/bullet_in/serve/templates/index.html.j2 src/bullet_in/serve/static/style.css tests/test_serve_render.py
git commit  # feat(run): 운영 뷰 생성 연결 · index 푸터 진입 링크
```

---

### Task 5: dbt staging 2종 · 마트 2종

**Files:**
- Create: `dbt/models/staging/stg_pipeline_runs.sql`
- Create: `dbt/models/staging/stg_source_freshness.sql`
- Create: `dbt/models/marts/tier_distribution.sql`
- Create: `dbt/models/marts/slo_rollup.sql`
- Modify: `dbt/models/sources.yml` ( 신규 모델 테스트 추가 )

**Interfaces:**
- Consumes: `maria.pipeline_runs` · `maria.source_freshness` ( DuckDB mysql_scanner attach, `dbt/profiles.yml` ).
- Produces: dbt 마트 2종 — 뷰와 독립, 지표 정의는 spec §5 와 동일.

- [ ] **Step 1: staging 모델 작성**

`dbt/models/staging/stg_pipeline_runs.sql`:

```sql
select run_id, started_at, duration_sec,
       new_count, dup_count, error_count, success_rate
from maria.pipeline_runs
```

`dbt/models/staging/stg_source_freshness.sql`:

```sql
select run_id, checked_at, source_id, age_hours, stale
from maria.source_freshness
```

- [ ] **Step 2: 마트 모델 작성**

`dbt/models/marts/tier_distribution.sql`:

```sql
with counted as (
    select tier, count(*) as n_articles
    from {{ ref('stg_articles') }}
    group by tier
)
select tier, n_articles,
       round(100.0 * n_articles / sum(n_articles) over (), 1) as pct
from counted
```

`dbt/models/marts/slo_rollup.sql` ( SLO-6 은 감지 결과가 DB 에 없어 제외 — spec §7.2 ):

```sql
with recent as (
    select * from {{ ref('stg_pipeline_runs') }}
    order by started_at desc limit 30
),
latest_fresh as (
    select * from {{ ref('stg_source_freshness') }}
    where checked_at = (select max(checked_at)
                        from {{ ref('stg_source_freshness') }})
)
select 'SLO-2' as slo_id,
       '최근 30회 평균 success_rate' as metric,
       avg(success_rate) as value
from recent
union all
select 'SLO-5',
       '수집 끊긴 소스 수 (최신 run)',
       coalesce(sum(case when stale then 1 else 0 end), 0)
from latest_fresh
union all
select 'duration',
       '최근 30회 평균 duration_sec',
       avg(duration_sec)
from recent
```

- [ ] **Step 3: sources.yml 테스트 추가**

`dbt/models/sources.yml` 의 `models:` 목록 끝에 추가:

```yaml
  - name: tier_distribution
    columns:
      - name: tier
        tests: [unique, not_null]
  - name: slo_rollup
    columns:
      - name: slo_id
        tests: [unique, not_null]
```

- [ ] **Step 4: dbt build 로 신규 + 기존 게이트 확인**

Run: `docker compose up -d && cd dbt && uv run dbt build --profiles-dir . && cd ..`
Expected: PASS — 신규 4 모델 빌드 + 테스트 통과, 기존 `stg_articles` 테스트 · `daily_source_quality` 회귀 없음.
콜드 스타트 ( 이력 0행 ) 면 slo_rollup 의 value 가 NULL 일 수 있으나 테스트 대상은 `slo_id` 뿐이므로 통과가 정상.

- [ ] **Step 5: 커밋**

```bash
git add dbt/models/staging/stg_pipeline_runs.sql dbt/models/staging/stg_source_freshness.sql dbt/models/marts/tier_distribution.sql dbt/models/marts/slo_rollup.sql dbt/models/sources.yml
git commit  # feat(dbt): tier_distribution · slo_rollup 마트 + 실행 이력 staging
```

---

### Task 6: 운영 런북

**Files:**
- Create: `docs/runbook/2026-07-14-ops-monitoring-view.md`

**Interfaces:**
- Consumes: spec §5 지표 정의 · §6 데이터 계약 · §8 엣지 케이스, Task 1–5 산출물.
- Produces: 운영 문서 ( 코드와 같은 PR 동반 — spec §10 ).

- [ ] **Step 1: 런북 작성**

`docs/runbook/2026-07-14-ops-monitoring-view.md` 에 아래 구성으로 작성 ( 한국어 · 서식 §2.2 준수, 훅이 검사 ):

1. **개요** — 뷰의 목적 ( SLO-5 · 6 알림 수신 후 맥락 확인 ), 진입 경로 ( index 푸터 → `site/ops.html` ), 갱신 주기 ( 매 파이프라인 회차 ).
2. **화면 해석** — KPI 타일 6종과 섹션 5개 각각 "무엇을 보는가 · 이상 신호가 어떻게 보이는가".
   "수집 끊긴 소스" = SLO-5 stale, "번역 · 분류 대기" = 다음 Gemini 사이클 처리 잔량 ( 하루 4회 누적 구조 → 줄어드는지가 관건 ) 을 반드시 포함.
3. **데이터 계약 요약** — spec §6.1 표 ( 부재 = 0 vs 진짜 결측 ) 전재 + 트러블슈팅 문서 2건 상호 링크
   ( `2026-07-13-sparse-source-counts-trend-bias.md` · `2026-07-13-freshness-clock-mixing-gap.md` ).
4. **실패 모드** — "생성 시각이 낡음" = `write_ops` 실패 신호 → run.py `WARNING` 로그 확인 ·
   "이력 없음" 표시 조건 · 콜드 스타트 화면.
5. **dbt 마트 조회** — `cd dbt && uv run dbt build --profiles-dir .` 후
   `duckdb dbt/bullet_in.duckdb "select * from slo_rollup"` 예시, 뷰와 정의 동일 ( spec §5 ) · SLO-6 비대칭 명시.

- [ ] **Step 2: 서식 훅 통과 확인 후 커밋**

저장 시 PostToolUse 훅 통과 확인.

```bash
git add docs/runbook/2026-07-14-ops-monitoring-view.md
git commit  # docs(runbook): 수집 현황 운영 뷰 해석 · 실패 모드
```

---

### Task 7: 라이브 검증 · 캡처 · PR ( 컨트롤러 직접 수행 — subagent 위임 금지 )

**Files:**
- Create: `docs/assets/ops-view-live.png` ( 라이브 캡처 )
- 변경 없음 ( 검증 · PR 태스크 )

**Interfaces:**
- Consumes: Task 1–6 전체.
- Produces: PR ( 7섹션 한국어 본문 · `--body-file` · Claude 서명 금지 ).

- [ ] **Step 1: 종단 실행**

```bash
docker compose up -d
set -a; source .env; set +a
uv run python -m bullet_in.run --concurrency 8
```

Expected: summary 출력, `site/ops.html` 생성, `WARNING` 로그 없음.

- [ ] **Step 2: 브라우저 육안 확인 ( verification-before-completion )**

`site/ops.html` 을 열어 KPI 6 타일 · 섹션 5개 · 스파크라인 · 다크 모드를 확인하고 캡처를 `docs/assets/ops-view-live.png` 로 저장.
index 푸터 '수집 현황' 링크 진입 확인.
차트 · 라벨 겹침은 자동 검증 사각이므로 육안이 최종 게이트.

- [ ] **Step 3: 최종 whole-branch 리뷰 ( Fable 5 ) 후 PR**

`uv run pytest -q` · `dbt build` 재확인 → 캡처 커밋 → squash PR ( 머지 전 PR head = 로컬 HEAD 확인 ).

---

## Self-Review 결과

- **Spec coverage**: §3 ( A안 · 시각화 · 용어 ) = Task 2–3, §4 ( 흐름 · 격리 ) = Task 1 · 4, §5 ( 지표 ) = Task 1–2 · 5, §6 ( 계약 ) = Task 1–2 테스트, §7 ( dbt ) = Task 5, §8 ( 엣지 ) = Task 2–3 테스트, §9 ( 테스트 ) = 각 태스크 TDD + Task 7, §10 ( 성공 기준 ) = Task 7. 갭 없음.
- **Placeholder scan**: 코드 블록 전부 실코드, TBD 없음.
- **Type consistency**: `ops_snapshot()` 반환 dict 키 ( runs · freshness · tier_counts · pending ) 와 `build_ops_view()` 소비 키 일치, `write_ops` 시그니처 Task 3 정의 = Task 4 호출 일치, `spark_points` 명칭 통일 확인.
