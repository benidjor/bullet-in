# 배포 자동화 (안건 2β) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 머지된 코드를 회차 유닛이 시작에서 스스로 내려받고, 끝에서 첫 회차를 판정하고, 실패하면 직전 커밋으로 되돌리며, 결과를 디스코드로 알린다.

**구조:** 새 모듈 `src/bullet_in/deploy.py` 하나에 명령 넷 (`advance` · `judge` · `rollback` · `unblock`) 과 내부 명령 `preflight` 를 둔다.
`bullet-in.service` 의 `ExecStartPre` 가 `advance` 를, `ExecStopPost` 가 `judge` 를 부른다.
상태는 `state/deploy.json` 한 파일이고, 배포본 표지는 `run.py` 가 쓰는 `site/build.json` 이다.
게이트는 dbt 가 신호로 죽었을 때만 종료 코드 3 을 내어 판정기가 `$EXIT_STATUS` 하나로 급사와 나머지를 가른다.

**스택:** Python 3.11 · subprocess 로 git 호출 · httpx (이미 의존) · systemd `ExecStopPost=` · pytest (임시 git 저장소).

**스펙:** `docs/superpowers/specs/2026-09-03-deploy-automation-design.md`

## 전역 제약

- 전진 실패로 회차를 잃지 않는다.
  `advance` 는 어떤 경로로도 0 이 아닌 코드로 끝나지 않고, 유닛에서도 `ExecStartPre=-` 로 감싼다 (스펙 §4.3).
- `judge` 는 유닛 결과를 바꾸지 않는다.
  예외로 죽으면 사고 채널에 알리고 0 으로 끝낸다 (스펙 §6.2).
- `ff-only` 거부는 자동으로 풀지 않는다 (스펙 §5 4번).
- 빈 응답 · 비 200 · JSON 아님 · 해시 불일치를 전부 「표지 불일치」 로 센다 (스펙 §6.1).
- 알림은 전진 한 번에 한 번이다 (스펙 §10).
- `REQUIRED_ENV` 의 잣대는 「없으면 유닛 다섯 중 하나가 조용히 반쯤 도는 키」 다 (스펙 §9.1).
- 명사형 종결 · 문서 서식 §2.2 · 커밋 트레일러는 `CLAUDE.md` 와 컨벤션을 따른다.
- 테스트는 워크트리에서 `uv run --project <워크트리> --extra dev pytest` 로 돌린다.
- **PR 은 태스크 1 에서 6 을 하나로 묶는다.**
  순수 코드가 200줄을 넘는 사유는 「모듈 하나가 통째로 새로 생기고 유닛이 그 모듈을 부르므로 갈라 머지하면 중간 상태가 배포된다」 이다.
- 태스크 7 (마지막 손배포 · 라이브 리허설) 은 머지 뒤에 하고 PR 에 넣지 않는다.

---

## 파일 구조

| 파일 | 역할 |
| --- | --- |
| `src/bullet_in/deploy.py` (신규) | 상태 파일 · git 래퍼 · 사전 점검 · 전진 · 판정 · 롤백 · 표지 · CLI |
| `src/bullet_in/dbt_gate.py` | `GateResult.dbt_returncode` · `GATE_CRASH_EXIT = 3` · `enforce_gate` 의 종료 코드 분기 |
| `src/bullet_in/run.py` | 게이트 직전에 `write_build_marker("site", run_id=run_id)` 한 줄 |
| `infra/systemd/bullet-in.service` | `ExecStartPre=-… advance` · `ExecStopPost=… judge` 두 줄 |
| `.github/PULL_REQUEST_TEMPLATE.md` | §6 체크리스트 한 줄 |
| `.github/workflows/ci.yml` | 「이 CI 가 안 보는 것」 의 배포 줄 |
| `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md` (신규) | 알림 여섯을 받았을 때 각각 무엇을 보고 무엇을 치는지 |
| `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` | §2 「코드 반영」 을 자동 전진으로 |
| `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` | §3 의 `uv sync` 줄 정정 |
| `CLAUDE.md` | 스케줄 문단에 전진 · 판정 한 줄 |
| `tests/test_deploy.py` (신규) | 임시 git 저장소로 전진 · 롤백 · 판정 · 표지 · 사전 점검 |
| `tests/test_dbt_gate.py` | 신호 종료 케이스 둘 |

`deploy.py` 안의 이름은 이렇다.
뒤 태스크가 앞 태스크의 이름을 그대로 쓴다.

```python
STATE_PATH = Path("state/deploy.json")
BUILD_URL = "https://bullet-in.pages.dev/build.json"
REQUIRED_ENV: tuple[str, ...]

@dataclass
class DeployState: current, previous, pending, blocked, advanced_at
def load_state(path=STATE_PATH) -> DeployState
def save_state(state, path=STATE_PATH) -> None

class Repo:                       # git 래퍼 · 전부 subprocess
    head() -> str · fetch() -> bool · remote_main() -> str
    ff_merge() -> bool · reset_hard(sha) -> None · status_short() -> str

def preflight(environ=os.environ) -> list[str]          # 빈 목록 = 통과
def run_preflight_subprocess() -> list[str]             # 새 uv run 으로 preflight 를 부른다
def advance(repo, state, *, run_preflight=run_preflight_subprocess) -> str

@dataclass(frozen=True)
class Verdict: action ("none" | "confirm" | "hold" | "rollback") · reason
def decide(state, service_result: str, exit_status: str) -> Verdict
def fetch_build(url=BUILD_URL) -> dict | None
def build_matches(sha, *, fetch=fetch_build, tries=3, wait=20.0) -> tuple[bool, str]
def rollback(repo, state, *, reason: str) -> str
def unblock(state, sha_prefix: str) -> int
def judge(repo, state, *, service_result, exit_status, matches=build_matches) -> str
def write_build_marker(site_dir, *, run_id: str, repo_root=Path(".")) -> Path
def main(argv=None) -> int
```

---

### Task 1: 게이트가 신호 종료를 종료 코드 3 으로 낸다

**Files:**
- Modify: `src/bullet_in/dbt_gate.py` (`GateResult` · `run_gate` · `enforce_gate`)
- Test: `tests/test_dbt_gate.py`

**Interfaces:**
- Produces: `dbt_gate.GATE_CRASH_EXIT = 3` · `GateResult.dbt_returncode: int | None` · `enforce_gate` 가 신호 종료면 `SystemExit(3)`, 나머지 차단은 `SystemExit(1)`.
- Task 4 의 `decide` 가 `GATE_CRASH_EXIT` 를 import 한다.

- [ ] **Step 1: 실패하는 테스트 둘을 쓴다**

`tests/test_dbt_gate.py` 끝에 붙인다.

```python
def test_run_gate_records_dbt_returncode(tmp_path, monkeypatch):
    # 판정기는 저널을 안 읽는다 — 종료 코드가 결과에 실려 있어야 급사를 가른다.
    def fake_run(*args, **kwargs):
        return _FakeProc(-11, stdout="23 of 29 START ...")   # run_results.json 을 안 쓴다

    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")
    assert r.ran is False
    assert r.dbt_returncode == -11


def test_enforce_gate_exits_3_when_dbt_died_by_signal(monkeypatch):
    # 2026-08-31 · 2026-09-03 세그폴트 (안건 2ν): 코드 탓이 아니라 롤백하면 안 된다.
    sent = {}
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: sent.update(kw))
    result = GateResult(ran=False, error="종료코드 -11", dbt_returncode=-11)
    with pytest.raises(SystemExit) as e:
        enforce_gate(result, run_id="r1")
    assert e.value.code == GATE_CRASH_EXIT == 3
    assert sent   # 게이트 알림은 그대로 나간다


def test_enforce_gate_keeps_exit_1_when_dbt_failed_with_its_own_code(monkeypatch):
    # profile 오류 · 접속 실패 (종료 코드 1 · 2) 는 코드 의심이라 1 에 남는다.
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: None)
    result = GateResult(ran=False, error="종료코드 2", dbt_returncode=2)
    with pytest.raises(SystemExit) as e:
        enforce_gate(result, run_id="r1")
    assert e.value.code == 1
```

