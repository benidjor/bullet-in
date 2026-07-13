# SLO-5 신선도 워터마크 감시 구현 계획 (2026-07-13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 소스별 `MAX(fetched_at)` 워터마크의 경과 시간이 임계를 초과하면 Discord 로 알리고, 회차별 신선도를 `source_freshness` 이력 테이블에 기록한다.

**Architecture:** 순수 판정 함수 ( `quality.evaluate_freshness` ) 를 단위 테스트로 고정하고, DB 접점 ( 워터마크 조회 · 이력 적재 ) 은 `MartStore` 메서드로 분리해 통합 테스트 skip 규약을 따른다.
run.py 가 서빙 후 · SLO-6 anomaly 블록 인접에서 판정 → 기록 → 조건 알림을 잇는다.
spec: `docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md`.

**Tech Stack:** Python 3.11 · SQLAlchemy ( MariaDB ) · pytest · 기존 `notify.send_alert` Discord embed 배관.

## Global Constraints

- 스코프 = 감시 + 알림만. 증분 fetch 전환 · 어댑터 수정 · dbt freshness · `published_at` 사용 금지 ( spec §2 비목표 ).
- 임계: 전역 기본 48h ( `freshness_default_hours` 최상위 키 ) + 소스별 `freshness_hours` override, x_afcstuff = 24h.
- stale 판정은 `age > threshold` 엄격 초과. 정확히 같으면 stale 아님 ( spec §5 ).
- NULL 워터마크 ( 기사 0건 소스 ) 는 행 기록하되 stale False · 알림 제외 ( spec §5 ).
- `now` 는 DB `SELECT NOW()` — 앱 시계와의 TZ · 시계 불일치 제거 ( spec §4.1 ).
- `run_id` 는 `main()` 상단 1회 생성해 `source_freshness` · `pipeline_runs` 가 공유 ( spec §4.5 ).
- 알림은 stale 소스가 있을 때만 발송 · 없으면 무음 ( spec §4.4 ).
- 커밋: `<type>(<scope>): 한국어 제목` + 본문 ( 왜 ) + 실제 작업 모델 트레일러 ( 컨벤션 §1.3 개정 2026-07-13 ).
  설계 · 구현 모델이 다르면 역할 라벨 병기 — `Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>` + `Co-Authored-By: Claude <구현 subagent 모델> (구현) <noreply@anthropic.com>`.
  각 태스크 커밋 블록의 트레일러가 그 태스크의 배정 모델이며, 디스패치 모델 변경 시 트레일러도 맞출 것.
  git 신원은 `benidjor <94089198+benidjor@users.noreply.github.com>`.
- docs 산출물은 §2.2 서식 ( 한 줄 = 한 문장 · `·` 양옆 띄우기 · `—` 줄 끝 금지 ) — PostToolUse 훅이 검사.
- DB 통합 테스트는 `tests/integration/` 의 기존 `engine` fixture skip 규약을 따른다 ( MariaDB 없으면 skip ).

---

### Task 1: `quality.evaluate_freshness` 순수 판정 함수

**Files:**
- Modify: `src/bullet_in/quality.py`
- Test: `tests/test_quality.py`

**Interfaces:**
- Consumes: 없음 ( 표준 라이브러리만 ).
- Produces: `SourceFreshness` dataclass ( `source_id: str`, `last_fetched_at: datetime | None`, `threshold_hours: float`, `age_hours: float | None`, `stale: bool` ) 와
  `evaluate_freshness(watermarks: dict[str, datetime | None], now: datetime, default_hours: float, overrides: dict[str, float] | None = None) -> list[SourceFreshness]`.
  Task 2 가 `SourceFreshness` 를, Task 3 · 4 가 둘 다 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_quality.py` 상단 import 를 교체하고 파일 끝에 테스트를 추가한다.

```python
from datetime import datetime, timedelta
from bullet_in.quality import (success_rate, volume_anomaly, volume_anomalies,
                               Anomaly, evaluate_freshness)
```

```python
_NOW = datetime(2026, 7, 13, 12, 0, 0)


def _wm(hours_ago: float):
    return _NOW - timedelta(hours=hours_ago)


def test_evaluate_freshness_flags_source_over_default_threshold():
    [r] = evaluate_freshness({"bbc_sport": _wm(50)}, _NOW, default_hours=48)
    assert r.stale is True
    assert r.age_hours == 50.0
    assert r.threshold_hours == 48.0
    assert r.last_fetched_at == _wm(50)


