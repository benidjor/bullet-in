# 회차를 Airflow 로 옮기는 구현 계획 (2026-09-04)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 3시간 회차를 Airflow DAG 하나 (태스크 여덟) 로 옮기되, systemd 가 주던 성질 셋 (밀린 회차 보정 · 실패 알림 · 회차 시작과 끝의 배포 훅) 을 잃지 않는다.

**Architecture:** 회차 본체 `run.py` 를 단계 함수 넷 (collect · enrich · publish · gate) 으로 갈라 `--stage` 로 하나씩 부를 수 있게 하고, 수집 값은 회차 행 (`pipeline_runs`) 으로 단계 사이를 건넌다.
DAG 는 태스크 전부를 셸 호출로 두어 Airflow 의존과 프로젝트 의존을 섞지 않고, 게이트 급사 (종료 코드 3) 를 「건너뜀」 에 대응시켜 배포 자동화의 판정기가 입력만 바꿔 그대로 산다.
Airflow 는 프로젝트와 다른 venv 에 두고 systemd 유닛 셋으로 띄우며, 오케스트레이터 자체의 생존은 새 타이머 하나가 본다.

**Tech Stack:** Python 3.11 · uv · Apache Airflow 3.3.1 (LocalExecutor · BashOperator · Postgres 16 메타데이터) · systemd · docker compose · MariaDB 11 · dbt · pytest

**Spec:** `docs/superpowers/specs/2026-09-04-airflow-migration-design.md`

## Global Constraints

- 파이썬 3.11 고정 (프로젝트 · VM · CI 전부 3.11.15) · 워크트리 venv 는 `uv venv --python 3.11 --project <워크트리>` · 테스트는 `uv run --project <워크트리> --extra dev pytest -q`.
- Airflow 는 프로젝트 venv 에 설치하지 않는다 (스펙 §3.4 · 런북 2026-05-27) · VM 의 `/home/ubuntu/airflow-venv` 와 로컬 검증용 일회 venv 에만.
- Airflow 버전 = 3.3.1 (2026-09-04 PyPI 최신) · constraints = `https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt` · 태스크 0 에서 설치가 안 되면 3.1.6 으로 내린다.
- 이중 실행 금지 — systemd 회차 · 웨어하우스 타이머를 먼저 끄고 DAG 를 활성화한다 (스펙 §8).
- 세션은 VM 에서 `git pull` 을 치지 않는다 · 머지된 코드는 회차가 스스로 반영한다 (스펙 2026-09-03).
- `decide` · `rollback` · 배포 알림 서식은 바꾸지 않는다 (스펙 §6.3).
- 문서는 컨벤션 §2.2 서식 · `docs/` 는 서술형 · PR 본문은 명사형 · 트러블슈팅 · 런북 · PR 본문은 humanize fast 1회.
- 커밋 = `<type>(<scope>): 한국어 제목` + 도입 + 명사형 불릿 + `Refs:` + co-author 트레일러 (실제 작업 모델).
- 범위 밖 = 워치리스트 · 백업 · 유지보수의 이관 · 화면 외부 공개 · Airflow 업그레이드 자동화 · 2ν 원인 · `run.py` 의 다른 정리.

---

## 파일 구조

| 파일 | 책임 | 태스크 |
| --- | --- | --- |
| `src/bullet_in/run.py` | 단계 함수 넷 · `FetchSummary` · `--stage` CLI · `main` 은 넷을 차례로 | 1 |
| `src/bullet_in/storage/schema.sql` | `pipeline_runs.fetch_detail JSON` | 1 |
| `tests/test_run_stages.py` | `FetchSummary` 왕복 · CLI · 단계 순서 | 1 |
| `tests/integration/test_pipeline_runs_insert.py` | 두 단계 기록 (삽입 · 마감) | 1 |
| `src/bullet_in/dbt_gate.py` | 신호 종료일 때만 dbt 를 한 번 더 | 2 |
| `tests/test_dbt_gate.py` | 급사 재시도 세 갈래 | 2 |
| `src/bullet_in/deploy.py` | `airflow_inputs` · `parse_task_states` · `judge --from-airflow` | 3 |
| `tests/test_deploy.py` | 대응표 세 갈래 · CLI | 3 |
| `src/bullet_in/notify.py` | `build_task_failure_alert(payload)` · `python -m bullet_in.notify task-failure` | 4 |
| `airflow/dags/bullet_in_cycle.py` | DAG 하나 · 태스크 여덟 · 전부 셸 호출 (구 `bullet_in_daily.py` 삭제) | 4 |
| `airflow/requirements.txt` | 3.3.1 | 4 |
| `tests/test_dag_import.py` | 구조 검증 (격리 venv 에서만 돈다) | 4 |
| `docker-compose.yml` | `airflow-db` (Postgres 16 · 127.0.0.1:5433) | 5 |
| `infra/airflow/airflow.env` · `install-airflow.sh` | 설치 · 설정 | 5 |
| `infra/systemd/airflow-*.service` · `bullet-in-airflow-watch.*` · `install-units.sh` | 유닛 넷 | 5 |
| `src/bullet_in/airflow_watch.py` · `tests/test_airflow_watch.py` | 생존 감시 두 축 · 재알림 억제 | 5 |
| `src/bullet_in/backup.py` · `tests/test_backup.py` | `airflow.sql.gz` 한 파일 더 | 6 |
| `docs/…` 열 · 새 런북 하나 | 스펙 §11 | 7 |

PR 은 셋으로 자른다.

- **PR A = 태스크 1 · 2 · 3** — systemd 경로에서 그대로 도는 코드 변경.
  머지되면 다음 회차가 스스로 반영하고 판정한다.
  단계 분리가 systemd 회차에서 먼저 살아 도는 것이 가장 싼 통합 검증이다.
- **PR B = 태스크 4 · 5 · 6** — DAG · 인프라 · 감시 · 백업.
  VM 에 Airflow 를 깔기 전에는 아무 것도 돌지 않는다 (compose 의 `airflow-db` 만 다음 회차의 `docker compose up` 에서 뜬다).
- **PR C = 태스크 7** — 문서.
  태스크 8 (VM 설치 · 리허설 · 전환) 의 실측을 담아 마지막에 낸다.

태스크 0 은 코드 0줄이고 결과를 PR A 본문 §4 와 메모리 트랙에 적는다.

---

### Task 0: 착수 전 실물 검증 넷 (스펙 §9.1)

**Files:**
- 없음 (VM 의 `/tmp/af-probe` 에서만 · 끝나면 지운다)

**Interfaces:**
- Produces: 아래 표의 답 넷 · 하나라도 「아니오」 면 이 계획을 멈추고 스펙으로 돌아간다

- [ ] **Step 1: VM 에 일회 venv 로 Airflow 3.3.1 을 깐다 (시간과 성공 여부를 잰다)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
set -e
rm -rf /tmp/af-probe && mkdir -p /tmp/af-probe && cd /tmp/af-probe
~/.local/bin/uv venv --python 3.11 venv
time ~/.local/bin/uv pip install --python venv/bin/python \
  "apache-airflow==3.3.1" "apache-airflow-providers-standard" "psycopg2-binary" \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt
venv/bin/airflow version
EOF
```

Expected: `3.3.1` 이 찍힌다.
안 깔리면 (휠 없음 · 해석 실패) 3.1.6 과 그 constraints 로 한 번 더 시도하고, 그것도 안 되면 멈춘다.

- [ ] **Step 2: `skip_on_exit_code` · 콜백 컨텍스트 키 · CLI 출력 형식을 확인한다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
cd /tmp/af-probe
venv/bin/python - <<'PY'
import inspect
from airflow.providers.standard.operators.bash import BashOperator
sig = inspect.signature(BashOperator.__init__)
print("skip_on_exit_code:", "skip_on_exit_code" in sig.parameters)
PY
# 콜백 컨텍스트가 log_url · try_number 를 주는지 — 소스에서 찾는다
grep -rn "log_url" venv/lib/python3.11/site-packages/airflow/sdk/definitions/context.py venv/lib/python3.11/site-packages/airflow/sdk/execution_time/task_runner.py 2>/dev/null | head -5
grep -rn "def get_task_states" venv/lib/python3.11/site-packages/airflow/sdk/ 2>/dev/null | head -3
venv/bin/airflow tasks states-for-dag-run --help | head -20
EOF
```

Expected: `skip_on_exit_code: True` · `log_url` 이 컨텍스트 소스에 있다 · `states-for-dag-run` 이 `-o json` 을 받는다.
`get_task_states` 는 있으면 좋고 없어도 된다 (판정은 CLI 로 한다 · §Task 4).

- [ ] **Step 3: 상주 메모리를 잰다 (SQLite 로 60초만 띄운다 · 운영 설정이 아니다)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
cd /tmp/af-probe
export AIRFLOW_HOME=/tmp/af-probe/home AIRFLOW__CORE__LOAD_EXAMPLES=False
venv/bin/airflow db migrate >/dev/null 2>&1
venv/bin/airflow scheduler >/dev/null 2>&1 & S=$!
venv/bin/airflow dag-processor >/dev/null 2>&1 & D=$!
venv/bin/airflow api-server --port 18080 >/dev/null 2>&1 & A=$!
sleep 60
ps -o rss=,comm= -p $S $D $A $(pgrep -P $S) $(pgrep -P $D) $(pgrep -P $A) 2>/dev/null | awk '{s+=$1; print} END {print "TOTAL_MB", s/1024}'
kill $S $D $A; sleep 3; pkill -f af-probe || true
EOF
```

Expected: `TOTAL_MB` 가 1,500 아래.
1,500 을 넘으면 스펙 §1.3 의 여유 (11Gi) 로는 여전히 되지만 §4.1 의 `parallelism` 을 1 로 낮추고 이 값을 스펙 §1.3 에 적는다.

- [ ] **Step 4: 관리자 계정 방식을 확인한다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
cd /tmp/af-probe
venv/bin/airflow config get-value core simple_auth_manager_users 2>/dev/null || echo "(키 없음)"
venv/bin/airflow config get-value core auth_manager
ls home/ | grep -i password || true
EOF
```

Expected: `auth_manager` 가 `SimpleAuthManager` 이고 `simple_auth_manager_users` 가 `admin:admin` 꼴이며, 비밀번호 파일 (`simple_auth_manager_passwords.json.generated`) 이 첫 기동에 생긴다.
다르면 태스크 5 의 `airflow.env` 에서 계정 줄을 그 방식으로 바꾼다.

