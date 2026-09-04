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
    airflow_inputs,
    build_matches,
    cli_json,
    compare_url,
    decide,
    fetch_build,
    judge,
    load_state,
    main,
    parse_task_states,
    preflight,
    read_local_build,
    rollback,
    run_preflight_subprocess,
    save_state,
    unblock,
    write_build_marker,
)


def test_state_roundtrip_and_defaults(tmp_path):
    p = tmp_path / "deploy.json"
    assert load_state(p) == DeployState()          # 파일이 없으면 기본값
    s = DeployState(current="n" * 40, previous="p" * 40, pending=True,
                    blocked=["b" * 40], advanced_at="2026-09-04T00:03:12+00:00")
    save_state(s, p)
    assert load_state(p) == s
    assert json.loads(p.read_text())["pending"] is True


def test_load_state_ignores_unknown_keys(tmp_path):
    p = tmp_path / "deploy.json"
    p.write_text(json.dumps({"current": "n" * 40, "previous": "p" * 40, "pending": True,
                             "blocked": ["b" * 40], "advanced_at": "2026-09-04T00:03:12+00:00",
                             "future_key": 1}))
    s = load_state(p)
    assert s.current == "n" * 40
    assert s.previous == "p" * 40
    assert s.pending is True
    assert s.blocked == ["b" * 40]
    assert s.advanced_at == "2026-09-04T00:03:12+00:00"


def test_decide_does_nothing_without_pending():
    assert decide(DeployState(pending=False), "exit-code", "1").action == "none"


