from bullet_in.dbt_gate import dbt_env


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