- [ ] **Step 5: 정리하고 답 넷을 적는다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'rm -rf /tmp/af-probe'
```

| 물음 | 답 | 근거 (출력 발췌) |
| --- | --- | --- |
| 3.3.1 이 arm64 · 3.11 에 constraints 로 깔리는가 · 소요 | | |
| `skip_on_exit_code` 가 있는가 | | |
| 콜백 컨텍스트에 `log_url` · `try_number` 가 있는가 · `states-for-dag-run -o json` 형식 | | |
| 상주 메모리 (MB) | | |
| 관리자 계정 방식 | | |

이 표를 메모리 `airflow-migration-design-track-2026-09-04` 에 옮겨 적고 PR A 본문 §4 에도 싣는다.

---

### Task 1: 회차 본체를 단계 함수 넷으로 가른다

**Files:**
- Modify: `src/bullet_in/run.py` (`RUN_INSERT_SQL` 49-54 · `main` 233-584 · `__main__` 585-588)
- Modify: `src/bullet_in/storage/schema.sql:55-57` 근처에 `fetch_detail` 한 줄
- Modify: `tests/integration/test_pipeline_runs_insert.py`
- Test: `tests/test_run_stages.py` (신규)

**Interfaces:**
- Produces: `FetchSummary` (dataclass) · `collect(run_id, concurrency) -> FetchSummary` (async) · `enrich(run_id) -> None` · `publish(run_id) -> None` · `gate(run_id) -> None` · `run_stage(stage, run_id, concurrency) -> None` · `STAGES = ("collect", "enrich", "publish", "gate")` · CLI `python -m bullet_in.run --stage <이름> --run-id <값>`
- Produces: SQL 상수 `RUN_INSERT_SQL` (마감 열 없음 · `fetch_detail` 추가) · `RUN_FINISH_SQL` · `RUN_SELECT_SQL` · `VOLUME_HISTORY_SQL`
- Consumes: 지금 `main` 의 코드 전부 (옮기기만 한다 · 로직 무변경)

- [ ] **Step 1: `FetchSummary` 왕복 · CLI · 단계 순서 테스트를 쓴다**

`tests/test_run_stages.py`:

```python
"""회차 본체의 단계 분리 (스펙 2026-09-04 §5) — 수집 값은 회차 행으로 단계 사이를 건넌다."""
import json
from datetime import datetime

import pytest

from bullet_in import run as run_mod
from bullet_in.run import FetchSummary, STAGES, run_stage


def _summary(**over):
    base = dict(run_id="r1", started_at_utc=datetime(2026, 9, 4, 3, 0, 0), fetch_sec=7.5,
                source_counts={"bbc_sport": 2}, candidate_counts={"bbc_sport": 4},
                new_count=2, dup_count=1, blocked_count=0,
                errors={"fmkorea": "HTTP 430"}, funnels={"fmkorea": {"found": 15}},
                success_rate=0.9)
    base.update(over)
    return FetchSummary(**base)


def test_fetch_summary_roundtrips_through_row_params():
    s = _summary()
    params = s.to_params(dag_run_id="manual")
    assert params["rid"] == "r1" and params["drid"] == "manual"
    assert json.loads(params["detail"]) == {"errors": {"fmkorea": "HTTP 430"},
                                            "funnels": {"fmkorea": {"found": 15}}}
    # DB 가 돌려주는 모양 — JSON 열은 문자열로 온다
    row = {"run_id": "r1", "started_at": s.started_at_utc, "fetch_duration_sec": 7.5,
           "source_counts": params["counts"], "candidate_counts": params["cands"],
           "new_count": 2, "dup_count": 1, "blocked_count": 0, "error_count": 1,
           "success_rate": 0.9, "fetch_detail": params["detail"]}
    assert FetchSummary.from_row(row) == s


def test_fetch_summary_tolerates_missing_detail():
    row = {"run_id": "r1", "started_at": datetime(2026, 9, 4), "fetch_duration_sec": 1.0,
           "source_counts": "{}", "candidate_counts": None, "new_count": 0, "dup_count": 0,
           "blocked_count": None, "error_count": 0, "success_rate": 1.0, "fetch_detail": None}
    s = FetchSummary.from_row(row)
    assert s.errors == {} and s.funnels == {} and s.candidate_counts == {} and s.blocked_count == 0


def test_stage_order_is_fixed():
    assert STAGES == ("collect", "enrich", "publish", "gate")


def test_run_stage_dispatches_one_stage_only(monkeypatch):
    calls = []
    async def fake_collect(run_id, concurrency):
        calls.append(("collect", run_id, concurrency))
    monkeypatch.setattr(run_mod, "collect", fake_collect)
    monkeypatch.setattr(run_mod, "enrich", lambda run_id: calls.append(("enrich", run_id)))
    monkeypatch.setattr(run_mod, "publish", lambda run_id: calls.append(("publish", run_id)))
    monkeypatch.setattr(run_mod, "gate", lambda run_id: calls.append(("gate", run_id)))
    run_stage("collect", "r1", 8)
    run_stage("gate", "r1", 8)
    assert calls == [("collect", "r1", 8), ("gate", "r1")]


def test_run_stage_rejects_unknown_stage():
    with pytest.raises(ValueError):
        run_stage("render", "r1", 8)


async def test_main_runs_the_four_stages_in_order_with_one_run_id(monkeypatch):
    seen = []
    async def fake_collect(run_id, concurrency):
        seen.append(("collect", run_id))
    monkeypatch.setattr(run_mod, "collect", fake_collect)
    for name in ("enrich", "publish", "gate"):
        monkeypatch.setattr(run_mod, name,
                            lambda run_id, _n=name: seen.append((_n, run_id)))
    await run_mod.main(concurrency=3)
    assert [s for s, _ in seen] == list(STAGES)
    assert len({r for _, r in seen}) == 1


def test_cli_requires_run_id_with_stage():
    with pytest.raises(SystemExit):
        run_mod.parse_args(["--stage", "collect"])
    ns = run_mod.parse_args(["--stage", "collect", "--run-id", "abc"])
    assert (ns.stage, ns.run_id, ns.concurrency) == ("collect", "abc", 8)
    assert run_mod.parse_args([]).stage is None
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_run_stages.py -q`
Expected: `ImportError: cannot import name 'FetchSummary'`

- [ ] **Step 3: SQL 상수 넷과 `FetchSummary` 를 `run.py` 에 넣는다**

`RUN_INSERT_SQL` (49-54줄) 을 다음 넷으로 바꾼다.
`CANDIDATE_HISTORY_SQL` 은 그대로 둔다 (절벽 판정은 삽입 앞에 돈다).

```python
# 회차 행은 두 단계로 적는다 (스펙 2026-09-04 §5.3) — collect 가 수집 값을 넣고 publish 가 마감한다.
# started_at 은 Python UTC 바인딩 · finished_at 은 UTC_TIMESTAMP() — 세션 TZ 무관 (spec §5)
RUN_INSERT_SQL = (
    "INSERT INTO pipeline_runs (run_id,dag_run_id,started_at,fetch_duration_sec,"
    "source_counts,candidate_counts,new_count,dup_count,blocked_count,error_count,"
    "success_rate,fetch_detail) "
    "VALUES (:rid,:drid,:started,:fetch,:counts,:cands,:new,:dup,:blocked,:err,:sr,:detail)")
RUN_FINISH_SQL = ("UPDATE pipeline_runs SET finished_at=UTC_TIMESTAMP(), duration_sec=:dur "
                  "WHERE run_id=:rid")
RUN_SELECT_SQL = (
    "SELECT run_id,started_at,fetch_duration_sec,source_counts,candidate_counts,new_count,"
    "dup_count,blocked_count,error_count,success_rate,fetch_detail "
    "FROM pipeline_runs WHERE run_id=:rid")
# SLO-6 이력 — 이번 행이 이미 들어가 있으므로 자기 run_id 를 뺀다.
VOLUME_HISTORY_SQL = ("SELECT source_counts FROM pipeline_runs WHERE run_id <> :rid "
                      "ORDER BY started_at DESC LIMIT 12")
```

`FMKOREA_SERVING_SINCE` 정의 바로 뒤 (121줄 뒤) 에 dataclass 를 더한다.
`from dataclasses import dataclass, field` 를 import 줄에 더한다.

```python
@dataclass
class FetchSummary:
    """수집 단계가 남기고 publish 가 되읽는 값 여덟 (스펙 2026-09-04 §1.2 · §5.3).

    메모리로 넘기지 않고 회차 행에 적는 이유는 단계 함수가 Airflow 없이도 같은 길로
    값을 받게 하기 위해서다 (§3.4)."""
    run_id: str
    started_at_utc: datetime
    fetch_sec: float
    source_counts: dict
    candidate_counts: dict
    new_count: int
    dup_count: int
    blocked_count: int
    errors: dict[str, str]
    funnels: dict
    success_rate: float

    def to_params(self, *, dag_run_id: str) -> dict:
        return {"rid": self.run_id, "drid": dag_run_id, "started": self.started_at_utc,
                "fetch": self.fetch_sec,
                "counts": json.dumps(self.source_counts),
                "cands": json.dumps(self.candidate_counts),
                "new": self.new_count, "dup": self.dup_count, "blocked": self.blocked_count,
                "err": len(self.errors), "sr": self.success_rate,
                "detail": json.dumps({"errors": self.errors, "funnels": self.funnels},
                                     ensure_ascii=False)}

    @classmethod
    def from_row(cls, row) -> "FetchSummary":
        def _j(v):
            return json.loads(v) if isinstance(v, (str, bytes)) else (v or {})
        detail = _j(row.get("fetch_detail"))
        return cls(run_id=row["run_id"], started_at_utc=row["started_at"],
                   fetch_sec=float(row["fetch_duration_sec"] or 0.0),
                   source_counts=_j(row.get("source_counts")),
                   candidate_counts=_j(row.get("candidate_counts")),
                   new_count=int(row.get("new_count") or 0),
                   dup_count=int(row.get("dup_count") or 0),
                   blocked_count=int(row.get("blocked_count") or 0),
                   errors=dict(detail.get("errors") or {}),
                   funnels=dict(detail.get("funnels") or {}),
                   success_rate=float(row.get("success_rate") or 0.0))
```

- [ ] **Step 4: `schema.sql` 에 열을 더한다**

`ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS candidate_counts JSON;` (57줄) 바로 뒤에 한 줄.

```sql
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS fetch_detail JSON;
```

- [ ] **Step 5: `main` 을 단계 함수 넷으로 가른다**

지금 `main` (233-584줄) 의 본문을 아래 다섯 함수로 옮긴다.
**옮기는 블록은 한 글자도 고치지 않는다.**
바뀌는 것은 (a) 각 함수 머리의 재료 준비 (b) 회차 행 삽입 · 마감 자리 (c) SLO-6 이력 조회 (d) `summary` 의 계산 셋뿐이다.

```python
def _materials():
    """단계마다 자기 재료를 만든다 (스펙 §5.1). 지금 main 의 첫 아홉 줄과 같다."""
    cfg = yaml.safe_load(Path("config/sources.yaml").read_text())
    sources = load_sources("config/sources.yaml")
    registry = load_registry("config/credibility.yaml")
    engine = create_engine(os.environ["MARIADB_URL"])
    mart = MartStore(engine)
    mart.ensure_schema()
    pstore = PlayerStore(engine)
    return cfg, sources, registry, engine, mart, pstore


async def collect(run_id: str, concurrency: int) -> FetchSummary:
    """수집 · 원본 저장 · 마트 upsert · 회차 행 삽입 (§3.2 표의 첫 행)."""
    cfg, sources, registry, engine, mart, pstore = _materials()
    # ── 여기부터 지금 main 의 244줄 (adapters = build_adapters(...)) 에서
    #    305줄 (mart.upsert(arts)) 까지를 그대로 옮긴다 ──
    ...
    # ── 옮긴 블록 끝 · 아래가 새 줄 ──
    summary = FetchSummary(
        run_id=run_id, started_at_utc=started_at_utc, fetch_sec=fetch_sec,
        source_counts=stats["source_counts"], candidate_counts=candidate_counts,
        new_count=len(arts), dup_count=stats["dup_count"],
        blocked_count=stats["blocked_count"], errors=errors,
        funnels=adapter_funnels(adapters),
        success_rate=success_rate(len(adapters), len(errors)))
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL),
                  summary.to_params(dag_run_id=os.environ.get("AIRFLOW_CTX_DAG_RUN_ID", "manual")))
    return summary