def test_evaluate_freshness_quiet_within_threshold():
    [r] = evaluate_freshness({"bbc_sport": _wm(10)}, _NOW, default_hours=48)
    assert r.stale is False


def test_evaluate_freshness_applies_source_override():
    [r] = evaluate_freshness({"x_afcstuff": _wm(30)}, _NOW, default_hours=48,
                             overrides={"x_afcstuff": 24})
    assert r.stale is True
    assert r.threshold_hours == 24.0


def test_evaluate_freshness_null_watermark_recorded_but_not_stale():
    [r] = evaluate_freshness({"new_source": None}, _NOW, default_hours=48)
    assert r.last_fetched_at is None
    assert r.age_hours is None
    assert r.stale is False


def test_evaluate_freshness_exact_threshold_not_stale():
    [r] = evaluate_freshness({"bbc_sport": _wm(48)}, _NOW, default_hours=48)
    assert r.age_hours == 48.0
    assert r.stale is False


def test_evaluate_freshness_empty_input():
    assert evaluate_freshness({}, _NOW, default_hours=48) == []


def test_evaluate_freshness_returns_all_sources_sorted():
    records = evaluate_freshness({"b": _wm(1), "a": None}, _NOW, default_hours=48)
    assert [r.source_id for r in records] == ["a", "b"]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_quality.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate_freshness'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/quality.py` 에 추가한다 ( 기존 코드 무수정 ).
상단 import 에 `from datetime import datetime` 을 더한다.

```python
@dataclass
class SourceFreshness:
    source_id: str
    last_fetched_at: datetime | None
    threshold_hours: float
    age_hours: float | None   # 워터마크 없으면 None
    stale: bool               # 워터마크 없으면 False (알림 제외)


def evaluate_freshness(watermarks: dict[str, datetime | None], now: datetime,
                       default_hours: float,
                       overrides: dict[str, float] | None = None
                       ) -> list[SourceFreshness]:
    overrides = overrides or {}
    out: list[SourceFreshness] = []
    for sid in sorted(watermarks):
        wm = watermarks[sid]
        thr = float(overrides.get(sid, default_hours))
        if wm is None:
            out.append(SourceFreshness(sid, None, thr, None, False))
            continue
        age = (now - wm).total_seconds() / 3600
        out.append(SourceFreshness(sid, wm, thr, age, age > thr))
    return out
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_quality.py -v`
Expected: 전부 PASS ( 기존 volume 테스트 포함 ).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/quality.py tests/test_quality.py
git commit -m "feat(quality): 소스별 신선도 판정 evaluate_freshness

소스가 조용히 죽어도 \"0건 성공\" 으로 넘어가는 사각을 재기 위한
소스별 신선도 판정 순수 함수를 추가한다.

- evaluate_freshness: 워터마크 (MAX(fetched_at)) + DB now → SourceFreshness 목록
- stale 판정: age > threshold 엄격 초과 (경계 동일값은 정상)
- NULL 워터마크 (기사 0건): 행은 남기되 stale False → 신규 소스 오탐 방지
- I/O 없는 순수 함수: 경계 · override · NULL 을 단위 테스트로 고정

Refs: docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 2: `notify.build_freshness_alert` embed 빌더

**Files:**
- Modify: `src/bullet_in/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: Task 1 의 `SourceFreshness` ( `source_id` · `age_hours` · `threshold_hours` 필드만 duck-typing 으로 읽음 ).
- Produces: `build_freshness_alert(breaches: list[SourceFreshness], default_hours: float) -> dict` — `notify.send_alert(**alert)` 로 바로 펼칠 수 있는 dict.
  Task 4 가 사용한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_notify.py` 끝에 추가한다.

