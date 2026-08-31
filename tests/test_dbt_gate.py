import json
from pathlib import Path

import pytest

from bullet_in.dbt_gate import GateResult, TestOutcome, dbt_env, enforce_gate, parse_results, run_gate


def _write(tmp_path: Path, results: list[dict]) -> Path:
    p = tmp_path / "run_results.json"
    p.write_text(json.dumps({"metadata": {}, "results": results,
                             "elapsed_time": 0.5, "args": {}}))
    return p


def test_parse_results_separates_blocked_from_warned(tmp_path):
    path = _write(tmp_path, [
        {"unique_id": "test.bullet_in.unique_stg_articles_url.abc",
         "status": "fail", "failures": 3, "message": ""},
        {"unique_id": "test.bullet_in.relationships_stg_article_players_x.def",
         "status": "warn", "failures": 7, "message": ""},
        {"unique_id": "test.bullet_in.not_null_stg_articles_url.ghi",
         "status": "pass", "failures": 0, "message": ""},
        {"unique_id": "model.bullet_in.stg_articles",
         "status": "success", "failures": None, "message": ""},
    ])
    r = parse_results(path)
    assert [t.name for t in r.blocked] == ["unique_stg_articles_url"]
    assert r.blocked[0].failures == 3
    assert [t.name for t in r.warned] == ["relationships_stg_article_players_x"]
    assert r.warned[0].failures == 7
    assert r.ran is True
    assert r.error is None


def test_parse_results_counts_model_errors_as_blocking(tmp_path):
    # 모델이 못 돌면 테스트는 건너뛰어 조용히 통과한 것처럼 보인다.
    path = _write(tmp_path, [
        {"unique_id": "model.bullet_in.stg_article_players",
         "status": "error", "failures": None, "message": "Binder Error"},
    ])
    r = parse_results(path)
    assert [t.name for t in r.blocked] == ["stg_article_players"]


def test_parse_results_reports_missing_file(tmp_path):
    r = parse_results(tmp_path / "없는파일.json")
    assert r.ran is False
    assert r.blocked == []
    assert "run_results.json" in (r.error or "")


def test_parse_results_reports_corrupted_file(tmp_path):
    # dbt 가 쓰던 도중 죽으면 파일은 있는데 JSON 이 안 닫혀 있다.
    p = tmp_path / "run_results.json"
    p.write_text("{ this is not json")
    r = parse_results(p)
    assert r.ran is False
    assert r.blocked == []
    assert "run_results.json" in (r.error or "")


def test_dbt_env_splits_url_into_five_variables():
    env = dbt_env("mysql+pymysql://root:secret@10.0.0.5:3307/bulletin")
    assert env == {
        "DBT_MARIA_HOST": "10.0.0.5",
        "DBT_MARIA_PORT": "3307",
        "DBT_MARIA_USER": "root",
        "DBT_MARIA_PASSWORD": "secret",
        "DBT_MARIA_DB": "bulletin",
    }


def test_dbt_env_fills_defaults_when_url_omits_them():
    env = dbt_env("mysql+pymysql://root@localhost/bulletin")
    assert env["DBT_MARIA_PORT"] == "3306"
    assert env["DBT_MARIA_PASSWORD"] == ""


def test_dbt_env_unquotes_percent_encoded_password():
    # 운영 비밀번호에 @ 나 / 가 들어가면 URL 에 퍼센트 인코딩으로 실린다.
    env = dbt_env("mysql+pymysql://root:p%40ss%2Fword@localhost:3306/bulletin")
    assert env["DBT_MARIA_PASSWORD"] == "p@ss/word"


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_run_gate_does_not_report_pass_from_a_stale_results_file(tmp_path, monkeypatch):
    # 2026-08-31 실측 재현: dbt 가 죽은 포트를 겨눠 종료 코드 2 로 죽었는데 (아무것도
    # 새로 안 씀), target/ 에 지난 회차의 "전부 통과" 파일이 남아 있던 상황을 그대로 흉내낸다.
    # 지우지 않으면 이 파일을 그대로 읽어 통과로 보고한다 — 이 테스트는 그 결함을 잡는다.
    target = tmp_path / "target"
    target.mkdir()
    _write(target, [
        {"unique_id": "test.bullet_in.unique_stg_articles_url.abc",
         "status": "pass", "failures": 0, "message": ""},
    ])

    def fake_run(*args, **kwargs):
        return _FakeProc(2)  # 아무것도 새로 안 쓴다

    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:1/bulletin")
    assert r.ran is False