파일 머리의 import 줄에 `GATE_CRASH_EXIT` 를 더한다.

```python
from bullet_in.dbt_gate import (GATE_CRASH_EXIT, GateResult, TestOutcome, dbt_env,
                                enforce_gate, parse_results, run_gate)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_dbt_gate.py -q`
Expected: ImportError (`GATE_CRASH_EXIT`) 로 수집 단계에서 실패.

- [ ] **Step 3: 구현한다**

`GateResult` 에 필드 하나와 상수 하나를 더한다.

```python
# 게이트가 못 돈 것 중 dbt 가 신호로 죽은 경우 (세그폴트 · 강제 종료) 의 종료 코드.
# 판정기 (deploy.judge) 가 $EXIT_STATUS 하나로 「급사」 와 나머지를 가른다 (스펙 §8).
GATE_CRASH_EXIT = 3


@dataclass(frozen=True)
class GateResult:
    blocked: list[TestOutcome] = field(default_factory=list)
    warned: list[TestOutcome] = field(default_factory=list)
    ran: bool = True
    error: str | None = None
    dbt_returncode: int | None = None
```

`run_gate` 에서 `subprocess.run` 뒤의 세 `return` 에 `dbt_returncode=proc.returncode` 를 싣는다.
`parse_results` 가 돌려준 정상 결과도 종료 코드를 실어야 하므로 마지막 줄은 `dataclasses.replace` 로 바꾼다.

```python
    result = parse_results(results_path)
    diag = _diagnosis(proc, Path(project_dir))
    if not result.ran:
        return GateResult(ran=False, error=f"{result.error} · {diag}",
                          dbt_returncode=proc.returncode)
    if proc.returncode != 0 and not result.blocked:
        return GateResult(ran=False,
                          error=f"결과 파일엔 차단 항목이 없는데 dbt 가 실패로 끝났다 · {diag}",
                          dbt_returncode=proc.returncode)
    return replace(result, dbt_returncode=proc.returncode)
```

`from dataclasses import dataclass, field, replace` 로 import 를 고친다.

`enforce_gate` 의 마지막 줄을 바꾼다.

```python
    # 신호로 죽은 것 (음수) 만 3 — 코드 탓이 아닌 유일한 실패라 판정기가 되돌리지 않는다.
    crashed = not result.ran and (result.dbt_returncode or 0) < 0
    raise SystemExit(GATE_CRASH_EXIT if crashed else 1)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_dbt_gate.py -q`
Expected: 전부 PASS (기존 케이스도 그대로).

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/dbt_gate.py tests/test_dbt_gate.py
git -C <워크트리> commit -m "feat(gate): dbt 가 신호로 죽으면 종료 코드 3 으로 끝낸다"
```

---

### Task 2: 상태 파일과 판정 함수

**Files:**
- Create: `src/bullet_in/deploy.py`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `DeployState` · `load_state` · `save_state` · `Verdict` · `decide` · `REQUIRED_ENV` · `STATE_PATH` · `BUILD_URL`.
- Consumes: `dbt_gate.GATE_CRASH_EXIT` (Task 1).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_deploy.py` 를 만든다.

```python
"""배포 자동화 (스펙 2026-09-03) — 상태 · 판정 · 전진 · 롤백 · 표지."""
import json
from pathlib import Path

import pytest

from bullet_in.deploy import DeployState, Verdict, decide, load_state, save_state


def test_state_roundtrip_and_defaults(tmp_path):
    p = tmp_path / "deploy.json"
    assert load_state(p) == DeployState()          # 파일이 없으면 기본값
    s = DeployState(current="n" * 40, previous="p" * 40, pending=True,
                    blocked=["b" * 40], advanced_at="2026-09-04T00:03:12+00:00")
    save_state(s, p)
    assert load_state(p) == s
    assert json.loads(p.read_text())["pending"] is True


def test_decide_does_nothing_without_pending():
    assert decide(DeployState(pending=False), "exit-code", "1").action == "none"


@pytest.mark.parametrize("service_result,exit_status,action", [
    ("success", "0", "confirm"),
    ("exit-code", "3", "hold"),        # 게이트 급사 (dbt 세그폴트) — 되돌리지 않는다
    ("exit-code", "1", "rollback"),    # 예외 · 게이트 위반 · dbt 자체 실패
    ("timeout", "", "rollback"),
    ("signal", "9", "rollback"),
])
def test_decide_follows_the_spec_table(service_result, exit_status, action):
    v = decide(DeployState(pending=True), service_result, exit_status)
    assert isinstance(v, Verdict)
    assert v.action == action
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: `ModuleNotFoundError: bullet_in.deploy`.

- [ ] **Step 3: 모듈의 첫 부분을 쓴다**

```python
"""머지된 코드를 회차가 스스로 반영하고 판정한다.

설계 = docs/superpowers/specs/2026-09-03-deploy-automation-design.md

명령 넷 — advance (회차 시작 · ExecStartPre) · judge (회차 끝 · ExecStopPost) ·
rollback (사람이) · unblock (사람이). preflight 는 advance 가 새 코드로 부르는 내부 명령.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from bullet_in import notify
from bullet_in.dbt_gate import GATE_CRASH_EXIT

log = logging.getLogger(__name__)

STATE_PATH = Path("state/deploy.json")
BUILD_URL = "https://bullet-in.pages.dev/build.json"

# 없으면 유닛 다섯 중 하나가 조용히 반쯤 도는 키 (스펙 §9.1). 죽는 키는 OnFailure 가 잡으므로
# 이 목록의 값어치는 조용한 쪽에 있다. 새 기능이 키를 더하면 같은 PR 에서 여기에 올린다.
REQUIRED_ENV: tuple[str, ...] = (
    "MARIADB_URL", "MONGO_URI", "GEMINI_API_KEY",
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "DISCORD_WEBHOOK_INCIDENT", "DISCORD_WEBHOOK_REVIEW",
    "GA4_DATASET",
    "ICEBERG_CATALOG_URI", "ICEBERG_WAREHOUSE", "GCS_BACKUP_BUCKET",
)


@dataclass
class DeployState:
    current: str = ""
    previous: str = ""
    pending: bool = False
    blocked: list[str] = field(default_factory=list)
    advanced_at: str = ""


def load_state(path: Path = STATE_PATH) -> DeployState:
    try:
        return DeployState(**json.loads(Path(path).read_text()))
    except (OSError, ValueError, TypeError):
        return DeployState()


def save_state(state: DeployState, path: Path = STATE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(asdict(state), ensure_ascii=False, indent=1))


@dataclass(frozen=True)
class Verdict:
    action: str    # none · confirm · hold · rollback
    reason: str


def decide(state: DeployState, service_result: str, exit_status: str) -> Verdict:
    """유닛 결과 하나와 종료 코드 하나로 판정한다 (스펙 §6 표).

    원인은 모른다 — 「무엇이 보이면」 으로만 적는다. 넓게 되돌리는 대신 알림이
    원인을 단정하지 않는다 (스펙 §3.2).
    """
    if not state.pending:
        return Verdict("none", "판정 대기 없음")
    if service_result == "success":
        return Verdict("confirm", "회차 · 게이트 · 배포 통과")
    if service_result == "exit-code" and exit_status == str(GATE_CRASH_EXIT):
        return Verdict("hold", "게이트 급사 (dbt 신호 종료) — 다음 회차에 다시 판정")
    return Verdict("rollback", f"유닛 결과 {service_result} · 종료 코드 {exit_status or '?'}")
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: 7 passed.

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/deploy.py tests/test_deploy.py
git -C <워크트리> commit -m "feat(deploy): 배포 상태 파일과 첫 회차 판정 함수"
```

---

### Task 3: git 래퍼 · 사전 점검 · 전진

**Files:**
- Modify: `src/bullet_in/deploy.py`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `Repo(root)` (`head` · `fetch` · `remote_main` · `ff_merge` · `reset_hard` · `status_short`) · `preflight(environ)` · `run_preflight_subprocess()` · `advance(repo, state, *, run_preflight)` · `_alert(title, description, *, incident, fields=None)`.
- Consumes: `DeployState` (Task 2).

- [ ] **Step 1: 임시 git 저장소 픽스처와 실패하는 테스트를 쓴다**

`tests/test_deploy.py` 에 붙인다.

```python
import os
import subprocess

from bullet_in.deploy import Repo, advance, preflight

_GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env=_GIT_ENV).stdout.strip()


def _commit(repo_dir: Path, text: str) -> str:
    (repo_dir / "a.txt").write_text(text)
    _git(repo_dir, "add", "a.txt")
    _git(repo_dir, "commit", "-qm", text)
    return _git(repo_dir, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    """upstream (= GitHub 의 main) 과 vm (= VM 체크아웃). vm 은 upstream 을 origin 으로 본다."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    _commit(upstream, "c1")
    vm = tmp_path / "vm"
    _git(tmp_path, "clone", "-q", str(upstream), str(vm))
    return upstream, vm


