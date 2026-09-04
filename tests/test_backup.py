"""백업 · 복구의 판정 부분 테스트 — 세대 선택 · 산출물 검사 · 복구 대조."""
import gzip
import json
import subprocess
from datetime import date, datetime, timezone

import pytest

from bullet_in import backup


# --- 세대 선택 -------------------------------------------------------------

def test_평일은_일_세대만():
    assert backup.generations_for(date(2026, 9, 2)) == ("daily",)


def test_일요일은_주_세대가_붙는다():
    assert backup.generations_for(date(2026, 9, 6)) == ("daily", "weekly")


def test_달의_1일은_월_세대가_붙는다():
    assert backup.generations_for(date(2026, 9, 1)) == ("daily", "monthly")


def test_1일이_일요일이면_세대_셋():
    # 2026-11-01 은 일요일이다.
    assert backup.generations_for(date(2026, 11, 1)) == ("daily", "weekly", "monthly")


def test_접두어는_세대와_시각을_잇는다():
    ts = datetime(2026, 9, 1, 5, 30, 0, tzinfo=timezone.utc)
    assert backup.backup_prefix("daily", ts) == "daily/2026-09-01T05-30-00Z"


# --- 산출물 검사 -----------------------------------------------------------

def _정상_덤프(tmp_path):
    sql = tmp_path / "mariadb.sql"
    sql.write_text("\n".join(f"CREATE TABLE `{t}` (id INT);"
                             for t in backup.EXPECTED_TABLES)
                   + "\n" + "-- 채우기 " + "x" * backup.MIN_MARIADB_BYTES)
    archive = tmp_path / "mongo.archive.gz"
    archive.write_bytes(b"y" * backup.MIN_MONGO_BYTES)
    return sql, archive


def test_정상_덤프는_문제가_없다(tmp_path):
    sql, archive = _정상_덤프(tmp_path)
    assert backup.dump_problems(sql, archive) == []


def test_표가_빠진_덤프를_잡는다(tmp_path):
    sql, archive = _정상_덤프(tmp_path)
    sql.write_text(sql.read_text().replace("CREATE TABLE `articles`", "-- 지움"))
    problems = backup.dump_problems(sql, archive)
    assert any("articles" in p for p in problems)


def test_너무_작은_마리아디비_덤프를_잡는다(tmp_path):
    sql, archive = _정상_덤프(tmp_path)
    sql.write_text("\n".join(f"CREATE TABLE `{t}` (id INT);"
                             for t in backup.EXPECTED_TABLES))
    problems = backup.dump_problems(sql, archive)
    assert any("MariaDB" in p for p in problems)


def test_너무_작은_몽고_아카이브를_잡는다(tmp_path):
    sql, archive = _정상_덤프(tmp_path)
    archive.write_bytes(b"y" * 10)
    problems = backup.dump_problems(sql, archive)
    assert any("MongoDB" in p for p in problems)


def test_빈_덤프는_문제_둘_이상을_낸다(tmp_path):
    sql = tmp_path / "mariadb.sql"
    sql.write_text("")
    archive = tmp_path / "mongo.archive.gz"
    archive.write_bytes(b"")
    # 조용히 통과하는 백업이 이 안건의 출발점이다 — 빈 산출물이 반드시 걸려야 한다.
    assert len(backup.dump_problems(sql, archive)) >= 2


# --- 복구 대조 -------------------------------------------------------------

def _매니페스트(**over):
    base = dict(taken_at="2026-09-01T05:30:00Z",
                row_counts={"articles": 969, "players": 538},
                mongo_docs=1634, mariadb_bytes=2287679, mongo_bytes=1734975,
                git_commit="13c827c")
    base.update(over)
    return backup.Manifest(**base)


def test_복구가_같으면_어긋남이_없다():
    m = _매니페스트()
    assert backup.restore_mismatches(m, {"articles": 969, "players": 538}, 1634) == []


def test_행이_모자라면_어긋남을_낸다():
    m = _매니페스트()
    problems = backup.restore_mismatches(m, {"articles": 900, "players": 538}, 1634)
    assert any("articles" in p and "969" in p and "900" in p for p in problems)


def test_표가_통째로_없으면_어긋남을_낸다():
    m = _매니페스트()
    problems = backup.restore_mismatches(m, {"articles": 969}, 1634)
    assert any("players" in p for p in problems)


def test_몽고_건수가_다르면_어긋남을_낸다():
    m = _매니페스트()
    problems = backup.restore_mismatches(m, {"articles": 969, "players": 538}, 1600)
    assert any("raw_items" in p for p in problems)


def test_행이_0인_표는_어긋남이_아니다():
    # `sources` 는 운영에서 실제로 0행이다 (2026-09-01 실측) — 0 을 실패로 보면
    # 정상 백업이 매번 실패한다.
    m = _매니페스트(row_counts={"sources": 0, "articles": 969})
    assert backup.restore_mismatches(m, {"sources": 0, "articles": 969}, 1634) == []


# --- 매니페스트 왕복 -------------------------------------------------------

def test_매니페스트는_json_왕복을_견딘다():
    m = _매니페스트()
    assert backup.Manifest.from_json(json.dumps(m.to_dict())) == m


# --- GCS 주소 --------------------------------------------------------------

def test_객체_이름의_슬래시는_주소에서_인코딩된다():
    url = backup.object_url("bi-backup", "daily/2026-09-01T05-30-00Z/mariadb.sql.gz")
    assert "daily%2F2026-09-01T05-30-00Z%2Fmariadb.sql.gz" in url


@pytest.mark.parametrize("gen", ["daily", "weekly", "monthly"])
def test_세대_셋은_모두_보관_규칙을_가진다(gen):
    # 규칙이 없는 세대가 생기면 그 세대는 영원히 안 지워져 무료 한도를 잠식한다.
    assert gen in backup.RETENTION_DAYS


# --- 매니페스트는 「지금 DB」 가 아니라 「이 파일」 을 설명해야 한다 -----------

def test_덤프에_담긴_행을_파일에서_센다(tmp_path):
    sql = tmp_path / "mariadb.sql"
    sql.write_text("CREATE TABLE `articles` (id INT);\n"
                   + "INSERT INTO `articles` VALUES (1);\n" * 3
                   + "INSERT INTO `players` VALUES (1);\n" * 2)
    counts = backup.dump_row_counts(sql)
    assert counts["articles"] == 3
    assert counts["players"] == 2
    # 표는 있는데 행이 없으면 0 이다 — 없는 표와 같은 값이지만 대조 기준은 파일이다.
    assert counts["sources"] == 0


def test_몽고_건수는_mongodump_출력에서_읽는다():
    # 2026-09-01 에 VM 에서 그대로 받아 적은 출력이다 — 이름이 백틱에 싸여 있고,
    # 처음 쓴 정규식은 그 백틱 때문에 아무것도 못 읽었다.
    stderr = ("2026-08-31T20:29:52.023+0000\twriting `bulletin.raw_items` to "
              "`archive on stdout`\n"
              "2026-08-31T20:29:52.226+0000\tdone dumping `bulletin.raw_items` "
              "(1634 documents)\n")
    assert backup.mongodump_document_count(stderr) == 1634


def test_백틱_없는_출력도_읽는다():
    assert backup.mongodump_document_count(
        "done dumping bulletin.raw_items (12 documents)\n") == 12


def test_몽고_건수가_안_찍히면_세운다():
    with pytest.raises(SystemExit):
        backup.mongodump_document_count("2026-09-01T05:30:00 오류로 아무것도 안 남겼다\n")


# --- Airflow 덤프 ----------------------------------------------------------

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