def enrich(run_id: str) -> None:
    """번역 · 재작성 게이트 · 선수 추출 · 관측 · 분류 · 말투 백필 (§3.2 표의 둘째 행)."""
    cfg, sources, registry, engine, mart, pstore = _materials()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    # ── 지금 main 의 308줄 (from bullet_in.enrich import ...) 에서
    #    465줄 (말투 백필 로그) 까지를 그대로 옮긴다 ──
    ...


def publish(run_id: str) -> None:
    """서빙 렌더 · SLO 관측 · 회차 행 마감 · 운영 화면 · 표지 (§3.2 표의 셋째 행)."""
    cfg, sources, registry, engine, mart, pstore = _materials()
    adapters = build_adapters(cfg, fmkorea_player_names=pstore.confirmed_ko_names())
    mongo = MongoClient(os.environ["MONGO_URI"])[os.environ.get("MONGO_DB", "bulletin")]
    rawstore = RawStore(mongo)
    with engine.connect() as c:
        row = c.execute(text(RUN_SELECT_SQL), {"rid": run_id}).mappings().one()
    fetched = FetchSummary.from_row(row)
    t0 = time.perf_counter()
    # ── 지금 main 의 467줄 (with engine.connect() as c: rows = ...) 에서
    #    573줄 (write_build_marker) 까지를 그대로 옮기되 다음 다섯 자리만 바꾼다 ──
    #  ① 494줄 SLO-6 이력 조회 — text("SELECT source_counts ... LIMIT 12") 를
    #     text(VOLUME_HISTORY_SQL), {"rid": run_id} 로
    #  ② 495줄 volume_anomalies(stats["source_counts"], hist) → volume_anomalies(fetched.source_counts, hist)
    #  ③ 498줄 · 520줄 candidates=candidate_counts → candidates=fetched.candidate_counts
    #  ④ 521줄 fetch_errors=errors, funnels=adapter_funnels(adapters) → fetch_errors=fetched.errors, funnels=fetched.funnels
    #  ⑤ 541-553줄 summary 계산과 RUN_INSERT_SQL 실행을 아래 마감 코드로
    ...
    summary = {"new_or_changed": fetched.new_count, "errors": fetched.errors,
               "success_rate": fetched.success_rate,
               "elapsed_sec": round((datetime.now(timezone.utc).replace(tzinfo=None)
                                     - fetched.started_at_utc).total_seconds(), 2)}
    with engine.begin() as c:
        c.execute(text(RUN_FINISH_SQL), {"rid": run_id, "dur": summary["elapsed_sec"]})
    # ── 555줄 (운영 뷰 write_ops) 에서 573줄 (write_build_marker) 까지는 마감 뒤에 그대로 ──
    ...
    print(summary)


def gate(run_id: str) -> None:
    """dbt 품질 게이트 (§3.2 표의 넷째 행). 차단이면 SystemExit — 셸 종료 코드가 판정 재료다."""
    dbt_gate.enforce_gate(
        dbt_gate.run_gate(Path("dbt"), os.environ["MARIADB_URL"]), run_id=run_id)


async def main(concurrency: int):
    """넷을 차례로 — 로컬 · 테스트 · systemd 되돌림이 쓰는 한 프로세스 경로."""
    run_id = str(uuid.uuid4())
    await collect(run_id, concurrency)
    enrich(run_id)
    publish(run_id)
    gate(run_id)


STAGES = ("collect", "enrich", "publish", "gate")


def run_stage(stage: str, run_id: str, concurrency: int) -> None:
    if stage not in STAGES:
        raise ValueError(f"모르는 단계 {stage!r} — {STAGES}")
    if stage == "collect":
        asyncio.run(collect(run_id, concurrency))
    elif stage == "enrich":
        enrich(run_id)
    elif stage == "publish":
        publish(run_id)
    else:
        gate(run_id)


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--stage", choices=STAGES,
                    help="하나만 돌린다 (Airflow 태스크) · 없으면 넷을 차례로")
    ap.add_argument("--run-id", help="--stage 와 함께 · 회차 행의 run_id")
    ns = ap.parse_args(argv)
    if ns.stage and not ns.run_id:
        ap.error("--stage 는 --run-id 와 함께 준다")
    return ns


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ns = parse_args()
    if ns.stage:
        run_stage(ns.stage, ns.run_id, ns.concurrency)
    else:
        asyncio.run(main(ns.concurrency))
```

옮길 때 주의 셋이다.

- `publish` 의 마감 (`RUN_FINISH_SQL`) 은 `write_ops` **앞**이다.
  `ops_snapshot` 이 `pipeline_runs` 를 읽으므로 `duration_sec` 이 채워진 뒤 읽어야 화면에 빈 칸이 안 난다.
- `enrich` 안의 `from bullet_in.enrich import (partition_by_body_level, ...)` 지연 import 는 그대로 함수 안에 둔다.
- 지금 `main` 의 `t0` 은 수집 소요와 전체 소요 둘에 쓰였다.
  수집 소요는 `collect` 의 `t0` 이 재고, 전체 소요는 `publish` 가 `started_at_utc` 와의 차로 잰다.

- [ ] **Step 6: 단위 테스트를 통과시킨다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_run_stages.py tests/test_run_cliff_alert.py -q`
Expected: 전부 PASS

- [ ] **Step 7: 통합 테스트를 두 단계 기록에 맞춘다**

`tests/integration/test_pipeline_runs_insert.py` 의 `_params` 와 네 테스트를 다음으로 바꾼다.

```python
import json
from datetime import datetime
from sqlalchemy import create_engine, text
from bullet_in.run import RUN_INSERT_SQL, RUN_FINISH_SQL, RUN_SELECT_SQL, FetchSummary
from tests.integration.conftest import TEST_URL


def _params(rid="bench-run", fetch=7.5, blocked=0):
    return {"rid": rid, "drid": "test",
            "started": datetime(2026, 7, 14, 3, 0, 0),
            "fetch": fetch,
            "counts": json.dumps({"bbc_sport": 2}),
            "cands": json.dumps({"bbc_sport": 4}),
            "new": 2, "dup": 0, "blocked": blocked, "err": 1, "sr": 0.9,
            "detail": json.dumps({"errors": {"fmkorea": "HTTP 430"},
                                  "funnels": {"fmkorea": {"found": 15}}})}


def test_insert_leaves_finish_columns_empty_and_records_fetch(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params())
        row = c.execute(text(
            "SELECT started_at, fetch_duration_sec, finished_at, duration_sec "
            "FROM pipeline_runs WHERE run_id='bench-run'")).mappings().one()
    assert row["fetch_duration_sec"] == 7.5
    assert row["started_at"] == datetime(2026, 7, 14, 3, 0, 0)
    assert row["finished_at"] is None and row["duration_sec"] is None


def test_finish_sets_utc_finished_at_and_duration(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-finish"))
        c.execute(text(RUN_FINISH_SQL), {"rid": "bench-finish", "dur": 42.0})
        row = c.execute(text(
            "SELECT duration_sec, TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) AS drift "
            "FROM pipeline_runs WHERE run_id='bench-finish'")).mappings().one()
    assert row["duration_sec"] == 42.0
    assert abs(row["drift"]) <= 60


def test_select_roundtrips_fetch_summary(engine):
    with engine.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-select", blocked=15))
        row = c.execute(text(RUN_SELECT_SQL), {"rid": "bench-select"}).mappings().one()
    s = FetchSummary.from_row(row)
    assert s.blocked_count == 15 and s.candidate_counts == {"bbc_sport": 4}
    assert s.errors == {"fmkorea": "HTTP 430"} and s.funnels == {"fmkorea": {"found": 15}}


def test_finished_at_stays_utc_under_kst_session(engine):
    # NOW() 회귀면 finished_at 이 +9h(32400s) 어긋난다 — UTC_TIMESTAMP() 검증
    kst = create_engine(TEST_URL,
                        connect_args={"init_command": "SET time_zone = '+09:00'"})
    with kst.begin() as c:
        c.execute(text(RUN_INSERT_SQL), _params(rid="bench-kst"))
        c.execute(text(RUN_FINISH_SQL), {"rid": "bench-kst", "dur": 1.0})
        drift = c.execute(text(
            "SELECT TIMESTAMPDIFF(SECOND, finished_at, UTC_TIMESTAMP()) "
            "FROM pipeline_runs WHERE run_id='bench-kst'")).scalar_one()
    kst.dispose()
    assert abs(drift) <= 60
```

Run: `docker compose up -d && uv run --project <워크트리> --extra dev pytest tests/integration/test_pipeline_runs_insert.py -q`
Expected: 4 PASS (DB 가 없으면 skip · 그때는 CI 결과로 본다)

- [ ] **Step 8: 전체 테스트 · 한 프로세스 경로가 그대로 도는지**

Run: `uv run --project <워크트리> --extra dev pytest -q`
Expected: 기존 1,670 + 신규 7 전부 PASS

Run (로컬 DB · `.env` 가 있으면): `set -a; source .env; set +a; uv run --project <워크트리> python -m bullet_in.run --stage gate --run-id local-probe`
Expected: 게이트만 돌고 「dbt 게이트 통과」 또는 차단 로그로 끝난다.

- [ ] **Step 9: 커밋**

```bash
git -C <워크트리> add src/bullet_in/run.py src/bullet_in/storage/schema.sql tests/test_run_stages.py tests/integration/test_pipeline_runs_insert.py
git -C <워크트리> commit -m "refactor(run): 회차 본체를 단계 함수 넷으로 가르고 수집 값을 회차 행으로 건넨다"
```

---

### Task 2: 게이트 급사는 단계 안에서 한 번 더 (스펙 §6.2)

**Files:**
- Modify: `src/bullet_in/dbt_gate.py:105-141` (`run_gate`)
- Test: `tests/test_dbt_gate.py`

**Interfaces:**
- Produces: `run_gate(project_dir, mariadb_url, *, crash_retries: int = 1) -> GateResult` · 신호 종료 (`returncode < 0`) 일 때만 다시 돌린다 · 두 번째도 신호 종료면 지금처럼 `ran=False` 와 음수 코드 (그러면 `enforce_gate` 가 `3`)

- [ ] **Step 1: 세 갈래 테스트를 쓴다**

`tests/test_dbt_gate.py` 끝에 더한다.
같은 파일의 `test_run_gate_records_dbt_returncode` (210줄) 가 쓰는 `fake_run` 꼴을 따른다.

```python
def _completed(rc, stdout="", stderr=""):
    return subprocess.CompletedProcess(["dbt", "build"], rc, stdout, stderr)


def _write_pass(tmp_path):
    (tmp_path / "target").mkdir(exist_ok=True)
    (tmp_path / "target" / "run_results.json").write_text(json.dumps(
        {"results": [{"unique_id": "test.bullet_in.ok.x", "status": "pass", "failures": 0}]}))


def test_run_gate_retries_once_after_a_signal_death_and_passes(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            return _completed(-11)
        _write_pass(tmp_path)
        return _completed(0)
    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")
    assert len(calls) == 2
    assert r.ran and not r.blocked and r.dbt_returncode == 0


def test_run_gate_gives_up_after_two_signal_deaths(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _completed(-11)
    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")
    assert len(calls) == 2
    assert not r.ran and r.dbt_returncode == -11


def test_run_gate_does_not_retry_a_violation(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        (tmp_path / "target").mkdir(exist_ok=True)
        (tmp_path / "target" / "run_results.json").write_text(json.dumps(
            {"results": [{"unique_id": "test.bullet_in.bad.x", "status": "fail", "failures": 3}]}))
        return _completed(1)
    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")
    assert len(calls) == 1
    assert r.ran and r.blocked and r.dbt_returncode == 1
```