```python
def test_build_freshness_alert_formats_lines_and_threshold_field():
    from datetime import datetime, timedelta
    from bullet_in.quality import SourceFreshness

    now = datetime(2026, 7, 13, 12, 0, 0)
    breaches = [
        SourceFreshness("x_afcstuff", now - timedelta(hours=61.4), 24.0, 61.4, True),
        SourceFreshness("bbc_sport", now - timedelta(hours=72), 48.0, 72.0, True)]
    alert = notify.build_freshness_alert(breaches, default_hours=48)
    assert alert["title"] == "🕰️ 신선도 경고 — 오래된 소스"
    assert alert["color"] == notify.COLOR_ANOMALY
    assert "⏳ x_afcstuff: 61.4h 경과 (임계 24h)" in alert["description"]
    assert "⏳ bbc_sport: 72.0h 경과 (임계 48h)" in alert["description"]
    assert alert["fields"][0] == {"name": "기본 임계", "value": "전역 48h",
                                  "inline": True}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: FAIL — `AttributeError: module 'bullet_in.notify' has no attribute 'build_freshness_alert'`

- [ ] **Step 3: 최소 구현**

`src/bullet_in/notify.py` 의 `build_anomaly_alert` 아래에 추가한다.

```python
def build_freshness_alert(breaches, default_hours: float) -> dict:
    lines = "\n".join(
        f"⏳ {b.source_id}: {b.age_hours:.1f}h 경과 (임계 {b.threshold_hours:g}h)"
        for b in breaches)
    return {"title": "🕰️ 신선도 경고 — 오래된 소스", "description": lines,
            "color": COLOR_ANOMALY,
            "fields": [{"name": "기본 임계", "value": f"전역 {default_hours:g}h",
                        "inline": True}]}
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_notify.py -v`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/notify.py tests/test_notify.py
git commit -m "feat(notify): 신선도 경고 Discord embed 빌더

stale 소스 목록을 사람이 바로 읽을 수 있는 경고 embed 로 바꾼다.
SLO-6 과 같은 send_alert 배관을 재사용해 채널 · 규격을 통일한다.

- build_freshness_alert: breaches → embed dict (send_alert(**alert) 호환)
- 라인 형식: 소스별 '⏳ <source>: <age>h 경과 (임계 <thr>h)' 한 줄
- 색상: COLOR_ANOMALY — SLO-6 과 동일한 소프트 경고 톤
- 기본 임계 필드: 전역 임계 병기 → 라인 임계와 다르면 override 식별

Refs: docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 3: `source_freshness` 이력 테이블 · `MartStore` DB 접점

**Files:**
- Modify: `src/bullet_in/storage/schema.sql`
- Modify: `src/bullet_in/storage/mariadb.py`
- Modify: `tests/integration/conftest.py` ( `clean` fixture 에 `source_freshness` 정리 추가 )
- Test: `tests/integration/test_source_freshness.py` ( 신규 )

**Interfaces:**
- Consumes: Task 1 의 `evaluate_freshness` · `SourceFreshness`.
- Produces: `MartStore.source_watermarks() -> dict[str, datetime]` ( 기사 있는 소스만 키 존재 ),
  `MartStore.db_now() -> datetime`,
  `MartStore.record_freshness(run_id: str, checked_at: datetime, records: list[SourceFreshness]) -> None`.
  Task 4 가 사용한다.

- [ ] **Step 1: 실패하는 통합 테스트 작성**

`tests/integration/test_source_freshness.py` 를 생성한다.
`engine` fixture 는 기존 conftest 것을 그대로 쓴다 ( MariaDB 없으면 자동 skip ).

```python
from datetime import datetime
from sqlalchemy import text
from bullet_in.models import Article
from bullet_in.quality import evaluate_freshness
from bullet_in.storage.mariadb import MartStore


def _art(h, url, fetched_at):
    return Article(content_hash=h, url=url, source_id="bbc_sport",
                   title_original="T", fetched_at=fetched_at)


def test_source_watermarks_returns_max_fetched_at(engine):
    store = MartStore(engine)
    store.upsert([_art("h1", "https://x.test/1", datetime(2026, 7, 10, 8, 0)),
                  _art("h2", "https://x.test/2", datetime(2026, 7, 12, 9, 30))])
    wm = store.source_watermarks()
    assert wm["bbc_sport"] == datetime(2026, 7, 12, 9, 30)


def test_db_now_returns_datetime(engine):
    assert isinstance(MartStore(engine).db_now(), datetime)


def test_record_freshness_persists_rows_with_shared_run_id(engine):
    store = MartStore(engine)
    now = store.db_now()
    records = evaluate_freshness({"bbc_sport": None}, now, default_hours=48)
    store.record_freshness("run-1", now, records)
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT run_id, source_id, last_fetched_at, stale "
            "FROM source_freshness")).all()
    assert rows == [("run-1", "bbc_sport", None, 0)]


def test_record_freshness_empty_records_is_noop(engine):
    MartStore(engine).record_freshness("run-1", datetime(2026, 7, 13), [])
    with engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM source_freshness")).scalar_one()
    assert n == 0
