import os, pytest
from sqlalchemy import create_engine, text

TEST_URL = os.environ.get("MARIADB_TEST_URL",
    "mysql+pymysql://root:bulletin@localhost:3306/bulletin_test")

@pytest.fixture(scope="session")
def engine():
    base = create_engine("mysql+pymysql://root:bulletin@localhost:3306/")
    try:
        with base.connect() as c:
            c.execute(text("CREATE DATABASE IF NOT EXISTS bulletin_test"))
            c.commit()
    except Exception:
        pytest.skip("MariaDB not available")
    eng = create_engine(TEST_URL)
    from pathlib import Path
    ddl = Path("src/bullet_in/storage/schema.sql").read_text()
    with eng.begin() as c:
        for stmt in [s for s in ddl.split(";") if s.strip()]:
            c.execute(text(stmt))
    yield eng

@pytest.fixture(autouse=True)
def clean(engine):
    with engine.begin() as c:
        c.execute(text("DELETE FROM articles"))
    yield