파일 머리에 `import json, subprocess` 가 없으면 더한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_dbt_gate.py -q -k "signal or violation"`
Expected: 첫 둘이 `assert len(calls) == 2` 에서 FAIL (지금은 한 번만 돈다)

- [ ] **Step 3: `run_gate` 에 재시도를 넣는다**

`run_gate` 의 시그니처와 subprocess 호출 부분 (105-124줄) 을 이렇게 바꾼다.
나머지 (결과 파싱 · 진단) 는 그대로다.

```python
def run_gate(project_dir: Path, mariadb_url: str, *, crash_retries: int = 1) -> GateResult:
    """`dbt build` 를 돌리고 결과 파일을 읽어 판정한다.

    dbt 자체가 못 돌면 데이터 결함이 아니라 게이트 고장이다 — 그것도 차단으로 낸다.
    조용히 통과시키면 게이트가 있다는 착각만 남는다.

    신호로 죽은 것 (세그폴트 · 안건 2ν · 비결정적) 만 crash_retries 번 더 돌린다.
    위반 · 설정 오류는 다시 돌려도 같은 답이라 한 번에 끝낸다 (스펙 2026-09-04 §6.2).
    Airflow 의 태스크 재시도로는 이 구분을 못 한다 — 건너뜀은 재시도되지 않고
    retries 는 실패 전부에 붙는다.
    """
    results_path = Path(project_dir) / "target" / "run_results.json"
    env = {**os.environ, **dbt_env(mariadb_url), "DBT_PROFILES_DIR": "."}
    proc = None
    for attempt in range(1 + crash_retries):
        # 2026-08-31 실측: dbt 가 시작도 못 하면 run_results.json 을 새로 안 쓴다 —
        # 지난 회차의 "전부 통과" 파일이 남아 통과로 읽힌다. 시도마다 지운다.
        try:
            results_path.unlink(missing_ok=True)
        except OSError as e:
            return GateResult(ran=False, error=f"이전 결과 파일을 못 지웠다: {e}")
        try:
            proc = subprocess.run(["dbt", "build"], cwd=project_dir, env=env,
                                  capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            return GateResult(ran=False, error=f"dbt 를 못 돌렸다: {e}")
        if proc.returncode >= 0:
            break
        log.warning("dbt 가 신호로 죽었다 (종료코드 %d · 시도 %d/%d)",
                    proc.returncode, attempt + 1, 1 + crash_retries)
    result = parse_results(results_path)
    ...  # 이하 지금 코드 (diag · 세 갈래 return) 그대로
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_dbt_gate.py -q`
Expected: 18 + 3 전부 PASS (기존 `test_run_gate_*` 는 첫 시도가 0 이상이라 한 번만 돈다)

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/dbt_gate.py tests/test_dbt_gate.py
git -C <워크트리> commit -m "feat(dbt-gate): 신호로 죽은 dbt 만 같은 회차에서 한 번 더 돌린다"
```

---

### Task 3: 판정기의 Airflow 입력 (스펙 §6.3)

**Files:**
- Modify: `src/bullet_in/deploy.py` (`judge` 앞에 함수 둘 · `main` 의 `judge` 서브커맨드)
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `PIPELINE_TASKS = ("advance", "collect", "enrich", "publish", "gate", "deploy_site")` · `parse_task_states(text: str) -> dict[str, str]` (CLI `states-for-dag-run -o json` 의 목록 또는 `{task_id: state}` 사전) · `airflow_inputs(states: dict[str, str]) -> tuple[str, str]` (`service_result`, `exit_status`) · CLI `deploy judge --from-airflow <경로 또는 ->`
- Consumes: `decide` · `judge` (무변경) · `GATE_CRASH_EXIT`

- [ ] **Step 1: 대응표 · 파서 · CLI 테스트를 쓴다**

`tests/test_deploy.py` 의 import 에 `airflow_inputs, parse_task_states` 를 더하고 파일 끝에 붙인다.

```python
# ── Airflow 입력 (스펙 2026-09-04 §6.3) — 태스크 상태 일곱을 decide 의 두 값으로 ──

def _states(**over):
    base = {t: "success" for t in ("advance", "collect", "enrich", "publish", "gate", "deploy_site")}
    base["judge"] = "running"
    base["warehouse_load"] = "success"
    base.update(over)
    return base


def test_airflow_inputs_success_when_pipeline_tasks_all_succeed():
    assert airflow_inputs(_states()) == ("success", "0")


def test_airflow_inputs_holds_when_gate_was_skipped():
    s = _states(gate="skipped", deploy_site="skipped")
    assert airflow_inputs(s) == ("exit-code", "3")
    assert decide(DeployState(pending=True), *airflow_inputs(s)).action == "hold"


def test_airflow_inputs_rolls_back_naming_the_first_failed_task():
    s = _states(enrich="failed", publish="upstream_failed", gate="upstream_failed",
                deploy_site="upstream_failed")
    assert airflow_inputs(s) == ("exit-code", "enrich")
    assert decide(DeployState(pending=True), *airflow_inputs(s)).action == "rollback"


def test_airflow_inputs_ignores_warehouse_load_and_judge():
    assert airflow_inputs(_states(warehouse_load="failed", judge="running")) == ("success", "0")


def test_airflow_inputs_treats_missing_task_as_failure():
    s = _states()
    del s["deploy_site"]
    assert airflow_inputs(s) == ("exit-code", "deploy_site")


def test_parse_task_states_accepts_cli_list_and_plain_dict():
    cli = json.dumps([{"dag_id": "bullet_in_cycle", "run_id": "r", "task_id": "gate", "state": "skipped"},
                      {"dag_id": "bullet_in_cycle", "run_id": "r", "task_id": "collect", "state": "success"}])
    assert parse_task_states(cli) == {"gate": "skipped", "collect": "success"}
    assert parse_task_states(json.dumps({"gate": "success"})) == {"gate": "success"}


def test_cli_judge_from_airflow_reads_states_file(repos, tmp_path, quiet_alerts, monkeypatch):
    vm, state, old, new = _advanced(repos)
    state_path = tmp_path / "deploy.json"
    save_state(state, state_path)
    monkeypatch.setattr("bullet_in.deploy.STATE_PATH", state_path)
    monkeypatch.chdir(vm)
    states = tmp_path / "states.json"
    states.write_text(json.dumps(_states(gate="failed", deploy_site="upstream_failed")))
    assert main(["judge", "--from-airflow", str(states)]) == 0
    assert _git(vm, "rev-parse", "HEAD") == old          # 롤백됐다
    assert load_state(state_path).blocked == [new]
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q -k airflow`
Expected: `ImportError: cannot import name 'airflow_inputs'`

- [ ] **Step 3: 함수 둘과 CLI 를 넣는다**

`judge` 정의 (348줄) 바로 앞에 더한다.

```python
# Airflow 에서 부를 때의 입력 (스펙 2026-09-04 §6.3). judge 의 재료 두 값은 그대로다 —
# 상태 일곱을 그 두 값으로 옮기는 얇은 층만 새로 둔다. warehouse_load 는 회차 결과와
# 무관하게 도는 것이라 판정 재료가 아니고 judge 자신은 아직 running 이다.
PIPELINE_TASKS = ("advance", "collect", "enrich", "publish", "gate", "deploy_site")


def parse_task_states(text: str) -> dict[str, str]:
    """`airflow tasks states-for-dag-run … -o json` 의 목록이나 {task_id: state} 사전을 받는다."""
    data = json.loads(text)
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {str(r["task_id"]): str(r.get("state")) for r in data if "task_id" in r}


def airflow_inputs(states: dict[str, str]) -> tuple[str, str]:
    """상태 일곱 → (service_result, exit_status). 스펙 §6.3 표의 세 갈래."""
    if states.get("gate") == "skipped":
        return "exit-code", str(GATE_CRASH_EXIT)
    for task in PIPELINE_TASKS:
        if states.get(task) != "success":
            return "exit-code", task
    return "success", "0"
```

`main` 의 서브커맨드 정의에서 `judge` 줄을 바꾸고 실행 분기를 고친다.

```python
    jd = sub.add_parser("judge", help="회차 끝 — $SERVICE_RESULT · $EXIT_STATUS 로 판정 (ExecStopPost) "
                                      "· --from-airflow 면 태스크 상태 JSON 으로")
    jd.add_argument("--from-airflow", metavar="PATH",
                    help="airflow tasks states-for-dag-run -o json 의 출력 파일 (- 는 stdin)")
```

```python
        elif args.command == "judge":
            if args.from_airflow:
                raw = sys.stdin.read() if args.from_airflow == "-" else Path(args.from_airflow).read_text()
                service_result, exit_status = airflow_inputs(parse_task_states(raw))
            else:
                service_result = os.environ.get("SERVICE_RESULT", "")
                exit_status = os.environ.get("EXIT_STATUS", "")
            out = judge(repo, state, service_result=service_result, exit_status=exit_status)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: 34 + 7 전부 PASS

- [ ] **Step 5: 커밋 · PR A**

```bash
git -C <워크트리> add src/bullet_in/deploy.py tests/test_deploy.py
git -C <워크트리> commit -m "feat(deploy): 판정기가 Airflow 태스크 상태를 입력으로 받는다"
```

PR A 를 낸다 (제목 `feat(run): 회차 본체를 단계 넷으로 가르고 게이트 · 판정기를 Airflow 에 맞춘다 (안건 2ε · 1/3)`).
본문 §4 에 태스크 0 의 표를 싣는다.
머지되면 다음 회차가 스스로 반영한다.
**리뷰 채널의 「✅ 코드 반영 완료」 를 확인한 뒤에야 PR B 를 낸다** — 단계 분리가 systemd 경로에서 한 회차 살아 돈 것이 PR B 의 전제다.

---

### Task 4: 실패 알림 CLI 와 DAG (스펙 §4.3 · §7)

**Files:**
- Modify: `src/bullet_in/notify.py:276-293` (`build_failure_alert`) · 파일 끝에 `__main__`
- Create: `airflow/dags/bullet_in_cycle.py`
- Delete: `airflow/dags/bullet_in_daily.py`
- Modify: `airflow/requirements.txt`
- Modify: `tests/test_dag_import.py`
- Test: `tests/test_notify_task_failure.py` (신규)

**Interfaces:**
- Produces: `notify.build_task_failure_alert(payload: dict) -> dict` (키 `dag_id` · `task_id` · `run_id` · `try_number` · `duration` · `hostname` · `log_url` · `exception`) · CLI `python -m bullet_in.notify task-failure` (stdin JSON)
- Produces: DAG `bullet_in_cycle` · 태스크 여덟 · Airflow venv 에서 `bullet_in` 을 import 하지 않는다
- Consumes: `run --stage` (태스크 1) · `deploy judge --from-airflow` (태스크 3) · `infra/deploy-site.sh` · `warehouse load`

- [ ] **Step 1: 알림 페이로드 테스트를 쓴다**

`tests/test_notify_task_failure.py`:

```python
"""Airflow 태스크 실패 알림 — DAG 는 프로젝트를 import 하지 않으므로 JSON 으로 건넨다."""
import io
import json

from bullet_in import notify


def _payload(**over):
    p = {"dag_id": "bullet_in_cycle", "task_id": "enrich", "run_id": "scheduled__2026-09-05T00:00:00+00:00",
         "try_number": 1, "duration": 83.2, "hostname": "seoulnow-receiver",
         "log_url": "http://127.0.0.1:8080/dags/bullet_in_cycle/runs/x/tasks/enrich",
         "exception": "RuntimeError: 429"}
    p.update(over)
    return p


def test_task_failure_alert_names_the_task_and_carries_six_fields():
    a = notify.build_task_failure_alert(_payload())
    assert a["title"] == "❌ 파이프라인 실패 — enrich"
    assert a["channel"] == notify.CHANNEL_INCIDENT
    names = [f["name"] for f in a["fields"]]
    assert names == ["DAG / Task", "Run", "Try", "Duration", "Host", "로그"]
    assert "RuntimeError: 429" in a["description"]


def test_task_failure_alert_tolerates_missing_duration_and_log():
    a = notify.build_task_failure_alert(_payload(duration=None, log_url=None, exception=None))
    values = {f["name"]: f["value"] for f in a["fields"]}
    assert values["Duration"] == "-" and values["로그"] == "-"


def test_cli_task_failure_reads_stdin_and_sends(monkeypatch):
    sent = []
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: sent.append(kw))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(task_id="gate"))))
    assert notify.main(["task-failure"]) == 0
    assert sent and sent[0]["title"].endswith("gate")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_notify_task_failure.py -q`
Expected: `AttributeError: module 'bullet_in.notify' has no attribute 'build_task_failure_alert'`

- [ ] **Step 3: `notify.py` 를 고친다**

`build_failure_alert` (276-293줄) 를 다음 둘로 바꾼다.
기존 함수는 남기되 새 함수를 부르게 한다 (호출처는 구 DAG 뿐이고 그 DAG 는 지운다 · 다음 정리 때 뺀다).

```python
def build_task_failure_alert(payload: dict) -> dict:
    """Airflow 태스크 실패 — DAG 콜백이 JSON 으로 건넨 값으로 만든다 (스펙 2026-09-04 §7).

    DAG 파일은 프로젝트를 import 하지 않으므로 (Airflow venv 가 따로다) 컨텍스트에서
    뽑은 값 여덟만 stdin 으로 받는다."""
    dur = payload.get("duration")
    log_url = payload.get("log_url")
    task = payload.get("task_id", "?")
    fields = [
        {"name": "DAG / Task", "value": f"{payload.get('dag_id', '?')} / {task}", "inline": True},
        {"name": "Run", "value": str(payload.get("run_id") or "-"), "inline": True},
        {"name": "Try", "value": str(payload.get("try_number") or "-"), "inline": True},
        {"name": "Duration", "value": f"{dur:.0f}s" if dur is not None else "-", "inline": True},
        {"name": "Host", "value": str(payload.get("hostname") or "-"), "inline": True},
        {"name": "로그", "value": f"[열기]({log_url})" if log_url else "-", "inline": True},
    ]
    exc = payload.get("exception")
    return {"title": f"❌ 파이프라인 실패 — {task}",
            "description": f"회차 태스크가 예외로 중단되었습니다.\n```\n{str(exc)[:400] if exc else '-'}\n```",
            "color": COLOR_FAILURE, "fields": fields,
            "channel": CHANNEL_INCIDENT}