```

`tests/integration/conftest.py` 의 `clean` fixture 를 수정한다.

```python
@pytest.fixture(autouse=True)
def clean(engine):
    with engine.begin() as c:
        c.execute(text("DELETE FROM articles"))
        c.execute(text("DELETE FROM source_freshness"))
    yield
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/integration/test_source_freshness.py -v`
Expected: MariaDB 가 있으면 FAIL ( `AttributeError: 'MartStore' object has no attribute 'source_watermarks'` ), 없으면 SKIP.
docker 로 띄워 실제 FAIL 을 확인한다: `docker compose up -d` 후 재실행.

- [ ] **Step 3: 최소 구현**

`src/bullet_in/storage/schema.sql` 끝에 추가한다 ( 파일 끝 `pipeline_runs` 문 뒤에 `;` 로 구분해 append — `ensure_schema()` 가 `;` split 로 실행 ).

```sql
;
CREATE TABLE IF NOT EXISTS source_freshness (
  run_id VARCHAR(64), checked_at DATETIME, source_id VARCHAR(64),
  last_fetched_at DATETIME, age_hours FLOAT, threshold_hours FLOAT,
  stale BOOLEAN,
  PRIMARY KEY (run_id, source_id))
```

`src/bullet_in/storage/mariadb.py` 에 추가한다.
상단에 `from datetime import datetime` 과 `from bullet_in.quality import SourceFreshness` import 를 더하고, 클래스 끝에 메서드 3개를 붙인다.

```python
    def source_watermarks(self) -> dict[str, datetime]:
        """소스별 MAX(fetched_at) 워터마크. 기사 0건 소스는 키가 없다."""
        with self.engine.connect() as c:
            rows = c.execute(text(
                "SELECT source_id, MAX(fetched_at) FROM articles "
                "GROUP BY source_id")).all()
        return {sid: wm for sid, wm in rows}

    def db_now(self) -> datetime:
        with self.engine.connect() as c:
            return c.execute(text("SELECT NOW()")).scalar_one()

    def record_freshness(self, run_id: str, checked_at: datetime,
                         records: list[SourceFreshness]) -> None:
        if not records:  # 빈 executemany 는 SQLAlchemy 가 거부
            return
        with self.engine.begin() as c:
            c.execute(text(
                "INSERT INTO source_freshness (run_id,checked_at,source_id,"
                "last_fetched_at,age_hours,threshold_hours,stale) "
                "VALUES (:rid,:at,:sid,:wm,:age,:thr,:stale)"),
                [{"rid": run_id, "at": checked_at, "sid": r.source_id,
                  "wm": r.last_fetched_at, "age": r.age_hours,
                  "thr": r.threshold_hours, "stale": r.stale}
                 for r in records])
```

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/integration/ -v`
Expected: 신규 4개 포함 전부 PASS ( 기존 통합 테스트 회귀 없음 ).

- [ ] **Step 5: 커밋**

```bash
git add src/bullet_in/storage/schema.sql src/bullet_in/storage/mariadb.py \
        tests/integration/conftest.py tests/integration/test_source_freshness.py
git commit -m "feat(storage): source_freshness 이력 테이블 · 워터마크 조회

회차별 소스 신선도를 남겨 SLO-7 모니터링 뷰의 추세 조회 기반을 만든다.

- schema.sql: source_freshness 테이블 (PK run_id + source_id) —
  CREATE TABLE IF NOT EXISTS 멱등 적용, 수동 마이그레이션 없음
- source_watermarks: 소스별 MAX(fetched_at) 조회
- db_now: DB SELECT NOW() — DB 측 워터마크와 TZ · 시계 불일치 제거
- record_freshness: 판정 레코드 전량 append (빈 목록 no-op)
- 통합 테스트: 기존 engine fixture skip 규약 (MariaDB 없으면 skip)

Refs: docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 4: config 임계 키 · run.py 연결 ( run_id 공유 리팩터 )

**Files:**
- Modify: `config/sources.yaml`
- Modify: `src/bullet_in/run.py`

**Interfaces:**
- Consumes: Task 1 `evaluate_freshness` · Task 2 `build_freshness_alert` · Task 3 `MartStore` 메서드 3종.
- Produces: 없음 ( 종단 연결 ).

- [ ] **Step 1: config 임계 키 추가**

`config/sources.yaml` 최상단 ( `sources:` 위 ) 에 전역 키를 추가한다.

```yaml
freshness_default_hours: 48   # SLO-5 신선도 전역 임계 (h)
```

`x_afcstuff` 항목의 `fallback_tier: 4` 아래에 override 를 추가한다.

```yaml
    freshness_hours: 24   # X 는 고빈도 소스 — 전역 48h 보다 좁게 감시
