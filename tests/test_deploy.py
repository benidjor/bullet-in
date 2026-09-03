"""배포 자동화 (스펙 2026-09-03) — 상태 · 판정 · 전진 · 롤백 · 표지."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from bullet_in.deploy import (
    DeployState,
    Repo,
    Verdict,
    advance,
    decide,
    load_state,
    preflight,
    save_state,
)


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