@pytest.mark.parametrize("service_result,exit_status,action", [
    ("success", "0", "confirm"),
    ("exit-code", "3", "hold"),        # 게이트 급사 (dbt 세그폴트) — 되돌리지 않는다
    ("exit-code", "1", "rollback"),    # 예외 · 게이트 위반 · dbt 자체 실패
    ("timeout", "", "rollback"),
    ("signal", "9", "rollback"),
    ("", "", "none"),                  # SERVICE_RESULT 없음 — systemd 밖에서 부른 것 같다
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


def test_run_preflight_subprocess_prefers_stdout_over_uv_sync_noise(monkeypatch):
    class _Proc:
        def __init__(self, stdout, stderr):
            self.returncode = 1
            self.stdout = stdout
            self.stderr = stderr

    stderr = "Installed 20 packages\n" + "\n".join(f" + pkg{i}==1.0" for i in range(20))
    monkeypatch.setattr("bullet_in.deploy.subprocess.run",
                        lambda *a, **k: _Proc("필수 키 없음: GA4_DATASET\n", stderr))
    assert run_preflight_subprocess() == ["필수 키 없음: GA4_DATASET"]

    monkeypatch.setattr("bullet_in.deploy.subprocess.run",
                        lambda *a, **k: _Proc("", stderr))
    assert run_preflight_subprocess() == stderr.strip().splitlines()[-8:]


def _advanced(repos):
    """c1 에서 c2 로 전진해 pending 인 상태를 만든다."""
    upstream, vm = repos
    old = _git(vm, "rev-parse", "HEAD")
    new = _commit(upstream, "c2")
    state = DeployState()
    advance(Repo(vm), state, run_preflight=lambda: [])
    return vm, state, old, new


def test_advance_keeps_confirmed_previous_when_still_pending(repos, quiet_alerts):
    upstream, _ = repos
    vm, state, old, new = _advanced(repos)
    assert state.pending is True
    c3 = _commit(upstream, "c3")
    advance(Repo(vm), state, run_preflight=lambda: [])
    assert state.previous == old
    assert state.current == c3


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
    answers = iter([(None, "status 500 · 0 bytes"),
                    ({"commit": "other"}, "status 200 · 20 bytes"),
                    ({"commit": "n" * 40, "run_id": "r" * 40}, "status 200 · 60 bytes")])
    ok, detail = build_matches("n" * 40, fetch=lambda: next(answers), tries=3, wait=0)
    assert ok is True


def test_build_matches_fails_on_empty_and_mismatch():
    ok, detail = build_matches("n" * 40, fetch=lambda: (None, "status 200 · 0 bytes"),
                               tries=2, wait=0)
    assert ok is False
    assert "status 200 · 0 bytes" in detail
    ok, detail = build_matches("n" * 40, fetch=lambda: ({"commit": "o" * 40}, "status 200 · 40 bytes"),
                               tries=1, wait=0)
    assert ok is False
    assert "ooooooo" in detail


class _FakeResp:
    def __init__(self, status_code, content, json_data=None, json_error=False):
        self.status_code = status_code
        self.content = content
        self._json_data = json_data
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._json_data


def test_fetch_build_reports_status_and_bytes_on_every_failure(monkeypatch):
    monkeypatch.setattr("bullet_in.deploy.httpx.get",
                        lambda *a, **k: _FakeResp(500, b"error"))
    data, detail = fetch_build()
    assert data is None
    assert detail == "status 500 · 5 bytes"

    monkeypatch.setattr("bullet_in.deploy.httpx.get",
                        lambda *a, **k: _FakeResp(200, b""))
    data, detail = fetch_build()
    assert data is None
    assert detail == "status 200 · 0 bytes"

    monkeypatch.setattr("bullet_in.deploy.httpx.get",
                        lambda *a, **k: _FakeResp(200, b"[1]", json_data=[1]))
    data, detail = fetch_build()
    assert data is None
    assert "객체가 아님" in detail


def test_fetch_build_returns_dict_and_detail(monkeypatch):
    payload = {"commit": "n" * 40, "run_id": "r" * 40}
    content = json.dumps(payload).encode()
    monkeypatch.setattr("bullet_in.deploy.httpx.get",
                        lambda *a, **k: _FakeResp(200, content, json_data=payload))
    data, detail = fetch_build()
    assert data == payload
    assert detail == f"status 200 · {len(content)} bytes"


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


# ── 알림 상세 (2026-09-04 · 반영 완료 · 롤백에 커밋 제목 · 목록 · 규모 · 시간 · 회차) ──

def test_repo_subjects_and_shortstat(repos):
    vm, state, old, new = _advanced(repos)
    subjects = Repo(vm).subjects(old, new)
    assert subjects == [f"{new[:7]} c2"]
    assert "1 file changed" in Repo(vm).shortstat(old, new)
    assert Repo(vm).subjects(new, new) == []        # 같은 커밋이면 비어 있다


@pytest.mark.parametrize("remote,expected", [
    ("https://github.com/benidjor/bullet-in.git", "https://github.com/benidjor/bullet-in/compare/aaaaaaa...bbbbbbb"),
    ("https://github.com/benidjor/bullet-in", "https://github.com/benidjor/bullet-in/compare/aaaaaaa...bbbbbbb"),
    ("git@github.com:benidjor/bullet-in.git", "https://github.com/benidjor/bullet-in/compare/aaaaaaa...bbbbbbb"),
    ("/tmp/upstream", None),                       # 테스트의 로컬 원격 · 링크 없음
])
def test_compare_url_reads_github_remotes_only(remote, expected):
    assert compare_url(remote, "a" * 40, "b" * 40) == expected


def test_read_local_build_returns_none_when_missing(tmp_path):
    assert read_local_build(tmp_path / "site" / "build.json") is None
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "build.json").write_text('{"commit": "x", "run_id": "localrun-1"}')
    assert read_local_build(tmp_path / "site" / "build.json")["run_id"] == "localrun-1"


def test_judge_confirm_alert_carries_commit_detail(repos, quiet_alerts, monkeypatch):
    vm, state, old, new = _advanced(repos)
    (vm / "site").mkdir()
    (vm / "site" / "build.json").write_text(json.dumps({"commit": new, "run_id": "localrun-1"}))
    monkeypatch.chdir(vm)
    judge(Repo(vm), state, service_result="success", exit_status="0",
          matches=lambda sha: (True, f"{sha[:7]} · run liverun1"))
    alert = quiet_alerts[0]
    assert alert["title"].startswith("✅ 코드 반영 완료 — c2")          # 무엇이 나갔나가 제목에
    names = [f["name"] for f in alert["fields"]]
    assert names == ["반영된 커밋", "변경 규모", "시간", "회차"]
    values = {f["name"]: f["value"] for f in alert["fields"]}
    assert f"{new[:7]} c2" in values["반영된 커밋"]
    assert "1 file changed" in values["변경 규모"]
    assert "전진" in values["시간"] and "판정" in values["시간"]
    assert "run localrun" in values["회차"] and "liverun1" in values["회차"]   # 이 회차 · 라이브 표지
    assert alert.get("url") is None                                       # 로컬 원격은 링크 없음


def test_rollback_alert_carries_commit_detail(repos, quiet_alerts):
    vm, state, old, new = _advanced(repos)
    rollback(Repo(vm), state, reason="시험")
    alert = quiet_alerts[0]
    assert alert["title"].startswith("⏪ 코드 롤백 — c2")
    values = {f["name"]: f["value"] for f in alert["fields"]}
    assert f"{new[:7]} c2" in values["되돌린 커밋"]
    assert "1 file changed" in values["변경 규모"]
    assert "태스크 로그" in values                                          # 회차가 Airflow 로 옮겨 저널 대신 태스크 로그
    assert "dag_id=bullet_in_cycle" in values["태스크 로그"]
    assert "journalctl" not in values["태스크 로그"]


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


def test_parse_task_states_skips_leading_structlog_warning_lines():
    warning = (
        '2026-09-04T06:24:26.841666Z [warning  ] Could not import graphviz. '
        'Rendering graph to the graphical format will not be possible. \n'
    )
    cli = json.dumps([{"dag_id": "bullet_in_cycle", "run_id": "r", "task_id": "gate", "state": "success"}])
    assert parse_task_states(warning + cli) == {"gate": "success"}


def test_cli_json_raises_on_empty_input():
    with pytest.raises(ValueError):
        cli_json("")


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