```

- [ ] **Step 2: run.py 수정**

import 라인을 교체한다.

```python
from bullet_in.quality import success_rate, volume_anomalies, evaluate_freshness
```

`main()` 첫 줄에 run_id 를 1회 생성한다.

```python
async def main(concurrency: int):
    run_id = str(uuid.uuid4())
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
```

SLO-6 anomaly 블록 ( `if anomalies:` 문 ) 바로 아래에 추가한다.
`sources` 는 `load_sources` 가 enabled 소스만 담으므로 비활성 · config 제거 소스는 자동 제외된다.

```python
    # 신선도 워터마크 감시 (SLO-5): 소스별 MAX(fetched_at) 경과가 임계 초과면 알림
    default_hours = cfg.get("freshness_default_hours", 48)
    overrides = {sid: float(s["freshness_hours"])
                 for sid, s in sources.items() if "freshness_hours" in s}
    checked_at = mart.db_now()
    wm = mart.source_watermarks()
    records = evaluate_freshness({sid: wm.get(sid) for sid in sources},
                                 checked_at, default_hours, overrides)
    mart.record_freshness(run_id, checked_at, records)
    breaches = [r for r in records if r.stale]
    if breaches:
        notify.send_alert(**notify.build_freshness_alert(breaches, default_hours))