@pytest.fixture
def quiet_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr("bullet_in.notify.send_alert", lambda **kw: sent.append(kw))
    return sent


def test_advance_noop_when_up_to_date(repos, quiet_alerts):
    upstream, vm = repos
    state = DeployState()
    out = advance(Repo(vm), state, run_preflight=lambda: [])
    assert "변경 없음" in out
    assert state.pending is False
    assert quiet_alerts == []


def test_advance_moves_to_new_commit_and_marks_pending(repos, quiet_alerts):
    upstream, vm = repos
    old = _git(vm, "rev-parse", "HEAD")
    new = _commit(upstream, "c2")
    state = DeployState()
    advance(Repo(vm), state, run_preflight=lambda: [])
    assert _git(vm, "rev-parse", "HEAD") == new
    assert (state.previous, state.current, state.pending) == (old, new, True)
    assert state.advanced_at
    assert quiet_alerts == []          # 성공 알림은 판정 뒤에 낸다 (전진 한 번에 알림 한 번)


def test_advance_skips_a_blocked_commit(repos, quiet_alerts):
    upstream, vm = repos
    old = _git(vm, "rev-parse", "HEAD")
    new = _commit(upstream, "c2")
    state = DeployState(blocked=[new])
    out = advance(Repo(vm), state, run_preflight=lambda: [])
    assert "차단" in out
    assert _git(vm, "rev-parse", "HEAD") == old


def test_advance_refuses_when_preflight_fails_and_resets(repos, quiet_alerts):
    upstream, vm = repos
    old = _git(vm, "rev-parse", "HEAD")
    new = _commit(upstream, "c2")
    state = DeployState()
    out = advance(Repo(vm), state, run_preflight=lambda: ["필수 키 없음: GA4_DATASET"])
    assert "사전 점검" in out
    assert _git(vm, "rev-parse", "HEAD") == old     # 새 코드로 회차를 돌리지 않는다
    assert state.blocked == [new]
    assert state.pending is False
    assert len(quiet_alerts) == 1
    assert "GA4_DATASET" in json.dumps(quiet_alerts[0], ensure_ascii=False)


def test_advance_alerts_and_keeps_code_when_ff_is_refused(repos, quiet_alerts):
    upstream, vm = repos
    _commit(upstream, "c2")
    local = _commit(vm, "누가 VM 에서 직접 커밋")       # 갈라짐
    state = DeployState()
    out = advance(Repo(vm), state, run_preflight=lambda: [])
    assert "ff 거부" in out
    assert _git(vm, "rev-parse", "HEAD") == local       # 자동으로 reset 하지 않는다
    assert len(quiet_alerts) == 1


def test_advance_never_raises(repos, quiet_alerts, monkeypatch):
    upstream, vm = repos
    _commit(upstream, "c2")
    def boom():
        raise RuntimeError("uv 가 죽었다")
    state = DeployState()
    out = advance(Repo(vm), state, run_preflight=boom)
    assert "예외" in out
    assert len(quiet_alerts) == 1


def test_preflight_reports_missing_keys_and_import_error(monkeypatch):
    def bad_import(name):
        raise ImportError("no module named foo")
    monkeypatch.setattr("bullet_in.deploy.importlib.import_module", bad_import)
    problems = preflight({"MARIADB_URL": "x"})
    assert any("import" in p for p in problems)
    assert any("GEMINI_API_KEY" in p for p in problems)


def test_preflight_passes_with_everything(monkeypatch):
    monkeypatch.setattr("bullet_in.deploy.importlib.import_module", lambda name: None)
    from bullet_in.deploy import REQUIRED_ENV
    assert preflight({k: "x" for k in REQUIRED_ENV}) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: ImportError (`Repo` · `advance` · `preflight`).

- [ ] **Step 3: 구현한다**

`deploy.py` 의 `decide` 아래에 붙인다.