def test_run_gate_happy_path_still_passes(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        target = tmp_path / "target"
        target.mkdir(exist_ok=True)
        _write(target, [
            {"unique_id": "test.bullet_in.unique_stg_articles_url.abc",
             "status": "pass", "failures": 0, "message": ""},
        ])
        return _FakeProc(0)

    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")
    assert r.ran is True
    assert r.blocked == []


def test_enforce_gate_passes_when_nothing_broke(caplog):
    enforce_gate(GateResult(), run_id="r1")   # 예외가 안 나야 한다


def test_enforce_gate_logs_warnings_without_blocking(caplog, monkeypatch):
    import logging
    sent = {}
    monkeypatch.setattr("bullet_in.notify.send_alert",
                        lambda **kw: sent.update(kw))
    result = GateResult(warned=[TestOutcome("relationships_orphans", 259)])
    with caplog.at_level(logging.WARNING):
        enforce_gate(result, run_id="r1")
    assert "relationships_orphans" in caplog.text
    assert "259" in caplog.text
    assert sent == {}   # 경고는 알림 피로 방지를 위해 발송하지 않는다


def test_enforce_gate_raises_and_alerts_when_blocked(monkeypatch):
    sent = {}
    monkeypatch.setattr("bullet_in.notify.send_alert",
                        lambda **kw: sent.update(kw))
    result = GateResult(blocked=[TestOutcome("unique_stg_articles_url", 3)])
    with pytest.raises(SystemExit) as e:
        enforce_gate(result, run_id="r1")
    assert e.value.code == 1
    assert "unique_stg_articles_url" in str(sent)


def test_enforce_gate_blocks_when_dbt_could_not_run(monkeypatch):
    sent = {}
    monkeypatch.setattr("bullet_in.notify.send_alert",
                        lambda **kw: sent.update(kw))
    result = GateResult(ran=False, error="dbt 실행 파일이 없다")
    with pytest.raises(SystemExit) as e:
        enforce_gate(result, run_id="r1")
    assert e.value.code == 1
    assert "dbt 실행 파일이 없다" in str(sent)


def test_run_gate_keeps_stdout_when_stderr_only_has_a_warning(tmp_path, monkeypatch):
    # 2026-08-31 21:05 실측 재현: dbt 가 노드 23/29 에서 죽어 run_results.json 을 못 남겼고,
    # stderr 에는 무해한 종료 경고 한 줄만 있고 진짜 원인은 stdout 에 있었다.
    # 종전 구현은 `stderr or stdout` 이라 그 경고 한 줄이 stdout 을 통째로 밀어냈고,
    # 저널에 남은 것이 경고뿐이라 원인을 좇을 수 없었다.
    def fake_run(*args, **kwargs):
        return _FakeProc(
            -11,
            stdout="Running with dbt=1.11.11\nRuntime Error in model gold_slo_rollup\n"
                   "  Connection to MariaDB was lost",
            stderr="UserWarning: resource_tracker: There appear to be 2 leaked semaphore objects",
        )

    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")

    assert r.ran is False
    assert "Runtime Error in model gold_slo_rollup" in r.error   # stdout 이 살아남는다
    assert "leaked semaphore" in r.error                          # stderr 도 함께 남는다
    assert "-11" in r.error                                       # 종료 코드가 남는다
    assert "logs/dbt.log" in r.error                              # 전체 로그의 자리를 알려준다


def test_run_gate_reports_exit_code_when_results_lack_blocking_rows(tmp_path, monkeypatch):
    # 결과 파일은 있는데 종료 코드가 실패인 경우도 같은 진단을 실어야 한다.
    def fake_run(*args, **kwargs):
        target = tmp_path / "target"
        target.mkdir(exist_ok=True)
        _write(target, [
            {"unique_id": "test.bullet_in.unique_stg_articles_url.abc",
             "status": "pass", "failures": 0, "message": ""},
        ])
        return _FakeProc(2, stdout="Database Error\n  could not attach maria", stderr="")

    monkeypatch.setattr("bullet_in.dbt_gate.subprocess.run", fake_run)
    r = run_gate(tmp_path, "mysql+pymysql://root@localhost:3306/bulletin")

    assert r.ran is False
    assert "could not attach maria" in r.error
    assert "2" in r.error
