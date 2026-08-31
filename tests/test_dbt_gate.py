import json
from pathlib import Path

from bullet_in.dbt_gate import dbt_env, parse_results


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