```python
# ── git ──────────────────────────────────────────────────────────────────────

class Repo:
    """VM 체크아웃에 대한 git 호출. 전부 subprocess 라 테스트는 임시 저장소로 돈다."""

    def __init__(self, root: Path = Path(".")):
        self.root = Path(root)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.root, check=check,
                              capture_output=True, text=True, timeout=120)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def remote_main(self) -> str:
        return self._git("rev-parse", "origin/main").stdout.strip()

    def fetch(self) -> bool:
        return self._git("fetch", "origin", "--quiet", check=False).returncode == 0

    def ff_merge(self) -> bool:
        return self._git("merge", "--ff-only", "--quiet", "origin/main",
                         check=False).returncode == 0

    def reset_hard(self, sha: str) -> None:
        self._git("reset", "--hard", "--quiet", sha)

    def status_short(self) -> str:
        return self._git("status", "--short", "--branch", check=False).stdout.strip()[:800]


# ── 알림 ──────────────────────────────────────────────────────────────────────

def _alert(title: str, description: str, *, incident: bool,
           fields: list[dict] | None = None) -> None:
    notify.send_alert(title, description, color=notify.COLOR_FAILURE if incident
                      else notify.COLOR_CANDIDATE, fields=fields, footer="bullet-in deploy",
                      channel=notify.CHANNEL_INCIDENT if incident else notify.CHANNEL_REVIEW)


def _short(sha: str) -> str:
    return sha[:7]


# ── 사전 점검 · 전진 ───────────────────────────────────────────────────────────

def preflight(environ=os.environ) -> list[str]:
    """새 코드가 돌 수 있는지 회차 전에 본다. 빈 목록이 통과다 (스펙 §5 5번)."""
    problems: list[str] = []
    try:
        importlib.import_module("bullet_in.run")
    except Exception as e:  # noqa: BLE001 — 어떤 import 오류든 한 줄로 실어 알린다
        problems.append(f"import 실패: {type(e).__name__}: {e}"[:300])
    missing = [k for k in REQUIRED_ENV if not environ.get(k)]
    if missing:
        problems.append("필수 키 없음: " + " · ".join(missing))
    return problems


def _uv() -> str:
    # 유닛의 PATH 에는 ~/.local/bin 이 없다 — 유닛 파일이 절대 경로로 부르는 것과 같은 자리.
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def run_preflight_subprocess() -> list[str]:
    """새 프로세스로 preflight 를 부른다.

    같은 프로세스에서 import 하면 옛 코드가 이미 올라와 있고 잠금 파일도 옛것이다.
    `uv run` 을 새로 타야 새 코드 · 새 의존으로 검사한다 (스펙 §5 5번).
    """
    proc = subprocess.run([_uv(), "run", "python", "-m", "bullet_in.deploy", "preflight"],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode == 0:
        return []
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
    return tail or [f"preflight 종료 코드 {proc.returncode}"]


def advance(repo: Repo, state: DeployState, *,
            run_preflight=run_preflight_subprocess) -> str:
    """회차 시작에 코드를 전진시킨다. 어느 경로로도 예외를 밖으로 내지 않는다 (스펙 §5)."""
    try:
        if not repo.fetch():
            return "fetch 실패 — 현재 코드로 계속 (다음 회차에 다시)"
        head, target = repo.head(), repo.remote_main()
        if target == head:
            return "변경 없음"
        if target in state.blocked:
            return f"{_short(target)} 은 차단 목록 — 새 커밋을 기다림"
        if not repo.ff_merge():
            _alert("🚧 코드 전진 — VM 트리가 갈라졌다",
                   f"`origin/main` {_short(target)} 을 ff 로 못 얹는다 · 현재 {_short(head)} 로 회차를 돌린다 · "
                   "자동으로 되돌리지 않는다 — 사람이 VM 에서 `git status` 를 본다",
                   incident=True, fields=[{"name": "git status", "value": repo.status_short() or "-"}])
            return "ff 거부 — 현재 코드로 계속"
        problems = run_preflight()
        if problems:
            repo.reset_hard(head)
            state.blocked.append(target)
            _alert("🚧 코드 전진 거부 — 사전 점검 실패",
                   f"{_short(target)} 을 내려받았다가 {_short(head)} 로 되돌렸다 · 이번 회차는 직전 코드로 돈다 · "
                   "고친 커밋이 main 에 오면 다시 전진한다",
                   incident=True, fields=[{"name": "사유", "value": "\n".join(f"- {p}" for p in problems)[:1024]}])
            return "사전 점검 실패 — 되돌림"
        state.previous, state.current, state.pending = head, target, True
        state.advanced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return f"전진 {_short(head)} → {_short(target)} · 회차 끝에 판정"
    except Exception as e:  # noqa: BLE001 — 전진 실패로 회차를 잃지 않는다
        log.exception("advance 예외")
        _alert("🚧 코드 전진 — 예외", f"{type(e).__name__}: {e}"[:1000], incident=True)
        return f"예외 — 현재 코드로 계속 ({type(e).__name__})"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: 전부 PASS.
`test_advance_never_raises` 는 `run_preflight` 가 던진 예외를 잡고 알림 하나를 낸 뒤 문자열을 돌려줘야 한다.

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/deploy.py tests/test_deploy.py
git -C <워크트리> commit -m "feat(deploy): 회차 시작에 origin/main 을 내려받고 사전 점검으로 거른다"
```

---

### Task 4: 롤백 · unblock · 표지 대조 · 판정

**Files:**
- Modify: `src/bullet_in/deploy.py`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `rollback(repo, state, *, reason)` · `unblock(state, sha_prefix)` · `fetch_build(url)` · `build_matches(sha, *, fetch, tries, wait)` · `judge(repo, state, *, service_result, exit_status, matches)`.
- Consumes: `Repo` · `advance` (Task 3) · `decide` (Task 2).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from bullet_in.deploy import build_matches, judge, rollback, unblock


def _advanced(repos):
    """c1 에서 c2 로 전진해 pending 인 상태를 만든다."""
    upstream, vm = repos
    old = _git(vm, "rev-parse", "HEAD")
    new = _commit(upstream, "c2")
    state = DeployState()
    advance(Repo(vm), state, run_preflight=lambda: [])
    return vm, state, old, new