```

`pipeline_runs` INSERT 의 인라인 생성을 공유 run_id 로 교체한다.

```python
            {"rid": run_id,
```

( 기존 `{"rid": str(uuid.uuid4()),` 줄을 위처럼 바꾼다. `uuid` import 는 main 상단 생성이 계속 쓰므로 유지. )

- [ ] **Step 3: 검증**

run.py 는 DB · Gemini 없이는 실행할 수 없으므로 구문 · 계약 수준으로 확인한다.

Run: `uv run python -m py_compile src/bullet_in/run.py && uv run python -c "import yaml; cfg = yaml.safe_load(open('config/sources.yaml')); assert cfg['freshness_default_hours'] == 48; assert [s for s in cfg['sources'] if s['source_id'] == 'x_afcstuff'][0]['freshness_hours'] == 24; print('config ok')"`
Expected: `config ok`

Run: `uv run pytest -q`
Expected: 전체 스위트 PASS ( DB 없는 환경이면 integration 은 skip ).
`load_sources` 는 plain dict 반환이라 신규 키로 깨지는 소비자가 없다 ( `test_score.py` 포함 확인 ).

- [ ] **Step 4: 커밋**

```bash
git add config/sources.yaml src/bullet_in/run.py
git commit -m "feat(run): SLO-5 신선도 감시 연결 · run_id 공유 리팩터

수집이 끊긴 소스를 회차마다 자동으로 잡아내도록 종단을 잇는다.

- run.py: 서빙 후 SLO-6 인접에서 판정 → source_freshness 전량 기록
  → stale 있을 때만 Discord 알림
- run_id: pipeline_runs 인라인 생성 → main 상단 1회 생성 리팩터
  (source_freshness 와 회차 식별자 공유)
- config: freshness_default_hours 48 전역 + x_afcstuff 24h override
  (X 는 고빈도 소스라 좁게 감시)
- 비활성 소스: load_sources 가 enabled 만 반환 → 유령 알림 없음

Refs: docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Sonnet 5 (구현) <noreply@anthropic.com>"
```

---

### Task 5: 신선도 알림 운영 런북

**Files:**
- Create: `docs/runbook/2026-07-13-freshness-watermark-ops.md`

**Interfaces:**
- Consumes: Task 1–4 의 최종 동작 ( 알림 형식 · config 키 · 테이블 ).
- Produces: 운영 문서 ( 코드 의존 없음 ).

트러블슈팅 문서는 이번에 만들지 않는다.
이 repo 의 troubleshooting 은 실제 발생한 함정의 기록이며 ( SLO-6 의 예외 삼킴 갭처럼 ), 구현 중 실제 갭이 드러나면 그때 추가한다.
런북이 spec §2.1 진단표 확장과 임계 조정 가이드를 모두 담는다.

- [ ] **Step 1: 런북 작성**

아래 전문을 그대로 저장한다 ( §2.2 서식 훅 통과 필수 ).

````markdown
# 신선도 워터마크 알림 운영 (2026-07-13)

## 목적

소스가 조용히 죽어도 파이프라인은 "0건 성공" 으로 넘어가는 사각을 메우는 SLO-5 신선도 감시의 해석 · 대응 · 임계 조정 · 롤백을 정리.

- 감시 신호 — 소스별 `MAX(fetched_at)` 워터마크의 경과 시간이 임계 ( 전역 48h · 소스별 override ) 를 초과하면 Discord 알림.
- SLO-6 과의 분담 — SLO-6 은 회차 단위 수집량 급변 ( 건수 ), SLO-5 는 누적 무소식 ( 시간 ) 을 본다.
  저빈도라 min_baseline 에 걸러지는 소스도 SLO-5 는 잡는다.
- 이력 — 매 회차 소스별 한 행을 `source_freshness` 에 남긴다 ( SLO-7 모니터링 뷰 기반 ).

## 알림 해석

- **🕰️ 신선도 경고 (주황)** — stale 소스가 하나라도 있으면 한 embed 로 묶여 온다.
  라인 예: `⏳ x_afcstuff: 61.4h 경과 (임계 24h)`.
  `기본 임계` 필드 ( `전역 48h` ) 와 라인의 임계가 다르면 그 소스는 override 적용 상태다.
- **무알림** — 모든 소스가 임계 안이거나, 워터마크 자체가 없는 소스뿐인 경우.
  워터마크 없음 ( 기사 0건 ) 은 "신규 추가" 와 "처음부터 죽음" 을 구분할 수 없어 알림에서 제외한다 — 이 케이스는 SLO-6 · 에러 로그가 담당.

## 대응 — 원인 → 처방 진단표

알림은 "무엇이 오래됐는지" 만 말한다.
원인은 아래 순서로 좁힌다.

| 원인 | 확인 방법 | 처방 |
|---|---|---|
| 셀렉터 드리프트 ( 사이트 개편 ) | 어댑터 단독 `fetch()` 라이브 실행 → 0건이면 `list_url` 을 브라우저로 열어 구조 대조 | `config/sources.yaml` 셀렉터 수정 · `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` |
| 피드 · 검색 URL 변경 | `list_url` · `search_url` 직접 접속 → 404 · 리다이렉트 확인 | `feed_url` · `list_url` 갱신 |
| X 쿠키 만료 | 파이프라인 로그의 x_playwright 로그인 오류 · `x_cookies.json` 수정 시각 | 쿠키 재주입 — `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md` |
| 기자 계정 이전 · 핸들 변경 | X 에서 해당 핸들 직접 확인 | `config/sources.yaml` 의 `handle` · 팔로우 대상 갱신 |
| 소스가 진짜 조용 ( 오프시즌 ) | 원문 사이트에 실제로 새 글이 없음 | 조치 없음 — 정상. 반복되면 임계 상향 검토 ( 아래 ) |

- 라이브 검증이 우선이다.
  단위 테스트는 모킹이라 드리프트를 못 잡는다 ( CLAUDE.md "자주 밟는 함정" ).

## 임계 조정 가이드

임계는 `config/sources.yaml` 에서만 조정한다 ( 코드 무수정 ).

- **전역 `freshness_default_hours: 48`** — 파이프라인이 6 시간 간격 4 회/일 돌므로 48h = 8 회차 연속 무신규.
  일반 언론 소스의 주말 · 뉴스 공백을 견디는 보수적 기본값이다.
- **소스별 `freshness_hours` override** — 소스 항목에 키를 추가하면 그 소스만 좁아진다.
  현재 `x_afcstuff: 24` ( X aggregator 는 매일 다건 포스팅 → 24h 무소식이면 이상 ).
- **오탐이 잦으면** — 해당 소스의 실제 발행 간격을 `source_freshness` 이력으로 확인하고 override 를 늘린다.
  `SELECT source_id, MAX(age_hours) FROM source_freshness GROUP BY source_id` 로 평시 최대 경과를 본다.
- **오프시즌** — 이적 뉴스 소스는 시즌 중 대비 확연히 뜸해진다.
  반복 오탐 시 전역을 올리기보다 뜸한 소스만 override ( 예: 72–96h ) 를 준다.

## 검증

webhook · DB 없이도 판정 · 포맷 로직을 확인할 수 있다.

```bash
uv run pytest tests/test_quality.py -v                       # evaluate_freshness 경계 · override · NULL
uv run pytest tests/test_notify.py -v                        # build_freshness_alert 포맷
uv run pytest tests/integration/test_source_freshness.py -v  # 테이블 적재 (MariaDB 필요 · 없으면 skip)
```

## 실패 모드

- **알림 실패 무해** — `send_alert` 가 모든 예외를 삼켜 파이프라인을 죽이지 않는다 ( `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` ).
- **워터마크 없음 무알림** — 기사 0건 소스는 행만 남고 조용하다.
  신규 소스를 붙였는데 며칠째 `last_fetched_at` 이 NULL 이면 어댑터 자체가 죽은 것 — SLO-6 드롭 알림 · 에러 로그를 본다.
- **DB 시계 기준** — `age_hours` 는 DB `NOW()` 기준이라 앱 서버 시계와 무관하다.
  컨테이너 TZ 를 바꿔도 판정이 흔들리지 않는다.

## 롤백

- 기능 제거는 `git revert` 로 충분하다.
  `source_freshness` 는 append 전용 이력이라 남아 있어도 무해하고, 테이블 자체도 `CREATE TABLE IF NOT EXISTS` 라 재적용 충돌이 없다.
- 알림만 임시로 끄려면 `DISCORD_WEBHOOK_URL` 을 해제한다 ( WARNING 로깅 폴백 ).
  감시 · 이력 적재는 계속 돈다.

## 참고

- spec · plan: `docs/superpowers/{specs,plans}/2026-07-13-slo5-freshness-watermark*`.
- SLO-6 알림 운영: `docs/runbook/2026-07-13-collection-alerts-ops.md`.
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ( Tier 3 · SLO-5 ).
````

- [ ] **Step 2: 서식 훅 통과 확인**

Run: `uv run python .claude/hooks/check-doc-format.py docs/runbook/2026-07-13-freshness-watermark-ops.md 2>/dev/null || echo "훅은 PostToolUse 로 자동 실행 — Write 시 통과 여부 확인"`
Expected: 훅 위반 없음 ( Write 시 훅이 차단하지 않음 ).

- [ ] **Step 3: 커밋**

```bash
git add docs/runbook/2026-07-13-freshness-watermark-ops.md
git commit -m "docs(runbook): 신선도 워터마크 알림 운영 런북

SLO-6 때 문서가 별도 PR (#35) 로 밀렸던 선례를 피해 코드와 같은
PR 에 운영 문서를 담는다.

- 알림 해석: embed 라인 · override 식별 · 무알림 케이스 (NULL 워터마크)
- 대응: spec §2.1 원인 → 처방 진단표 확장 (확인 방법 컬럼 추가)
- 임계 조정: 전역 48h 근거 · 소스별 override · 오프시즌 가이드
- 실패 모드 · 롤백: 알림 실패 무해 · append 전용 테이블 revert 안전

Refs: docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md

Co-Authored-By: Claude Fable 5 (설계) <noreply@anthropic.com>
Co-Authored-By: Claude Haiku 4.5 (구현) <noreply@anthropic.com>"
```

---

### Task 6: 최종 검증 · squash PR

**Files:**
- 변경 없음 ( 검증 · PR 생성만 ).

- [ ] **Step 1: 전체 스위트 · 통합 검증**

Run: `docker compose up -d && uv run pytest -q`
Expected: 전부 PASS ( MariaDB 기동으로 integration 포함 ).

- [ ] **Step 2: verification-before-completion**

superpowers:verification-before-completion 스킬로 성공 주장 전 증거를 확인한다.

- [ ] **Step 3: PR head 확인 후 squash PR**

- push 후 PR 본문은 7섹션 한국어 구조 · `--body-file` · Claude 서명 금지 ( 컨벤션 §2.7 ).
- 머지 전 PR head 가 마지막 커밋까지 갱신됐는지 확인한다 ( SLO-6 에서 옛 head squash 누락 실제 발생 ).

```bash
git push -u origin feat/slo5-freshness-watermark
gh pr create --title "feat(quality): SLO-5 신선도 워터마크 감시 · 오래된 소스 Discord 알림" --body-file /tmp/pr-body.md
gh pr view --json headRefOid   # 로컬 HEAD 와 일치 확인 후 squash merge
```
