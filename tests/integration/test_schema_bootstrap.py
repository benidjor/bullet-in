import pytest
from sqlalchemy import create_engine, text
from bullet_in.storage.mariadb import MartStore

BASE = "mysql+pymysql://root:bulletin@localhost:3306/"
DB = "bulletin_bootstrap_test"

@pytest.fixture
def fresh_engine():
    base = create_engine(BASE)
    try:
        with base.begin() as c:
            c.execute(text(f"DROP DATABASE IF EXISTS {DB}"))
            c.execute(text(f"CREATE DATABASE {DB}"))
    except Exception:
        pytest.skip("MariaDB not available")
    eng = create_engine(BASE + DB)
    yield eng
    with base.begin() as c:
        c.execute(text(f"DROP DATABASE IF EXISTS {DB}"))

def test_ensure_schema_creates_tables_on_empty_db(fresh_engine):
    MartStore(fresh_engine).ensure_schema()
    # 테이블이 없으면 count() 가 에러 → 생성됐다면 0 을 돌려준다
    assert MartStore(fresh_engine).count() == 0

def test_ensure_schema_is_idempotent(fresh_engine):
    store = MartStore(fresh_engine)
    store.ensure_schema()
    store.ensure_schema()  # 두 번째 호출도 예외 없이 통과해야 한다
    assert store.count() == 0