def test_rollback_resets_blocks_and_alerts(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    rollback(Repo(vm), state, reason="시험")
    assert _git(vm, "rev-parse", "HEAD") == old
    assert state.blocked == [new]
    assert state.pending is False
    assert len(quiet_alerts) == 1
    text = json.dumps(quiet_alerts[0], ensure_ascii=False)
    assert "코드 탓이 아닐 수 있다" in text          # 넓게 되돌리는 대가 (스펙 §3.2)
    assert "unblock" in text


def test_unblock_removes_by_prefix():
    state = DeployState(blocked=["a" * 40, "b" * 40])
    assert unblock(state, "aaaaaaa") == 1
    assert state.blocked == ["b" * 40]
    assert unblock(state, "zzz") == 0


def test_build_matches_retries_then_matches():
    answers = iter([None, {"commit": "other"}, {"commit": "n" * 40}])
    ok, detail = build_matches("n" * 40, fetch=lambda: next(answers), tries=3, wait=0)
    assert ok is True


def test_build_matches_fails_on_empty_and_mismatch():
    ok, detail = build_matches("n" * 40, fetch=lambda: None, tries=2, wait=0)
    assert ok is False
    assert "비정상 응답" in detail
    ok, detail = build_matches("n" * 40, fetch=lambda: {"commit": "o" * 40}, tries=1, wait=0)
    assert ok is False
    assert "ooooooo" in detail


def test_judge_confirms_when_build_matches(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    out = judge(Repo(vm), state, service_result="success", exit_status="0",
                matches=lambda sha: (True, sha[:7]))
    assert "반영 완료" in out
    assert state.pending is False
    assert len(quiet_alerts) == 1
    assert quiet_alerts[0]["channel"] == "review"


def test_judge_alerts_but_keeps_code_when_build_mismatches(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    judge(Repo(vm), state, service_result="success", exit_status="0",
          matches=lambda sha: (False, "비정상 응답"))
    assert _git(vm, "rev-parse", "HEAD") == new       # F7 은 코드 탓이 아니다
    assert state.pending is False
    assert quiet_alerts[0]["channel"] == "incident"


def test_judge_holds_on_gate_crash(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    judge(Repo(vm), state, service_result="exit-code", exit_status="3")
    assert _git(vm, "rev-parse", "HEAD") == new
    assert state.pending is True                       # 다음 회차에 다시 판정
    assert quiet_alerts[0]["channel"] == "review"


def test_judge_rolls_back_on_any_other_failure(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    judge(Repo(vm), state, service_result="exit-code", exit_status="1")
    assert _git(vm, "rev-parse", "HEAD") == old
    assert state.blocked == [new]
    assert quiet_alerts[0]["channel"] == "incident"


def test_judge_does_nothing_when_not_pending(repos, quiet_alerts):
    upstream, vm = repos
    out = judge(Repo(vm), DeployState(), service_result="exit-code", exit_status="1")
    assert "대기 없음" in out
    assert quiet_alerts == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: ImportError (`rollback` 등).

- [ ] **Step 3: 구현한다**

`advance` 아래에 붙인다.

```python
# ── 롤백 · 표지 · 판정 ─────────────────────────────────────────────────────────

def rollback(repo: Repo, state: DeployState, *, reason: str) -> str:
    """직전 커밋으로 되돌리고 현재 커밋을 차단한다. 자동 · 수동이 같은 함수다 (스펙 §7)."""
    bad, good = state.current, state.previous
    repo.reset_hard(good)
    if bad and bad not in state.blocked:
        state.blocked.append(bad)
    state.pending = False
    _alert("⏪ 코드 롤백 — 직전 커밋으로 되돌렸다",
           f"{_short(bad)} → {_short(good)} · 사유: {reason}\n"
           "**코드 탓이 아닐 수 있다** — DB 다운 · 데이터 부채로 실패한 회차도 같은 모양이다 · "
           "새 커밋이 main 에 오면 다시 전진한다 · 같은 커밋을 다시 보려면 "
           f"`uv run python -m bullet_in.deploy unblock {_short(bad)}`",
           incident=True,
           fields=[{"name": "저널", "value": "`journalctl -u bullet-in.service -n 200 --no-pager`",
                    "inline": False}])
    return f"롤백 {_short(bad)} → {_short(good)}"


def unblock(state: DeployState, sha_prefix: str) -> int:
    before = len(state.blocked)
    state.blocked = [s for s in state.blocked if not s.startswith(sha_prefix)]
    return before - len(state.blocked)


def fetch_build(url: str = BUILD_URL) -> dict | None:
    """라이브의 build.json. 비 200 · 0바이트 · JSON 아님은 전부 None 이다 (스펙 §6.1)."""
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20)
    except httpx.HTTPError as e:
        log.warning("build.json 수신 실패: %s", e)
        return None
    if r.status_code != 200 or not r.content:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def build_matches(sha: str, *, fetch=fetch_build, tries: int = 3,
                  wait: float = 20.0) -> tuple[bool, str]:
    """최상위 도메인이 배포 직후 잠깐 옛 것을 돌려주므로 몇 번 다시 받는다."""
    detail = "비정상 응답"
    for i in range(tries):
        data = fetch()
        got = (data or {}).get("commit") if data else None
        if got == sha:
            return True, _short(sha)
        detail = _short(got) if isinstance(got, str) and got else "비정상 응답"
        if i < tries - 1:
            time.sleep(wait)
    return False, detail


def judge(repo: Repo, state: DeployState, *, service_result: str, exit_status: str,
          matches=build_matches) -> str:
    """회차 끝에 systemd 가 준 결과로 판정한다 (스펙 §6 표)."""
    v = decide(state, service_result, exit_status)
    if v.action == "none":
        return v.reason
    if v.action == "rollback":
        return rollback(repo, state, reason=v.reason)
    if v.action == "hold":
        _alert("⏸ 코드 반영 판정 보류", f"{_short(state.current)} · {v.reason}", incident=False)
        return "판정 보류"
    ok, detail = matches(state.current)
    state.pending = False
    if ok:
        _alert("✅ 코드 반영 완료",
               f"{_short(state.previous)} → {_short(state.current)} · 첫 회차 통과 · 라이브 표지 일치 ({detail})",
               incident=False)
        return "반영 완료"
    _alert("🚧 배포는 나갔는데 라이브 표지가 다르다",
           f"기대 {_short(state.current)} · 받은 것 {detail} · 코드는 되돌리지 않는다 (F7) · "
           "몇 분 뒤 `curl -sL https://bullet-in.pages.dev/build.json` 으로 다시 본다",
           incident=True)
    return "표지 불일치"
```

- [ ] **Step 4: 통과를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git -C <워크트리> add src/bullet_in/deploy.py tests/test_deploy.py
git -C <워크트리> commit -m "feat(deploy): 회차 끝 판정과 롤백 · 라이브 표지 대조"
```

---

### Task 5: CLI 와 배포본 표지

**Files:**
- Modify: `src/bullet_in/deploy.py` (`write_build_marker` · `main`)
- Modify: `src/bullet_in/run.py` (게이트 호출 직전 한 줄 · import 한 줄)
- Test: `tests/test_deploy.py`

**Interfaces:**
- Produces: `write_build_marker(site_dir, *, run_id, repo_root)` · `python -m bullet_in.deploy {advance|judge|preflight|rollback|unblock <sha>}`.
- `judge` CLI 는 `$SERVICE_RESULT` · `$EXIT_STATUS` 를 읽는다 (systemd 가 `ExecStopPost` 에 준다).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from bullet_in.deploy import main, write_build_marker


def test_write_build_marker_records_head(repos, tmp_path):
    upstream, vm = repos
    site = tmp_path / "site"
    site.mkdir()
    p = write_build_marker(site, run_id="abc", repo_root=vm)
    data = json.loads(p.read_text())
    assert data["commit"] == _git(vm, "rev-parse", "HEAD")
    assert data["run_id"] == "abc"
    assert data["rendered_at"].endswith("+00:00")


def test_cli_unblock_and_rollback_use_the_state_file(repos, tmp_path, quiet_alerts, monkeypatch):
    vm, state, old, new = _advanced(repos)
    state_path = tmp_path / "deploy.json"
    save_state(state, state_path)
    monkeypatch.setattr("bullet_in.deploy.STATE_PATH", state_path)
    monkeypatch.chdir(vm)
    assert main(["rollback"]) == 0
    assert _git(vm, "rev-parse", "HEAD") == old
    assert load_state(state_path).blocked == [new]
    assert main(["unblock", new[:7]]) == 0
    assert load_state(state_path).blocked == []


def test_cli_judge_reads_systemd_variables(repos, tmp_path, quiet_alerts, monkeypatch):
    vm, state, old, new = _advanced(repos)
    state_path = tmp_path / "deploy.json"
    save_state(state, state_path)
    monkeypatch.setattr("bullet_in.deploy.STATE_PATH", state_path)
    monkeypatch.setattr("bullet_in.deploy.build_matches", lambda sha: (True, sha[:7]))
    monkeypatch.setenv("SERVICE_RESULT", "success")
    monkeypatch.setenv("EXIT_STATUS", "0")
    monkeypatch.chdir(vm)
    assert main(["judge"]) == 0
    assert load_state(state_path).pending is False


def test_cli_judge_exits_zero_even_when_it_blows_up(repos, tmp_path, quiet_alerts, monkeypatch):
    # 판정기가 유닛 결과를 바꾸면 안 된다 (스펙 §6.2).
    vm, state, old, new = _advanced(repos)
    state_path = tmp_path / "deploy.json"
    save_state(state, state_path)
    monkeypatch.setattr("bullet_in.deploy.STATE_PATH", state_path)
    def boom(*a, **k):
        raise RuntimeError("git 이 사라졌다")
    monkeypatch.setattr("bullet_in.deploy.judge", boom)
    monkeypatch.setenv("SERVICE_RESULT", "success")
    assert main(["judge"]) == 0
    assert len(quiet_alerts) == 1
```

- [ ] **Step 2: 실패를 확인한다**

Run: `uv run --project <워크트리> --extra dev pytest tests/test_deploy.py -q`
Expected: ImportError (`main` · `write_build_marker`).

- [ ] **Step 3: 구현한다**

`deploy.py` 끝에 붙인다.

```python
# ── 표지 · CLI ────────────────────────────────────────────────────────────────

def write_build_marker(site_dir: str | Path, *, run_id: str,
                       repo_root: Path = Path(".")) -> Path:
    """배포본에 커밋 표지를 싣는다 (스펙 §4.4). 판정기가 라이브에서 이것을 읽는다."""
    try:
        sha = Repo(repo_root).head()
    except (OSError, subprocess.SubprocessError):
        sha = "unknown"
    p = Path(site_dir) / "build.json"
    p.write_text(json.dumps({"commit": sha, "run_id": run_id,
                             "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="머지된 코드의 자동 반영 · 판정 · 롤백")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("advance", help="회차 시작 — origin/main 을 내려받는다 (ExecStartPre)")
    sub.add_parser("judge", help="회차 끝 — $SERVICE_RESULT · $EXIT_STATUS 로 판정 (ExecStopPost)")
    sub.add_parser("preflight", help="새 코드가 돌 수 있는지 (advance 가 새 uv run 으로 부른다)")
    sub.add_parser("rollback", help="사람이 — 직전 커밋으로 되돌리고 현재 커밋을 차단")
    ub = sub.add_parser("unblock", help="사람이 — 차단 목록에서 뺀다")
    ub.add_argument("sha")
    args = ap.parse_args(argv)

    if args.command == "preflight":
        problems = preflight()
        for p in problems:
            print(p)
        return 1 if problems else 0

    state = load_state(STATE_PATH)
    repo = Repo(Path("."))
    try:
        if args.command == "advance":
            out = advance(repo, state)
        elif args.command == "judge":
            out = judge(repo, state, service_result=os.environ.get("SERVICE_RESULT", ""),
                        exit_status=os.environ.get("EXIT_STATUS", ""))
        elif args.command == "rollback":
            out = rollback(repo, state, reason="수동 (사람이 rollback 을 쳤다)")
        else:
            n = unblock(state, args.sha)
            out = f"차단 해제 {n}건"
    except Exception as e:  # noqa: BLE001 — 판정기 · 전진기가 유닛 결과를 바꾸면 안 된다
        log.exception("%s 예외", args.command)
        _alert(f"🚧 deploy {args.command} — 예외", f"{type(e).__name__}: {e}"[:1000], incident=True)
        out = f"예외 ({type(e).__name__})"
    save_state(state, STATE_PATH)
    log.info("deploy %s — %s", args.command, out)
    print(out)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
```

`run.py` 의 게이트 호출 바로 앞에 두 줄을 넣는다 (`write_behavior` 의 `try` 블록 뒤).

```python
    # 배포본 표지 (스펙 2026-09-03 §4.4): 판정기가 라이브의 build.json 으로 반영을 확인한다.
    write_build_marker("site", run_id=run_id)
```

import 는 `from bullet_in import dbt_gate` 아래에 `from bullet_in.deploy import write_build_marker` 를 더한다.

- [ ] **Step 4: 통과를 확인하고 전체 테스트를 돌린다**

Run: `uv run --project <워크트리> --extra dev pytest -q`
Expected: 전부 PASS (통합은 DB 없으면 skip).

- [ ] **Step 5: 워크트리에서 CLI 를 실제로 한 번 부른다**

```bash
cd <워크트리> && uv run --project <워크트리> python -m bullet_in.deploy preflight; echo "exit=$?"
# 로컬 .env 를 소싱하지 않았으면 「필수 키 없음: …」 이 찍히고 exit=1 — 그것이 정상 동작이다
```

- [ ] **Step 6: 커밋**

```bash
git -C <워크트리> add src/bullet_in/deploy.py src/bullet_in/run.py tests/test_deploy.py
git -C <워크트리> commit -m "feat(deploy): 명령 다섯 CLI 와 배포본 커밋 표지 build.json"
```

---

### Task 6: 유닛 · PR 템플릿 · 문서

**Files:**
- Modify: `infra/systemd/bullet-in.service`
- Modify: `.github/PULL_REQUEST_TEMPLATE.md` (§6)
- Modify: `.github/workflows/ci.yml` (「이 CI 가 안 보는 것」)
- Modify: `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` (§2)
- Modify: `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` (§3 첫 불릿)
- Modify: `CLAUDE.md` (첫 문단)
- Create: `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md`

**Interfaces:**
- Consumes: `python -m bullet_in.deploy advance|judge|rollback|unblock` (Task 5).

- [ ] **Step 1: 유닛에 두 줄을 넣는다**

`infra/systemd/bullet-in.service` 의 `[Service]` 를 이렇게 만든다.

```ini
[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStartPre=/usr/bin/docker compose up -d --wait
ExecStartPre=/bin/sleep 10
# 머지된 코드를 회차 시작에 내려받는다 (스펙 2026-09-03). 앞의 - 는 「실패해도 회차를 계속」 —
# 전진 실패로 회차를 잃지 않는 것이 첫 원칙이다.
ExecStartPre=-/home/ubuntu/.local/bin/uv run python -m bullet_in.deploy advance
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.run --concurrency 8
ExecStartPost=/home/ubuntu/bullet-in/infra/deploy-site.sh
# 회차 끝 판정 — ExecStart 가 실패해도 돌고 $SERVICE_RESULT · $EXIT_STATUS 를 받는다.
# 전진 직후 회차면 성공은 라이브 표지 대조 · 실패는 직전 커밋으로 롤백 (종료 코드 3 은 보류).
ExecStopPost=/home/ubuntu/.local/bin/uv run python -m bullet_in.deploy judge
TimeoutStartSec=1800
# dbt 게이트가 세그폴트로 죽는 일이 VM 에서 두 번 났다 (2026-08-31 · 2026-09-03 · 종료코드 -11).
# 소프트 한도가 0 이면 코어가 안 남는다. systemd-coredump 가 받아 coredumpctl 로 본다.
LimitCORE=infinity
```

`install-units.sh` 는 이미 이 파일을 복사하므로 손대지 않는다.

- [ ] **Step 2: PR 템플릿 §6 에 한 줄을 더한다**

```
- [ ] 설정 키 — 새 환경변수가 있으면 REQUIRED_ENV 에 올리고 머지 전에 VM .env 에 넣음 (없으면 「해당 없음」)
```

`PR 크기` 줄 위에 둔다.
`.claude/tools/check-pr-format.py` 는 체크리스트 줄을 건너뛰므로 검사가 안 바뀐다.

- [ ] **Step 3: ci.yml 요약의 배포 줄을 바꾼다**

```
          - **배포와 운영 회차** — 코드는 다음 회차가 스스로 내려받고 첫 회차를 판정한다 (`bullet_in.deploy`) · 화면이 맞는지는 사람의 몫
```

- [ ] **Step 4: 손 배포 런북 §2 를 고친다**

`docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` 의 「## 2. 코드 반영」 절 본문을 이렇게 바꾼다.

````markdown
## 2. 코드 반영 — 손으로 하지 않는다 (2026-09-04 부터)

머지된 코드는 다음 회차가 시작할 때 스스로 내려받는다 (`bullet-in.service` 의 `ExecStartPre` · `bullet_in.deploy advance`).
회차 끝에 첫 회차를 판정하고 디스코드 리뷰 채널에 「✅ 코드 반영 완료」 가 온다.
그 알림이 오면 이 문서의 §3 이하를 할 필요가 없다.

급하면 회차를 손으로 한 번 시작한다.

```bash
ssh -i ~/.ssh/<키> <운영> 'sudo systemctl start --no-block bullet-in.service'
```

**`git pull` 을 손으로 치지 않는다.**
쳐도 되지만 상태 파일 (`state/deploy.json`) 이 「전진」 을 못 보고 지나가 첫 회차 판정과 롤백이 안 붙는다.

아래 §3 에서 §6 은 회차를 기다리지 않고 재렌더 · 배포만 앞당길 때 쓴다.
그때도 코드 반영은 위 명령으로 회차를 시작하는 편이 안전하다.
````

- [ ] **Step 5: 게이트 런북 §3 의 첫 불릿을 정정한다**

`docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` 의 「**`dbt` 실행 파일이 없다** — 배포할 때 `uv sync` 를 안 돌렸다.」 두 줄을 이렇게 바꾼다.

````markdown
- **`dbt` 실행 파일이 없다** — `uv run` 은 실행 전에 잠금 파일과 가상환경을 자동으로 맞추므로 정상이라면 있을 수 없다.
  있다면 그 회차의 `uv run` 이 동기화에서 실패한 것이다 (네트워크 · 빌드).
  저널의 `ExecStart` 첫 줄을 본다.
````

- [ ] **Step 6: CLAUDE.md 첫 문단에 한 줄을 더한다**

「스케줄은 VM 의 systemd 타이머다」 문장 뒤에 넣는다.

```
머지된 코드는 회차 유닛이 시작에서 내려받고 끝에서 판정한다 (`bullet_in.deploy` · 스펙 `docs/superpowers/specs/2026-09-03-deploy-automation-design.md`) — 세션이 VM 에서 `git pull` 을 하지 않는다.
```

- [ ] **Step 7: 새 런북을 쓴다**

`docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md`.
서식 §2.2 (한 줄 한 문장 · 기호 띄어쓰기) 를 지킨다.

````markdown
# 런북 — 회차가 코드를 스스로 반영할 때 오는 알림 여섯과 각각 할 일

머지된 코드는 사람이 내려받지 않는다.
`bullet-in.service` 가 시작에서 `bullet_in.deploy advance` 로 `origin/main` 을 내려받고, 끝에서 `bullet_in.deploy judge` 로 첫 회차를 판정한다.
설계는 `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` 에 있다.

상태는 VM 의 `~/bullet-in/state/deploy.json` 한 파일이다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cat ~/bullet-in/state/deploy.json'
```

`pending` 이 참이면 「전진했는데 아직 판정 안 함」 이고, `blocked` 는 판정에 실패한 커밋이다.

## 1. 알림 여섯

| 알림 | 채널 | 뜻 | 할 일 |
| --- | --- | --- | --- |
| ✅ 코드 반영 완료 | 리뷰 | 첫 회차 통과 · 라이브 표지 일치 | 없음 |
| ⏸ 코드 반영 판정 보류 | 리뷰 | 게이트가 신호로 죽었다 (안건 2ν) · 다음 회차에 다시 판정 | `coredumpctl info -1` (게이트 런북 §3.2) |
| ⏪ 코드 롤백 | 사고 | 첫 회차 실패 · 직전 커밋으로 되돌림 | §2 |
| 🚧 코드 전진 거부 — 사전 점검 실패 | 사고 | 새 코드가 import 안 되거나 필수 키가 없다 | §3 |
| 🚧 코드 전진 — VM 트리가 갈라졌다 | 사고 | 누가 VM 에서 직접 커밋했다 | §4 |
| 🚧 배포는 나갔는데 라이브 표지가 다르다 | 사고 | Cloudflare 캐시 · 배포 지연 | §5 |

## 2. 롤백 알림을 받았을 때

되돌린 것은 VM 의 코드뿐이다.
화면은 배포가 안 나갔으므로 직전 그대로이고, DB 에 그 회차가 쓴 행은 남는다.

먼저 저널로 어디까지 갔는지 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service -n 200 --no-pager | grep -E "ERROR|게이트|deploy"'
```

- **코드 탓이면** — 고친 PR 을 머지한다.
  새 커밋이 오면 다음 회차가 알아서 전진한다.
- **코드 탓이 아니면 (DB 다운 · 데이터 부채)** — 원인을 고친 뒤 같은 커밋을 다시 보게 한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy unblock <커밋 앞 7자리>'
```

## 3. 사전 점검 거부를 받았을 때

알림의 「사유」 에 빠진 키 이름이나 import 오류 한 줄이 있다.

- **키가 없다** — VM `.env` 에 넣는다.
  다음 회차가 다시 전진한다 (차단 목록에 올라 있으므로 `unblock` 이 먼저다).
- **import 오류** — 코드다.
  고친 PR 을 머지한다.

## 4. VM 트리가 갈라졌을 때

자동으로 되돌리지 않는다.
사람이 VM 에서 `git status` · `git log --oneline -3` 을 보고, 그 커밋이 필요 없으면 `git reset --hard origin/main` 을 친다.

## 5. 라이브 표지가 다를 때

코드는 되돌리지 않았다.
몇 분 뒤 직접 받아 본다.

```bash
curl -sL https://bullet-in.pages.dev/build.json
```

`commit` 이 `state/deploy.json` 의 `current` 와 같으면 캐시였다.
계속 다르면 `wrangler pages deployment list --project-name bullet-in` 으로 배포가 실제로 나갔는지 본다.

## 6. 화면이 틀린데 판정은 통과했을 때 (사람 눈에만 보이는 실패)

자동 판정은 조판 · 수치 오류를 못 본다.
사람이 되돌린다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy rollback'
```

자동 롤백과 같은 함수라 알림 · 차단 목록이 같은 모양으로 남는다.
화면은 다음 회차가 직전 코드로 덮는다.
급하면 Cloudflare 대시보드의 Deployments 에서 직전 배포로 Rollback 한다.

## 함께 볼 것

- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` — 게이트가 막았을 때
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` — 회차를 안 기다리고 재렌더 · 배포만 앞당길 때
````

- [ ] **Step 8: 문서 서식 검사와 전체 테스트**

```bash
cd <워크트리>
for f in docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md \
         docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md \
         docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md; do
  printf '{"tool_input":{"file_path":"%s"}}' "$PWD/$f" | python3 .claude/hooks/check-doc-format.py || echo "FAIL $f"
done
uv run --project <워크트리> --extra dev pytest -q
```

Expected: 서식 위반 0 · 테스트 전부 PASS.
낡은 런북을 한 줄 건드리면 그 파일의 서식 부채를 떠안으므로, 걸리면 그 파일의 위반을 함께 고친다.

- [ ] **Step 9: 커밋 · push · PR**

```bash
git -C <워크트리> add infra/systemd/bullet-in.service .github/PULL_REQUEST_TEMPLATE.md \
  .github/workflows/ci.yml CLAUDE.md docs/runbook/
git -C <워크트리> commit -m "feat(infra): 회차 유닛이 코드를 내려받고 판정하도록 · 런북과 템플릿"
git -C <워크트리> push -u origin <브랜치>
```

PR 본문은 7섹션 · `--body-file` · `check-pr-format.py --body` 통과 · humanize fast 1회.
§5 「장애 시나리오 & 롤백 전략」 에 이렇게 적는다.
「`ExecStartPre=-` 의 `-` 가 빠지면 전진 실패가 회차를 죽인다 · `ExecStopPost` 가 예외로 죽어도 0 으로 끝나게 되어 있다 · 되돌리려면 유닛 파일을 직전 것으로 `install-units.sh` 하고 `state/deploy.json` 을 지운다」.

---

### Task 7: 마지막 손배포와 라이브 리허설 (머지 뒤 · PR 밖)

**Files:** 없음 (VM 절차).

**Interfaces:**
- Consumes: 머지된 코드 · 갱신된 유닛.

- [ ] **Step 1: 회차가 안 도는지 확인하고 코드를 내려받는다 (마지막 손 pull)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'systemctl show bullet-in.service -p ActiveState --value; systemctl list-timers bullet-in.timer --no-pager | sed -n 2p'
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && git pull --ff-only && git log --oneline -1'
```

머지 커밋 해시를 눈으로 대조한다.

- [ ] **Step 2: 유닛을 설치한다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in/infra/systemd && ./install-units.sh && systemctl cat bullet-in.service | grep -E "ExecStartPre|ExecStopPost"'
```

Expected: `advance` 줄과 `judge` 줄에 `-` 가 있고 `TimeoutStopSec=300` 이 있다.
`systemctl show bullet-in.service -p TimeoutStopUSec -p TimeoutStartUSec` 로 5min · 30min 을 실측한다.
`sudo` 가 분류기에 막히면 사용자에게 명령을 드린다.

- [ ] **Step 3: 사전 점검이 VM 에서 통과하는지 본다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy preflight; echo "exit=$?"'
```

Expected: 출력 없음 · `exit=0`.
키가 빠졌다고 나오면 `.env` 를 채운 뒤 다시 (여기서 걸리면 첫 자동 전진이 거부된다).

- [ ] **Step 4: 상태 파일을 손으로 씨앗 넣는다 — `previous` 도 머지 커밋이다**

첫 회차는 「전진」 이 아니라 손 pull 로 왔으므로 상태 파일이 없다.
`previous` 를 `HEAD~1` 로 두면 안 된다.
그 커밋에는 `bullet_in.deploy` 가 없어서 `rollback` 한 순간 `unblock` · `advance` · `judge` 가 전부 「모듈 없음」 으로 죽는다 (`docs/troubleshooting/2026-09-04-a-rollback-that-deletes-the-rollback-tool.md`).

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && M=$(git rev-parse HEAD) &&
   mkdir -p state && printf "{\"current\": \"%s\", \"previous\": \"%s\", \"pending\": false, \"blocked\": [], \"advanced_at\": \"\"}\n" "$M" "$M" > state/deploy.json && cat state/deploy.json'
```

- [ ] **Step 5: 후속 문서 PR 을 하나 머지하고 첫 자동 전진을 본다**

리허설의 롤백은 도구를 가진 커밋으로 되돌아가야 하므로, 먼저 머지 커밋 위에 후속 커밋 `M2` 가 하나 올라가야 한다.
이 계획서의 Step 4에서 6 을 고친 문서 PR 이 그 커밋이다.
머지한 뒤 다음 정기 회차를 기다리거나 (20분 안쪽이면 기다린다) 회차를 손으로 시작한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'sudo systemctl start --no-block bullet-in.service'
```

정기 회차와 겹치지 않는 시각에 한다 (`list-timers` 로 다음 회차까지 40분 이상 남았을 때).
회차가 끝나면 Step 7 의 확인을 한다.
Expected: 저널에 「전진 M → M2 · 회차 끝에 판정」 과 「반영 완료」 · 리뷰 채널에 「✅ 코드 반영 완료」 (본문에 `run …`) · `state/deploy.json` 이 `previous: M · current: M2 · pending: false`.

- [ ] **Step 6: 수동 롤백 리허설 · 차단 해제 · 회차 손 시작**

이제 `previous` 가 `M` 이고 `M` 에는 도구가 있다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy rollback && git log --oneline -1 && cat state/deploy.json'
```

Expected: HEAD 가 `M` · `blocked` 에 `M2` · 사고 채널에 「⏪ 코드 롤백」 · 알림 본문에 「코드 탓이 아닐 수 있다」 와 `unblock` 명령.
디스코드에서 서식이 뭉개지지 않았는지 눈으로 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy unblock $(git rev-parse origin/main | cut -c1-7) && cat state/deploy.json'
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'sudo systemctl start --no-block bullet-in.service'
```

Expected: `blocked: []` · 회차가 다시 `M` 에서 `M2` 로 전진하고 Step 7 의 확인이 한 번 더 통과한다.

- [ ] **Step 7: 회차가 끝날 때까지 기다리고 판정을 본다**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'until [ "$(systemctl show bullet-in.service -p ActiveState --value)" != "activating" ]; do sleep 30; done;
   systemctl show bullet-in.service -p Result -p ExecMainStatus;
   journalctl -u bullet-in.service -n 400 --no-pager | grep -E "deploy (advance|judge)";
   cat ~/bullet-in/state/deploy.json; git -C ~/bullet-in log --oneline -1'
curl -sL https://bullet-in.pages.dev/build.json
```

Expected: 저널에 「deploy advance — 전진 P → N · 회차 끝에 판정」 과 「deploy judge — 반영 완료」 · 리뷰 채널에 「✅ 코드 반영 완료」 · `pending: false` · `build.json` 의 `commit` 이 머지 커밋.

- [ ] **Step 8: 다음 정기 회차 하나를 더 본다**

전진할 것이 없는 회차에서 `advance` 가 「변경 없음」 을, `judge` 가 「판정 대기 없음」 을 찍고 알림이 안 나는지 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service --since "4 hours ago" --no-pager | grep -E "deploy (advance|judge)"'
```

- [ ] **Step 9: 기록**

세션 메모리 `deploy-through-without-asking` 을 「머지 뒤 세션 몫은 반영 완료 알림 확인」 으로 고치고, 안건 표 2β 행을 ✅ 로 닫는다.
라이브로 못 잰 경로 셋 (종료 코드 3 보류 · 사전 점검 거부 · 표지 불일치) 은 단위 테스트뿐임을 함께 적는다.

---

## 계획 자체 점검 (작성자가 했다)

- **스펙 대조** — §4.1 명령 넷 (Task 5) · §4.2 상태 파일 (Task 2) · §4.3 유닛 (Task 6) · §4.4 표지 (Task 5) · §5 전진 일곱 단계 (Task 3) · §6 판정 표와 §6.1 재시도 (Task 4) · §6.2 판정기 고장 (Task 5 `main`) · §7 롤백 · 수동 둘 (Task 4 · 5) · §8 종료 코드 (Task 1) · §9 필수 키 · 템플릿 (Task 2 · 6) · §10 알림 여섯 (Task 3 · 4) · §11 단위 · 리허설 (Task 1에서 5 · 7) · §12 문서 다섯 (Task 6 · 7).
- **이름 일치** — `Repo.head` · `remote_main` · `ff_merge` · `reset_hard` · `status_short` · `advance(repo, state, *, run_preflight)` · `judge(repo, state, *, service_result, exit_status, matches)` · `build_matches(sha, *, fetch, tries, wait)` · `GATE_CRASH_EXIT` 를 태스크마다 같은 꼴로 썼다.
- **스펙과 다른 점 하나** — 알림 빌더를 `notify.py` 에 두지 않고 `deploy.py` 의 `_alert` 로 모았다.
  `notify.py` 를 안 건드리는 편이 수술적이고, 알림 여섯의 본문이 전부 배포 모듈의 상태를 읽기 때문이다.