def build_failure_alert(context) -> dict:
    """구 DAG (bullet_in_daily) 의 콜백 서명 — 컨텍스트에서 페이로드를 뽑아 위 함수로."""
    ti = context["task_instance"]
    return build_task_failure_alert({
        "dag_id": ti.dag_id, "task_id": ti.task_id, "run_id": context.get("run_id"),
        "try_number": ti.try_number, "duration": getattr(ti, "duration", None),
        "hostname": getattr(ti, "hostname", None), "log_url": getattr(ti, "log_url", None),
        "exception": context.get("exception")})
```

파일 끝에 CLI 를 더한다.

```python
def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="알림 CLI — Airflow DAG 콜백이 쓴다")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("task-failure", help="stdin 의 JSON 페이로드로 태스크 실패 알림")
    args = ap.parse_args(argv)
    if args.command == "task-failure":
        send_alert(**build_task_failure_alert(json.loads(sys.stdin.read())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`notify.py` 머리 (`import logging, os, re`) 에 `json` 을 더한다 — 지금은 없다.
기존 테스트 `tests/test_notify.py::test_build_failure_alert_maps_context` (55줄) 와 574줄의 채널 배정 표본은 호환 래퍼로 그대로 통과한다 (제목에 `task_id` 가 들어가고 예외 문자열이 설명에 남는다).

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_notify_task_failure.py tests/test_notify*.py -q`
Expected: 전부 PASS

- [ ] **Step 5: DAG 를 쓴다**

`airflow/dags/bullet_in_daily.py` 를 지우고 `airflow/dags/bullet_in_cycle.py` 를 만든다.

```python
"""bullet-in 회차 DAG — 태스크 여덟 · 전부 셸 호출 (스펙 2026-09-04 §4.3).

이 파일은 Airflow venv 에서 파싱되므로 bullet_in 을 import 하지 않는다.
단계는 프로젝트 venv 의 `uv run python -m bullet_in.run --stage …` 로 돌고,
전진 · 판정 · 롤백 (스펙 2026-09-03) 은 첫 · 끝 태스크가 같은 명령을 부른다.
"""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

REPO = "/home/ubuntu/bullet-in"
UV = "/home/ubuntu/.local/bin/uv"
AIRFLOW_BIN = "/home/ubuntu/airflow-venv/bin/airflow"
# 프로젝트의 .env 는 Airflow 프로세스가 아니라 태스크 셸이 읽는다 (스펙 §4.2).
PRELUDE = f"cd {REPO} && set -a && . ./.env && set +a && "
# 변경 이력 적재만 전용 서비스 계정 — 유닛 주석과 같은 사정 (bullet-in-warehouse.service).
LAKEHOUSE_KEY = "/home/ubuntu/.bullet-in-lakehouse.json"


def _stage(name: str) -> str:
    return f"{PRELUDE}{UV} run python -m bullet_in.run --stage {name} --run-id '{{{{ run_id }}}}'"


def _task_failure(context) -> None:
    """실패 콜백 — 컨텍스트에서 값 여덟을 뽑아 프로젝트의 알림 CLI 에 JSON 으로 건넨다."""
    ti = context["task_instance"]
    payload = {
        "dag_id": ti.dag_id, "task_id": ti.task_id, "run_id": context.get("run_id"),
        "try_number": ti.try_number, "duration": getattr(ti, "duration", None),
        "hostname": getattr(ti, "hostname", None), "log_url": getattr(ti, "log_url", None),
        "exception": str(context.get("exception") or "")[:400] or None,
    }
    subprocess.run(["bash", "-c", f"{PRELUDE}{UV} run python -m bullet_in.notify task-failure"],
                   input=json.dumps(payload, default=str), text=True, timeout=60, check=False)


with DAG(
    dag_id="bullet_in_cycle",
    schedule="0 */3 * * *",                       # bullet-in.timer 와 같은 값 (UTC)
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    catchup=False,                                # 밀린 회차 보정 = 최근 구간 한 번 (Persistent=true 대응)
    max_active_runs=1,                            # 이중 실행 금지
    dagrun_timeout=timedelta(minutes=30),         # TimeoutStartSec=1800 대응
    default_args={"on_failure_callback": _task_failure, "retries": 0},
    tags=["bullet-in"],
) as dag:
    # 전진 실패로 회차를 잃지 않는다 — ExecStartPre=- 와 같은 뜻으로 종료 코드를 0 으로 만든다.
    advance = BashOperator(task_id="advance",
                           bash_command=f"{PRELUDE}{UV} run python -m bullet_in.deploy advance || true")
    collect = BashOperator(task_id="collect", bash_command=_stage("collect"))
    enrich = BashOperator(task_id="enrich", bash_command=_stage("enrich"))
    publish = BashOperator(task_id="publish", bash_command=_stage("publish"), retries=1)
    # 급사 (종료 코드 3) 는 실패가 아니라 건너뜀 — 뒤의 deploy_site 가 기본 규칙으로 함께 건너뛰고
    # judge 가 「보류」 를 낸다. 급사 재시도는 게이트 안에서 이미 한 번 했다 (dbt_gate.run_gate).
    gate = BashOperator(task_id="gate", bash_command=_stage("gate"), skip_on_exit_code=3)
    deploy_site = BashOperator(task_id="deploy_site",
                               bash_command=f"{PRELUDE}infra/deploy-site.sh", retries=1)
    # 앞이 어떻게 끝났든 돈다 (ExecStopPost 대응) — 상태를 CLI 로 받아 판정기에 넘긴다.
    judge = BashOperator(
        task_id="judge", trigger_rule="all_done",
        bash_command=(f"{PRELUDE}mkdir -p state && "
                      f"{AIRFLOW_BIN} tasks states-for-dag-run bullet_in_cycle '{{{{ run_id }}}}' -o json "
                      f"> state/airflow_states.json && "
                      f"{UV} run python -m bullet_in.deploy judge --from-airflow state/airflow_states.json"))
    # 「회차 20분 뒤」 시계 어긋내기 대신 의존 — 회차 결과와 무관하게 돈다 (타이머와 같은 성질).
    warehouse_load = BashOperator(
        task_id="warehouse_load", trigger_rule="all_done",
        bash_command=(f"{PRELUDE}env GOOGLE_APPLICATION_CREDENTIALS={LAKEHOUSE_KEY} "
                      f"{UV} run python -m bullet_in.warehouse load"))

    advance >> collect >> enrich >> publish >> gate >> deploy_site >> judge
    publish >> warehouse_load
```

`airflow/requirements.txt`:

```
apache-airflow==3.3.1
apache-airflow-providers-standard
psycopg2-binary
```

- [ ] **Step 6: DAG 구조 테스트를 고친다**

`tests/test_dag_import.py` 전체를 바꾼다.

```python
"""DAG 구조 검증 — 프로젝트 venv 에는 Airflow 가 없어 skip 되고, 격리 venv 에서만 돈다
(런북 docs/runbook/2026-05-27-airflow-dag-verification.md)."""
import pytest
pytest.importorskip("airflow.models")
from airflow.models import DagBag


def _dag():
    bag = DagBag(dag_folder="airflow/dags", include_examples=False)
    assert bag.import_errors == {}
    return bag.dags["bullet_in_cycle"]


def test_dag_has_eight_tasks_in_the_spec_order():
    dag = _dag()
    assert set(dag.task_ids) == {"advance", "collect", "enrich", "publish", "gate",
                                 "deploy_site", "judge", "warehouse_load"}
    chain = ["advance", "collect", "enrich", "publish", "gate", "deploy_site", "judge"]
    for up, down in zip(chain, chain[1:]):
        assert up in dag.get_task(down).upstream_task_ids
    assert dag.get_task("warehouse_load").upstream_task_ids == {"publish"}


def test_gate_skips_on_exit_code_3_and_has_no_airflow_retry():
    gate = _dag().get_task("gate")
    assert 3 in (gate.skip_on_exit_code if isinstance(gate.skip_on_exit_code, (list, tuple, set))
                 else [gate.skip_on_exit_code])
    assert gate.retries == 0


def test_judge_and_warehouse_load_run_regardless_of_upstream():
    dag = _dag()
    assert dag.get_task("judge").trigger_rule == "all_done"
    assert dag.get_task("warehouse_load").trigger_rule == "all_done"


def test_run_parameters_mirror_the_systemd_timer():
    dag = _dag()
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout.total_seconds() == 1800


def test_every_task_has_the_failure_callback():
    for t in _dag().tasks:
        assert t.on_failure_callback
```

- [ ] **Step 7: 격리 venv 에서 DAG 테스트를 돌린다 (로컬)**

```bash
uv venv --python 3.11 /tmp/af33
uv pip install --python /tmp/af33/bin/python --quiet "apache-airflow==3.3.1" "apache-airflow-providers-standard" pytest pendulum \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt
cd <워크트리> && AIRFLOW_HOME=/tmp/af33/home /tmp/af33/bin/python -m pytest tests/test_dag_import.py -q -p no:cacheprovider
```

Expected: 5 PASS.
루트의 `airflow/` 디렉터리가 패키지 이름을 가리는 함정은 `docs/troubleshooting/2026-05-27-airflow-namespace-shadowing.md` 대로 `cd <워크트리>` 에서 `python -m pytest` 로 돈다.
`skip_on_exit_code` 의 타입이 정수가 아니면 (태스크 0 의 답) 테스트의 판정을 그에 맞춘다.

- [ ] **Step 8: 프로젝트 venv 에서는 skip 되는지 · 나머지 전부 통과**

Run: `uv run --project <워크트리> --extra dev pytest -q`
Expected: `test_dag_import.py` 5 skipped · 나머지 PASS

- [ ] **Step 9: 커밋**

```bash
git -C <워크트리> add src/bullet_in/notify.py tests/test_notify_task_failure.py airflow/ tests/test_dag_import.py
git -C <워크트리> commit -m "feat(airflow): 회차 DAG bullet_in_cycle (태스크 여덟 · 셸 호출) 과 태스크 실패 알림 CLI"
```

---

### Task 5: Airflow 설치 · 유닛 넷 · 생존 감시 (스펙 §4.1 · §4.2 · §4.4)

**Files:**
- Modify: `docker-compose.yml`
- Create: `infra/airflow/airflow.env` · `infra/airflow/install-airflow.sh`
- Create: `infra/systemd/airflow-api-server.service` · `airflow-scheduler.service` · `airflow-dag-processor.service` · `bullet-in-airflow-watch.service` · `bullet-in-airflow-watch.timer`
- Modify: `infra/systemd/install-units.sh`
- Create: `src/bullet_in/airflow_watch.py`
- Test: `tests/test_airflow_watch.py`

**Interfaces:**
- Produces: `airflow_watch.evaluate(heartbeat_ok: bool, last_success_age_hours: float | None, *, threshold_hours: float = 4.0) -> list[str]` · `airflow_watch.should_alert(problems, state: dict, now: datetime, *, every_hours: float = 4.0) -> tuple[bool, dict]` · `airflow_watch.latest_success_age(list_runs_json: str, now: datetime) -> float | None` · CLI `python -m bullet_in.airflow_watch`
- 스펙 §4.4 는 `infra/airflow/watch.py` 라 했으나 다른 유닛과 같이 `uv run python -m bullet_in.airflow_watch` 로 부르는 편이 테스트 · `.env` 로딩이 같은 길이라 모듈로 둔다 (스펙 문장의 자리만 바뀐다).
- 스펙 §4.1 의 「`airflow.cfg` 복사」 는 환경변수 파일 하나 (`airflow.env`) 로 대신한다 — systemd `EnvironmentFile=` 이 그대로 읽고 `AIRFLOW__<절>__<키>` 가 cfg 와 같은 뜻이다.

- [ ] **Step 1: 감시 판정 테스트를 쓴다**

`tests/test_airflow_watch.py`:

```python
"""오케스트레이터 생존 감시 (스펙 2026-09-04 §4.4) — 심박과 마지막 성공, 두 축."""
import json
from datetime import datetime, timedelta, timezone

from bullet_in.airflow_watch import evaluate, latest_success_age, should_alert

NOW = datetime(2026, 9, 6, 6, 0, tzinfo=timezone.utc)


def test_evaluate_is_quiet_when_both_axes_are_fine():
    assert evaluate(True, 2.5) == []


def test_evaluate_names_each_broken_axis():
    p = evaluate(False, 7.0)
    assert any("심박" in x for x in p) and any("7.0" in x for x in p)
    assert evaluate(True, None) == ["bullet_in_cycle 의 성공 실행이 없다"]
    assert evaluate(True, 3.9) == []


def test_latest_success_age_reads_the_cli_list_and_picks_the_newest():
    runs = [{"dag_id": "bullet_in_cycle", "state": "success", "end_date": "2026-09-06T00:07:21+00:00"},
            {"dag_id": "bullet_in_cycle", "state": "success", "end_date": "2026-09-06T03:07:02+00:00"},
            {"dag_id": "bullet_in_cycle", "state": "failed", "end_date": "2026-09-06T05:50:00+00:00"}]
    age = latest_success_age(json.dumps(runs), NOW)
    assert round(age, 2) == round((NOW - datetime(2026, 9, 6, 3, 7, 2, tzinfo=timezone.utc)).total_seconds() / 3600, 2)
    assert latest_success_age("[]", NOW) is None


def test_should_alert_sends_once_then_waits_four_hours():
    ok, st = should_alert(["x"], {}, NOW)
    assert ok and st["last_alert_at"] == NOW.isoformat()
    ok2, st2 = should_alert(["x"], st, NOW + timedelta(hours=1))
    assert not ok2 and st2 == st
    ok3, _ = should_alert(["x"], st, NOW + timedelta(hours=4, minutes=1))
    assert ok3


def test_should_alert_resets_when_healthy():
    _, st = should_alert(["x"], {}, NOW)
    ok, st2 = should_alert([], st, NOW + timedelta(hours=1))
    assert not ok and st2 == {}
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_airflow_watch.py -q`
Expected: `ModuleNotFoundError: No module named 'bullet_in.airflow_watch'`

- [ ] **Step 3: 감시 모듈을 쓴다**

`src/bullet_in/airflow_watch.py`:

```python
"""오케스트레이터 생존 감시 — 매시 두 축을 잰다 (스펙 2026-09-04 §4.4).

스케줄러가 살아 있어도 DAG 가 일시정지됐거나 파싱이 깨지면 회차가 조용히 안 돈다.
심박만 보면 그 경우를 못 잡고, 마지막 성공만 보면 원인이 안 갈린다 — 그래서 둘 다.
systemd 의 OnFailure 가 덮던 「유닛 자체가 죽은 경우」 를 이 타이머가 잇는다.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bullet_in import notify

log = logging.getLogger(__name__)

AIRFLOW_BIN = os.environ.get("AIRFLOW_BIN", "/home/ubuntu/airflow-venv/bin/airflow")
DAG_ID = "bullet_in_cycle"
STATE_PATH = Path("state/airflow_watch.json")


def evaluate(heartbeat_ok: bool, last_success_age_hours: float | None, *,
             threshold_hours: float = 4.0) -> list[str]:
    problems = []
    if not heartbeat_ok:
        problems.append("스케줄러 심박 없음 (airflow jobs check 실패)")
    if last_success_age_hours is None:
        problems.append(f"{DAG_ID} 의 성공 실행이 없다")
    elif last_success_age_hours > threshold_hours:
        problems.append(f"{DAG_ID} 의 마지막 성공이 {last_success_age_hours:.1f}시간 전 (문턱 {threshold_hours:g}시간)")
    return problems


def latest_success_age(list_runs_json: str, now: datetime) -> float | None:
    """`airflow dags list-runs -d bullet_in_cycle -o json` 의 목록에서 최신 성공까지의 시간."""
    ends = []
    for r in json.loads(list_runs_json or "[]"):
        if r.get("state") == "success" and r.get("end_date"):
            ends.append(datetime.fromisoformat(str(r["end_date"]).replace("Z", "+00:00")))
    if not ends:
        return None
    return (now - max(ends)).total_seconds() / 3600


def should_alert(problems: list[str], state: dict, now: datetime, *,
                 every_hours: float = 4.0) -> tuple[bool, dict]:
    """같은 상태가 이어지는 동안 every_hours 마다 한 번만 (신선도 재알림 규칙과 같은 방식)."""
    if not problems:
        return False, {}
    last = state.get("last_alert_at")
    if last and (now - datetime.fromisoformat(last)).total_seconds() < every_hours * 3600:
        return False, state
    return True, {"last_alert_at": now.isoformat()}


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([AIRFLOW_BIN, *args], capture_output=True, text=True, timeout=120)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    now = datetime.now(timezone.utc)
    hb = _cli("jobs", "check", "--job-type", "SchedulerJob", "--allow-multiple")
    runs = _cli("dags", "list-runs", "-d", DAG_ID, "-o", "json")
    age = latest_success_age(runs.stdout, now) if runs.returncode == 0 else None
    problems = evaluate(hb.returncode == 0, age)
    state = {}
    try:
        state = json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        pass
    send, new_state = should_alert(problems, state, now)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(new_state))
    if send:
        notify.send_alert("🚨 Airflow 가 회차를 안 돌리고 있다",
                          "\n".join(f"- {p}" for p in problems) + "\n"
                          "`systemctl status airflow-scheduler airflow-dag-processor` · "
                          "`airflow dags state bullet_in_cycle` · 되돌리려면 런북 (Airflow 아래에서 회차 돌리기) §5",
                          color=notify.COLOR_FAILURE, channel=notify.CHANNEL_INCIDENT)
    log.info("airflow watch — 심박 %s · 마지막 성공 %s시간 전 · 문제 %d · 발송 %s",
             "OK" if hb.returncode == 0 else "없음", f"{age:.1f}" if age is not None else "?",
             len(problems), send)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_airflow_watch.py -q`
Expected: 5 PASS

- [ ] **Step 5: compose · 환경 파일 · 설치 스크립트**

`docker-compose.yml` 에 서비스와 볼륨을 더한다 (기존 둘은 그대로).

```yaml
  airflow-db:
    image: postgres:16
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
      POSTGRES_DB: airflow
    ports: ["127.0.0.1:5433:5432"]      # 호스트 5432 는 동거 프로젝트가 쓴다 · 밖으로 열지 않는다
    volumes: ["airflow_db_data:/var/lib/postgresql/data"]
volumes:
  mongo_data:
  maria_data:
  airflow_db_data:
```

`infra/airflow/airflow.env` (VM 의 `/home/ubuntu/airflow/airflow.env` 로 복사된다):

```
AIRFLOW_HOME=/home/ubuntu/airflow
AIRFLOW__CORE__DAGS_FOLDER=/home/ubuntu/bullet-in/airflow/dags
AIRFLOW__CORE__EXECUTOR=LocalExecutor
AIRFLOW__CORE__PARALLELISM=2
AIRFLOW__CORE__MAX_ACTIVE_TASKS_PER_DAG=2
AIRFLOW__CORE__LOAD_EXAMPLES=False
AIRFLOW__CORE__DEFAULT_TIMEZONE=utc
AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS=admin:admin
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@127.0.0.1:5433/airflow
AIRFLOW__API__BASE_URL=http://127.0.0.1:8080
AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL=60
```

`infra/airflow/install-airflow.sh`:

```bash
#!/usr/bin/env bash
# Airflow 3 를 프로젝트와 다른 venv 에 깐다 — VM 에서 실행 (스펙 2026-09-04 §4.1).
set -euo pipefail
VERSION="${AIRFLOW_VERSION:-3.3.1}"
VENV=/home/ubuntu/airflow-venv
HOME_DIR=/home/ubuntu/airflow
UV=/home/ubuntu/.local/bin/uv
cd "$(dirname "$0")"
[ -d "$VENV" ] || $UV venv --python 3.11 "$VENV"
$UV pip install --python "$VENV/bin/python" \
  "apache-airflow==$VERSION" "apache-airflow-providers-standard" "psycopg2-binary" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-$VERSION/constraints-3.11.txt"
mkdir -p "$HOME_DIR"
cp airflow.env "$HOME_DIR/airflow.env"
set -a; . "$HOME_DIR/airflow.env"; set +a
(cd /home/ubuntu/bullet-in && /usr/bin/docker compose up -d --wait airflow-db)
"$VENV/bin/airflow" db migrate
"$VENV/bin/airflow" version
echo "관리자 비밀번호는 첫 api-server 기동 때 $HOME_DIR/simple_auth_manager_passwords.json.generated 에 생긴다"
```

- [ ] **Step 6: 유닛 넷과 설치 스크립트**

`infra/systemd/airflow-scheduler.service`:

```ini
[Unit]
Description=Airflow scheduler (bullet-in 회차 DAG)
Wants=docker.service network-online.target
After=docker.service network-online.target
OnFailure=bullet-in-fail-notify@%n.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/airflow
EnvironmentFile=/home/ubuntu/airflow/airflow.env
ExecStartPre=/usr/bin/docker compose -f /home/ubuntu/bullet-in/docker-compose.yml up -d --wait airflow-db
ExecStart=/home/ubuntu/airflow-venv/bin/airflow scheduler
Restart=on-failure
RestartSec=10
# dbt 게이트 세그폴트 (안건 2ν) 의 코어 덤프 — 게이트는 이 프로세스의 자식 (LocalExecutor) 이다.
LimitCORE=infinity

[Install]
WantedBy=multi-user.target
```

`infra/systemd/airflow-dag-processor.service` — 위와 같되 `Description=Airflow dag-processor (bullet-in)` · `ExecStart=/home/ubuntu/airflow-venv/bin/airflow dag-processor` · `LimitCORE` 줄 없음 · `ExecStartPre` 없음.

`infra/systemd/airflow-api-server.service` — 위와 같되 `Description=Airflow api-server (bullet-in · 127.0.0.1:8080 · SSH 터널로 본다)` · `ExecStart=/home/ubuntu/airflow-venv/bin/airflow api-server --host 127.0.0.1 --port 8080` · `LimitCORE` 줄 없음 · `ExecStartPre` 없음.

`infra/systemd/bullet-in-airflow-watch.service`:

```ini
[Unit]
Description=bullet-in 오케스트레이터 생존 감시 (스케줄러 심박 · 마지막 성공 4시간)
After=network-online.target
OnFailure=bullet-in-fail-notify@%n.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
EnvironmentFile=/home/ubuntu/airflow/airflow.env
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.airflow_watch
TimeoutStartSec=300
```

`infra/systemd/bullet-in-airflow-watch.timer`:

```ini
[Unit]
Description=bullet-in 오케스트레이터 생존 감시 매시

[Timer]
OnCalendar=*-*-* *:37:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

`infra/systemd/install-units.sh` 를 다음으로 바꾼다.
회차 · 웨어하우스 타이머는 **복사만 하고 활성화하지 않는다** (전환은 스펙 §8 의 순서로 사람이).

```bash
#!/usr/bin/env bash
# systemd 유닛 설치 · 갱신 — VM 의 저장소에서 실행 (sudo 필요). seoulnow install-units.sh 패턴.
# 회차 · 웨어하우스 타이머는 복사만 한다 — Airflow 전환 뒤에는 비활성이 정상이고 (스펙 2026-09-04 §3.5),
# 되돌릴 때 사람이 `systemctl enable --now` 로 켠다.
set -euo pipefail
cd "$(dirname "$0")"
sudo cp bullet-in.service bullet-in.timer \
        bullet-in-watchlist.service bullet-in-watchlist.timer \
        bullet-in-backup.service bullet-in-backup.timer \
        bullet-in-warehouse.service bullet-in-warehouse.timer \
        bullet-in-warehouse-maint.service bullet-in-warehouse-maint.timer \
        bullet-in-fail-notify@.service \
        airflow-scheduler.service airflow-dag-processor.service airflow-api-server.service \
        bullet-in-airflow-watch.service bullet-in-airflow-watch.timer /etc/systemd/system/
sudo rm -f /etc/systemd/system/bullet-in-fail-notify.service   # 구본 (유닛명 하드코딩) 제거
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in-watchlist.timer \
        bullet-in-backup.timer bullet-in-warehouse-maint.timer \
        airflow-scheduler.service airflow-dag-processor.service airflow-api-server.service \
        bullet-in-airflow-watch.timer
systemctl list-timers 'bullet-in*' --no-pager
systemctl --no-pager status airflow-scheduler airflow-dag-processor airflow-api-server | grep -E "●|Active"
```

- [ ] **Step 7: 유닛 문법 · 스크립트 문법을 로컬에서 본다**

```bash
bash -n infra/airflow/install-airflow.sh infra/systemd/install-units.sh
uv run --project <워크트리> --extra dev pytest -q
```

Expected: 문법 오류 없음 · 전부 PASS.
`systemd-analyze verify` 는 맥에 없다 · VM 에서 태스크 8 의 첫 단계로 본다.

- [ ] **Step 8: 커밋**

```bash
git -C <워크트리> add docker-compose.yml infra/airflow infra/systemd src/bullet_in/airflow_watch.py tests/test_airflow_watch.py
git -C <워크트리> commit -m "feat(infra): Airflow 설치 · 유닛 셋 · 메타데이터 DB · 오케스트레이터 생존 감시"
```

---

### Task 6: 백업에 Airflow 메타데이터 덤프 한 파일 (스펙 §3.3)

**Files:**
- Modify: `src/bullet_in/backup.py` (`dump_mongo` 뒤에 함수 하나 · `run_backup` 에 두 줄)
- Test: `tests/test_backup.py` (기존 파일 끝에)

**Interfaces:**
- Produces: `dump_airflow_db(dest: Path) -> None` · `AIRFLOW_DB_CONTAINER = "bullet-in-airflow-db-1"` · 업로드 목록에 `airflow.sql.gz`
- Consumes: `_docker(container, *args, stdout=...)` (기존)

- [ ] **Step 1: 테스트를 쓴다**

`tests/test_backup.py` 끝에 더한다.
파일 머리의 import (`json` · `datetime` · `pytest` · `backup`) 에 `gzip` 과 `subprocess` 를 더한다.

```python
def test_dump_airflow_db_dumps_plain_then_gzips(tmp_path, monkeypatch):
    seen = {}
    def fake_docker(container, *args, stdout=None, **kw):
        seen["container"], seen["args"] = container, args
        stdout.write(b"-- PostgreSQL database dump\nCREATE TABLE dag_run ();\n")
        return subprocess.CompletedProcess([], 0, b"", b"")
    monkeypatch.setattr(backup, "_docker", fake_docker)
    dest = tmp_path / "airflow.sql.gz"
    backup.dump_airflow_db(dest)
    assert seen["container"] == backup.AIRFLOW_DB_CONTAINER
    assert seen["args"][:3] == ("pg_dump", "-U", "airflow")
    assert not (tmp_path / "airflow.sql").exists()          # 평문은 압축 뒤 지운다
    with gzip.open(dest, "rb") as f:
        assert b"CREATE TABLE dag_run" in f.read()
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_backup.py -q -k airflow`
Expected: `AttributeError: … has no attribute 'dump_airflow_db'`

- [ ] **Step 3: 구현한다**

`backup.py` 의 컨테이너 상수 근처에 `AIRFLOW_DB_CONTAINER = "bullet-in-airflow-db-1"` 을 더하고, `dump_mongo` 뒤에 함수를 둔다.

```python
def dump_airflow_db(dest: Path) -> None:
    """Airflow 메타데이터 (DAG 실행 · 태스크 상태) — 되살리면 실행 이력이 돌아온다.

    마트 · 원본과 달리 잃어도 서비스는 안 멈추지만 (다음 회차가 새로 쌓는다),
    「언제 무엇이 실패했나」 가 사라진다. 한 파일이라 같은 세대 규칙으로 함께 올린다.

    _docker 는 자식 프로세스의 stdout 을 파일 디스크립터로 잇는다 — gzip 파일 객체를
    바로 주면 압축을 건너뛰고 평문이 .gz 이름으로 남는다. 그래서 dump_mariadb 와
    같이 평문으로 받은 뒤 압축한다."""
    plain = dest.with_suffix("")                      # airflow.sql.gz → airflow.sql
    with plain.open("wb") as f:
        _docker(AIRFLOW_DB_CONTAINER, "pg_dump", "-U", "airflow", "airflow", stdout=f)
    with plain.open("rb") as src, gzip.open(dest, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    plain.unlink()
```

`run_backup` 에서 `docs = dump_mongo(archive)` 다음 줄에 `airflow_gz = workdir / "airflow.sql.gz"` 와 `dump_airflow_db(airflow_gz)` 를 넣고, 업로드 루프의 `for path in (sql_gz, archive, manifest_path):` 를 `for path in (sql_gz, archive, airflow_gz, manifest_path):` 로 바꾼다.
매니페스트는 바꾸지 않는다 (복구 대조는 마트 · 원본 것이다).
`gzip` · `shutil` 은 `backup.py` 가 이미 import 한다 (`run_backup` 이 쓴다).

- [ ] **Step 4: 통과를 확인한다 · 커밋 · PR B**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_backup.py -q`
Expected: 전부 PASS

```bash
git -C <워크트리> add src/bullet_in/backup.py tests/test_backup.py
git -C <워크트리> commit -m "feat(backup): Airflow 메타데이터 덤프를 같은 세대로 함께 올린다"
```

PR B 를 낸다 (제목 `feat(airflow): 회차 DAG · 설치 · 유닛 · 생존 감시 · 백업 (안건 2ε · 2/3)`).
머지되면 다음 회차의 `docker compose up -d --wait` 가 `airflow-db` 를 띄우고, 백업 유닛이 그 덤프를 올리기 시작한다.
Airflow 자체는 태스크 8 에서 사람이 깐다.

---

### Task 7: 문서 (스펙 §11)

**Files:**
- Modify: `CLAUDE.md:5-9` · `README.md:52,112,149` · `docs/runbook/2026-05-27-daily-operations.md:19` · `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` §2 · `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` §3 · `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md` §2 에서 §5 · `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` §12 · `docs/MIGRATION.md`
- Create: `docs/runbook/2026-09-0X-running-the-cycle-under-airflow.md` (X 는 태스크 8 을 실행한 날)

**Interfaces:**
- Consumes: 태스크 8 의 실측 (설치 소요 · 메모리 · 리허설 결과) — 그래서 마지막 PR 이다

- [ ] **Step 1: 짧은 고침 여덟**

- `CLAUDE.md` 5-9줄 → 「스케줄은 둘이다. 회차와 웨어하우스 적재는 VM 의 Airflow DAG `bullet_in_cycle` (3시간 · 태스크 여덟 · 전진 · 판정은 첫 · 끝 태스크), 워치리스트 · 백업 · 유지보수는 systemd 타이머. 세션은 VM 에서 `git pull` 을 하지 않는다. 회차 유닛 `bullet-in.service` 는 되돌림용으로 남아 있고 타이머는 비활성이다.」 · 「보존 자산」 줄 삭제.
- `README.md` 52줄 · 112줄 · 149줄 — 스케줄 행을 「Airflow 3 (LocalExecutor · 단계 태스크 넷 + 배포 훅) · systemd 는 부수 작업」 으로 · 「보존 자산」 문구 삭제 · 149줄의 DAG 검증 문장은 유지.
- `docs/runbook/2026-05-27-daily-operations.md` 19줄 — 스케줄 문장을 DAG 로 · 저널 대신 `airflow dags list-runs` 한 줄.
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` §2 — 손 시작 명령을 `airflow dags trigger bullet_in_cycle` 로.
- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` §3 — 「신호 종료는 게이트 안에서 한 번 더 돈 뒤의 결과다 · Airflow 에서는 건너뜀으로 보인다」 한 문단.
- `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md` §2 에서 §5 — `systemctl start --no-block bullet-in.service` 를 `airflow dags trigger bullet_in_cycle` 로 · 저널 대신 화면 · `judge` 태스크 로그.
- `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` §12 끝 — 「2026-09-04 스펙이 전진 · 판정을 DAG 첫 · 끝 태스크로 옮겼다 · 입력만 바뀌고 판정 규칙은 그대로」 한 줄.
- `docs/MIGRATION.md` — 「2026-09 운영 버전 3.3.1 · DAG 는 `bullet_in_cycle` · 검증은 `tests/test_dag_import.py`」.

- [ ] **Step 2: 새 런북**

`docs/runbook/2026-09-0X-running-the-cycle-under-airflow.md` — 절 여섯.

1. 무엇이 어디서 도나 (표 · 스펙 §4.3 의 DAG 그림).
2. 화면 여는 법 — `ssh -i ~/.ssh/seoulnow_deploy -L 8080:127.0.0.1:8080 ubuntu@155.248.164.17` 뒤 `http://127.0.0.1:8080` · 계정과 비밀번호 파일 위치.
3. 손으로 회차 시작 — `airflow dags trigger bullet_in_cycle` · 특정 단계만 다시 — 화면에서 태스크 clear.
4. 알림을 받았을 때 — 태스크 실패 (❌ · 로그 링크) · 생존 감시 (🚨 · `systemctl status` 셋 · `airflow dags state`) · 배포 자동화 여섯은 2β 런북.
5. 되돌리기 — `airflow dags pause bullet_in_cycle` → `sudo systemctl enable --now bullet-in.timer bullet-in-warehouse.timer` · 두 명령 · 반대 순서 금지.
6. 전환 기록 — 태스크 8 의 실측 (설치 소요 · 메모리 · 리허설 다섯의 결과 · 첫 사흘 대조).

서식 §2.2 · 서술형 · humanize fast 1회 · `python3 .claude/hooks/check-doc-format.py <파일>`.

- [ ] **Step 3: 커밋 · PR C**

```bash
git -C <워크트리> add CLAUDE.md README.md docs/
git -C <워크트리> commit -m "docs(airflow): 회차가 Airflow 아래에서 도는 법 · 스케줄 문장 여덟 곳 정정"
```

PR C 제목 `docs(airflow): 회차를 Airflow 로 옮긴 뒤의 런북과 스케줄 문장 정정 (안건 2ε · 3/3)`.

---

### Task 8: VM 설치 · 리허설 · 전환 (스펙 §8 · §9.4)

**Files:**
- 없음 (VM 작업) · 결과는 태스크 7 의 런북 §6 과 메모리 트랙에

**Interfaces:**
- Consumes: PR A · B 가 머지되어 VM 에 반영된 상태 (리뷰 채널 「✅ 코드 반영 완료」 둘)

- [ ] **Step 1: 설치만 한다 (DAG 는 일시정지)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
set -e
cd ~/bullet-in
bash infra/airflow/install-airflow.sh
sudo systemd-analyze verify infra/systemd/airflow-*.service infra/systemd/bullet-in-airflow-watch.* || true
bash infra/systemd/install-units.sh
sleep 90
set -a; . ~/airflow/airflow.env; set +a
~/airflow-venv/bin/airflow dags list
~/airflow-venv/bin/airflow dags pause bullet_in_cycle
cat ~/airflow/simple_auth_manager_passwords.json.generated
free -h | head -2
EOF
```

Expected: `bullet_in_cycle` 이 목록에 있고 paused · 유닛 셋 active · 비밀번호 파일이 있다.
메모리 실측 (`free -h` 의 available 변화) 을 적는다.

- [ ] **Step 2: 리허설 — systemd 회차 직후에 손으로 한 번**

회차 시각 (KST 00 · 03 · 06 · 09 · 12 · 15 · 18 · 21시 + 5분) 직후에 돌린다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
set -a; . ~/airflow/airflow.env; set +a
~/airflow-venv/bin/airflow dags unpause bullet_in_cycle
~/airflow-venv/bin/airflow dags trigger bullet_in_cycle
sleep 600
~/airflow-venv/bin/airflow dags list-runs -d bullet_in_cycle -o table | head -5
~/airflow-venv/bin/airflow tasks states-for-dag-run bullet_in_cycle "$(~/airflow-venv/bin/airflow dags list-runs -d bullet_in_cycle -o json | python3 -c 'import sys,json; print(json.load(sys.stdin)[0]["run_id"])')" -o table
~/airflow-venv/bin/airflow dags pause bullet_in_cycle
EOF
```

주의 — `unpause` 는 `catchup=False` 라 최근 구간 실행을 하나 더 만들 수 있다.
`list-runs` 에 실행이 둘이면 그것이고, 둘 다 끝날 때까지 `pause` 를 미룬다.

대조 다섯이다.
같은 값일 필요는 없고 같은 모양이면 된다.

| 대조 | 어디서 | 기대 |
| --- | --- | --- |
| 회차 행 | `SELECT run_id, dag_run_id, fetch_duration_sec, duration_sec, finished_at FROM pipeline_runs ORDER BY started_at DESC LIMIT 2` | 새 행의 `dag_run_id` 가 `manual__…` · `finished_at` 채워짐 |
| 태스크 여덟 | 위 `states-for-dag-run` | advance 부터 judge 까지 success · warehouse_load success |
| 배포 표지 | `curl -sL https://bullet-in.pages.dev/build.json` | `run_id` 가 새 회차 |
| 반영 알림 | 리뷰 채널 | 「판정 대기 없음」 (전진 없는 회차) — `judge` 로그에서 |
| 웨어하우스 | `warehouse_load` 로그 | 적재 행 수 로그 · 오류 없음 |

- [ ] **Step 3: 리허설 넷 (스펙 §9.4)**

- **게이트 건너뜀** — `~/bullet-in/dbt` 의 `profiles.yml` 을 잠깐 없는 포트로 바꾸는 대신, `bullet_in.run` 의 `gate` 를 흉내내지 않고 **실제 세그폴트를 기다리지 않는다**.
  `state/` 에 셸 하나를 두어 `exit 3` 하게 하고 DAG 의 `gate` 명령을 그 셸로 잠깐 바꾼 뒤 (`bash_command` 한 줄 · 커밋하지 않는다) `trigger` → `gate` 가 skipped · `deploy_site` skipped · `judge` 로그에 「판정 대기 없음」 또는 「보류」 → 원복 (`git checkout airflow/dags/bullet_in_cycle.py`).
- **롤백 → unblock → 손 시작** — 2β 런북 §2 와 같되 손 시작이 `airflow dags trigger`.
- **도는 중 롤백** — `trigger` 직후 `uv run python -m bullet_in.deploy rollback` → 그 실행이 끝까지 가는지 · dag-processor 가 다음 파싱에서 되돌린 DAG 를 읽고 오류가 없는지 (`airflow dags list-import-errors`).
- **감시** — `sudo systemctl stop airflow-scheduler` → 다음 `:37` 에 사고 채널 🚨 한 장 · `start` → 다음 시각에는 없음.

- [ ] **Step 4: 전환 (순서가 전부다)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 bash -s <<'EOF'
sudo systemctl disable --now bullet-in.timer bullet-in-warehouse.timer
systemctl list-timers 'bullet-in*' --no-pager
set -a; . ~/airflow/airflow.env; set +a
~/airflow-venv/bin/airflow dags unpause bullet_in_cycle
date
EOF
```

Expected: 타이머 목록에 회차 · 웨어하우스가 없고 DAG 가 unpaused.

- [ ] **Step 5: 첫 사흘 대조 · 되돌림 기준**

- 회차마다 (하루 8회) — 화면의 실행 이력 · 회차 행 · 반영 알림 (머지가 있었으면) 셋.
- 되돌리는 조건 — 연속 두 회차가 Airflow 탓 (스케줄러 · 워커 · 파싱) 으로 안 돌면.
  명령은 런북 §5 의 둘.
- 사흘 뒤 — 태스크 7 의 런북 §6 에 실측을 적고 PR C 를 낸다 · 메모리 트랙 · 안건 표 2ε 행을 ✅ 로.

---

## 자체 점검 (계획을 다 쓴 뒤)

- 스펙 커버리지 — §3.1 범위 (태스크 4 의 `warehouse_load` · 잔류 셋은 `install-units.sh`) · §3.2 태스크 넷 + 넷 (태스크 1 · 4) · §3.3 Postgres (태스크 5) · §3.4 셸 호출 (태스크 4) · §3.5 잔류와 감시 (태스크 5) · §4.1 설치 (태스크 5 · `airflow.cfg` 대신 `airflow.env`) · §4.2 유닛 넷 (태스크 5) · §4.3 DAG (태스크 4) · §4.4 감시 (태스크 5 · 모듈 자리만 다르다) · §5 단계 분리 (태스크 1) · §6.1 전진 (태스크 4) · §6.2 건너뜀과 게이트 안 재시도 (태스크 2 · 4) · §6.3 대응표 (태스크 3) · §6.4 롤백과 DAG 파일 (태스크 8 리허설) · §7 알림 (태스크 4) · §3.3 의 `pg_dump` (태스크 6) · §8 전환 (태스크 8) · §9.1 검증 넷 (태스크 0) · §9.2 단위 (태스크 1 · 2 · 3 · 5 · 6) · §9.3 DAG 파싱 (태스크 4) · §9.4 리허설 (태스크 8) · §11 문서 (태스크 7).
- 스펙과 다른 곳 둘 — 감시 스크립트의 자리 (`infra/airflow/watch.py` → `bullet_in/airflow_watch.py`) · 설정 파일 (`airflow.cfg` → `airflow.env`).
  둘 다 같은 뜻을 더 적은 부품으로 낸다.
  스펙은 고치지 않고 런북 §1 에 실제 자리를 적는다.
- 미검증이 남는 것 — `states-for-dag-run -o json` 의 필드 이름 (`task_id` · `state`) 은 태스크 0 에서 `--help` 만 보므로 태스크 8 의 첫 리허설에서 `state/airflow_states.json` 을 열어 확인한다.
  다르면 `parse_task_states` 한 함수만 고친다.
