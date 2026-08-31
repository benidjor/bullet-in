"""운영 DB 를 GCS 로 내보내고 되살린다.

절차 · 설계 = docs/runbook/2026-09-01-backup-and-restore.md

세 가지를 한 모듈에 둔다 — 백업 (`run`) · 목록 (`list`) · 복구 (`restore`).
복구가 백업과 같은 파일에 있는 것이 이 설계의 요점이다.
되살려 본 적 없는 백업은 백업이 아니라서, 만드는 쪽만 있는 코드를 두지 않는다.

새 패키지를 안 쓴다 — `google-auth` 로 토큰만 받고 업로드는 `httpx` 로 한다.
둘 다 이미 이 저장소의 의존이라 VM 에 gcloud SDK 를 얹지 않아도 된다.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx

log = logging.getLogger(__name__)

# 컨테이너 · DB 이름은 docker-compose.yml 이 정하는 값이라 여기 상수로 둔다.
# Mongo 의 DB 이름은 `bulletin` 이다 — 코드 관례를 따라 `bullet_in` 으로 물으면
# 오류가 아니라 빈 결과가 와서 조용히 빈 백업이 된다 (2026-09-01 실물).
MARIADB_CONTAINER = "bullet-in-mariadb-1"
MONGO_CONTAINER = "bullet-in-mongo-1"
MONGO_DB = "bulletin"
MONGO_COLLECTION = "raw_items"

# schema.sql 이 만드는 표 전부. 하나라도 덤프에 없으면 부분 백업이다.
EXPECTED_TABLES = ("sources", "articles", "pipeline_runs",
                   "source_freshness", "players", "article_players")

# 부피 하한선 — 2026-09-01 실측 (MariaDB 덤프 9.2 MB · Mongo 아카이브 1.65 MiB) 보다
# 넉넉히 낮게 잡았다. 증가 추세를 재는 장치가 아니라 빈 산출물을 막는 바닥이다
# (deploy-site.sh 가 `page_count < 50` 으로 오배포를 막는 것과 같은 철학).
MIN_MARIADB_BYTES = 1_048_576
MIN_MONGO_BYTES = 524_288

# 세대별 보관 일수 — 지우는 일은 GCS 수명주기 규칙이 한다.
# 그래서 VM 의 서비스 계정에 삭제 권한을 안 줘도 되고, VM 이 통째로 털려도
# 공격자가 과거 백업을 지울 수 없다.
RETENTION_DAYS = {"daily": 8, "weekly": 35, "monthly": 400}

_SCOPE = "https://www.googleapis.com/auth/devstorage.read_write"
_API = "https://storage.googleapis.com/storage/v1/b"
_UPLOAD_API = "https://storage.googleapis.com/upload/storage/v1/b"


# --- 판정 (부수효과 없음) ---------------------------------------------------

def generations_for(day: date) -> tuple[str, ...]:
    """이 날짜의 백업이 들어갈 세대 접두어.

    같은 바이트를 일요일과 매달 1일에 두세 번 올리는 낭비가 있다.
    1회분이 4 MB 라 그 낭비가 보관 규칙을 단순하게 만드는 값보다 싸다 —
    세대마다 접두어가 갈려 있으면 보관 기간을 GCS 규칙 셋으로 끝낼 수 있다.
    """
    gens = ["daily"]
    if day.isoweekday() == 7:
        gens.append("weekly")
    if day.day == 1:
        gens.append("monthly")
    return tuple(gens)


def backup_prefix(generation: str, ts: datetime) -> str:
    """`daily/2026-09-01T05-30-00Z` — 한 백업이 들어가는 자리."""
    return f"{generation}/{ts.strftime('%Y-%m-%dT%H-%M-%SZ')}"


def object_url(bucket: str, name: str) -> str:
    """객체 하나를 가리키는 JSON API 주소. 이름의 `/` 도 인코딩해야 한다."""
    return f"{_API}/{bucket}/o/{quote(name, safe='')}"


def dump_problems(sql_path: Path, archive_path: Path) -> list[str]:
    """덤프 둘이 쓸 만한지 보고 문제를 문장으로 돌려준다. 빈 목록이면 통과.

    올리기 전에 본다 — 조용히 빈 백업이 쌓이는 것이 이 안건의 출발점이다.
    """
    problems: list[str] = []
    sql_size = sql_path.stat().st_size if sql_path.exists() else 0
    archive_size = archive_path.stat().st_size if archive_path.exists() else 0

    if sql_size < MIN_MARIADB_BYTES:
        problems.append(f"MariaDB 덤프가 {sql_size:,} 바이트로 하한 "
                        f"{MIN_MARIADB_BYTES:,} 미만이다")
    if archive_size < MIN_MONGO_BYTES:
        problems.append(f"MongoDB 아카이브가 {archive_size:,} 바이트로 하한 "
                        f"{MIN_MONGO_BYTES:,} 미만이다")

    text = sql_path.read_text(errors="replace") if sql_size else ""
    missing = [t for t in EXPECTED_TABLES if f"CREATE TABLE `{t}`" not in text]
    if missing:
        problems.append(f"덤프에 없는 표 {len(missing)}종 — {' · '.join(missing)}")
    return problems


def restore_mismatches(manifest: Manifest, restored_rows: dict[str, int],
                       restored_docs: int) -> list[str]:
    """되살린 DB 를 백업 당시 매니페스트와 대조한다. 빈 목록이면 복구 성공.

    행이 0인 표를 실패로 보지 않는다 — `sources` 는 운영에서 실제로 0행이다.
    """
    problems: list[str] = []
    for table, expected in sorted(manifest.row_counts.items()):
        actual = restored_rows.get(table)
        if actual is None:
            problems.append(f"{table} 표가 되살아나지 않았다 (기대 {expected:,}행)")
        elif actual != expected:
            problems.append(f"{table} 행 수가 다르다 — 기대 {expected:,} · 실제 {actual:,}")
    if restored_docs != manifest.mongo_docs:
        problems.append(f"raw_items 건수가 다르다 — 기대 {manifest.mongo_docs:,} · "
                        f"실제 {restored_docs:,}")
    return problems


@dataclass(frozen=True)
class Manifest:
    """백업 당시의 실측값. 복구를 검증할 때 대조하는 유일한 기준이다."""
    taken_at: str
    row_counts: dict[str, int]
    mongo_docs: int
    mariadb_bytes: int
    mongo_bytes: int
    git_commit: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        return cls(**json.loads(text))


# --- 환경 ------------------------------------------------------------------

def mariadb_credentials() -> tuple[str, str, str]:
    """`MARIADB_URL` 에서 사용자 · 비밀번호 · DB 이름을 뽑는다.

    접속 정보의 단일 출처를 `MARIADB_URL` 하나로 두려는 것이다 (dbt_gate 와 같은 이유).
    """
    p = urlparse(os.environ.get("MARIADB_URL", ""))
    return (p.username or "root", p.password or "bulletin",
            (p.path or "").lstrip("/") or "bulletin")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} 미설정 — .env 확인")
    return value


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


# --- 덤프 ------------------------------------------------------------------

def _docker(container: str, *args: str, stdout=None, stdin: bytes | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
    """컨테이너 안에서 한 명령을 돌리고, 실패하면 stderr 를 그대로 붙여 세운다.

    stderr 를 버리지 않는 것이 요점이다 — 진단을 삼킨 채 실패만 남기면 저널을
    봐도 왜 죽었는지 알 수 없다 (dbt 게이트에서 같은 실수를 이미 겪었다).
    """
    proc = subprocess.run(["docker", "exec", *(["-i"] if stdin else []), container, *args],
                          input=stdin, stdout=stdout, stderr=subprocess.PIPE,
                          timeout=1800)
    if check and proc.returncode != 0:
        raise SystemExit(f"docker exec {container} {args[0]} 실패 "
                         f"(코드 {proc.returncode}) — {proc.stderr.decode(errors='replace')[:500]}")
    return proc


def _mariadb_query(sql: str) -> str:
    user, password, db = mariadb_credentials()
    out = _docker(MARIADB_CONTAINER, "mariadb", f"-u{user}", f"-p{password}",
                  "-N", "-B", db, "-e", sql, stdout=subprocess.PIPE)
    return out.stdout.decode()


def dump_mariadb(dest: Path) -> None:
    """운영 DB 를 논리 덤프로 뽑는다.

    볼륨 스냅샷을 안 쓴다 — 볼륨 739 MB 안의 실제 데이터가 4 MB 이고 (2026-09-01 실측),
    논리 덤프라야 다른 호스트 · 다른 버전에 넣을 수 있다.
    `--single-transaction` 은 회차가 도는 중에도 표를 안 잠그기 위한 것이다.
    `--skip-extended-insert` 는 행마다 INSERT 를 한 줄씩 만든다 — 덤프에 든 행을
    셀 수 있게 하려는 것이고, 그래야 매니페스트가 「지금 DB」 가 아니라
    「이 파일」 을 설명한다.
    """
    user, password, db = mariadb_credentials()
    with dest.open("wb") as f:
        _docker(MARIADB_CONTAINER, "mariadb-dump", f"-u{user}", f"-p{password}",
                "--single-transaction", "--quick", "--skip-extended-insert",
                "--routines", "--events", db, stdout=f)


def dump_mongo(dest: Path) -> int:
    """수집 원본을 아카이브 하나로 뽑고, 담긴 건수를 돌려준다.

    건수를 따로 세지 않고 mongodump 가 stderr 에 찍는 값을 읽는다 — 따로 세면
    덤프와 셈 사이에 회차가 끼어 매니페스트가 아카이브를 설명하지 못하게 된다.
    """
    with dest.open("wb") as f:
        proc = _docker(MONGO_CONTAINER, "mongodump", f"--db={MONGO_DB}",
                       "--archive", "--gzip", stdout=f)
    return mongodump_document_count(proc.stderr.decode(errors="replace"))


def mongodump_document_count(stderr: str) -> int:
    """mongodump 이 찍는 마무리 줄에서 건수를 뽑는다.

    실물은 이름을 백틱으로 감싼다 — ``done dumping `bulletin.raw_items` (1634 documents)``
    (2026-09-01 VM 에서 직접 확인). 백틱 없는 판도 있어 둘 다 받는다.
    """
    m = re.search(rf"done dumping `?{MONGO_DB}\.{MONGO_COLLECTION}`? \((\d+) document",
                  stderr)
    if not m:
        raise SystemExit(f"mongodump 이 건수를 안 남겼다 — {stderr[-300:]}")
    return int(m.group(1))


def dump_row_counts(sql_path: Path) -> dict[str, int]:
    """덤프 파일에 실제로 담긴 표별 행 수.

    운영 DB 에 다시 묻지 않는다 — 덤프를 뜬 시각과 세는 시각 사이에 회차가 끼면
    매니페스트가 파일과 어긋나고, 그러면 복구 대조가 멀쩡한 백업을 실패로 찍는다.
    """
    text = sql_path.read_text(errors="replace")
    return {t: text.count(f"INSERT INTO `{t}` VALUES") for t in EXPECTED_TABLES}


# --- GCS -------------------------------------------------------------------

def _token() -> str:
    """서비스 계정으로 액세스 토큰을 받는다 (`GOOGLE_APPLICATION_CREDENTIALS`)."""
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=[_SCOPE])
    credentials.refresh(Request())
    return credentials.token


def upload(bucket: str, name: str, path: Path, token: str) -> None:
    url = f"{_UPLOAD_API}/{bucket}/o?uploadType=media&name={quote(name, safe='')}"
    with path.open("rb") as f:
        resp = httpx.post(url, content=f.read(), timeout=300,
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/octet-stream"})
    if resp.status_code >= 300:
        raise SystemExit(f"업로드 실패 {resp.status_code} — {name} · {resp.text[:200]}")
    log.info("올렸다 — gs://%s/%s (%s 바이트)", bucket, name, f"{path.stat().st_size:,}")


def download(bucket: str, name: str, dest: Path, token: str) -> None:
    resp = httpx.get(object_url(bucket, name), params={"alt": "media"}, timeout=300,
                     headers={"Authorization": f"Bearer {token}"},
                     follow_redirects=True)
    if resp.status_code >= 300:
        raise SystemExit(f"내려받기 실패 {resp.status_code} — {name}")
    dest.write_bytes(resp.content)


def list_prefixes(bucket: str, generation: str, token: str) -> list[str]:
    """한 세대에 쌓인 백업 접두어를 오래된 것부터 돌려준다."""
    resp = httpx.get(f"{_API}/{bucket}/o", timeout=60,
                     params={"prefix": f"{generation}/", "delimiter": "/"},
                     headers={"Authorization": f"Bearer {token}"})
    if resp.status_code >= 300:
        raise SystemExit(f"목록 조회 실패 {resp.status_code} — {resp.text[:200]}")
    return sorted(p.rstrip("/") for p in resp.json().get("prefixes", []))


# --- 명령 ------------------------------------------------------------------

def run_backup(workdir: Path) -> None:
    """덤프 → 검사 → 세대별 업로드. 어느 단계든 실패하면 0 아닌 코드로 끝난다.

    유닛이 실패로 끝나야 `OnFailure` 가 걸린 Discord 경보가 나간다.
    """
    bucket = _require_env("GCS_BACKUP_BUCKET")
    ts = datetime.now(timezone.utc)
    workdir.mkdir(parents=True, exist_ok=True)
    sql = workdir / "mariadb.sql"
    archive = workdir / "mongo.archive.gz"

    log.info("덤프 시작 — %s", ts.isoformat())
    dump_mariadb(sql)
    docs = dump_mongo(archive)

    problems = dump_problems(sql, archive)
    if problems:
        raise SystemExit("백업 산출물이 기준에 못 미친다 — " + " · ".join(problems))

    rows = dump_row_counts(sql)
    sql_gz = workdir / "mariadb.sql.gz"
    with sql.open("rb") as src, gzip.open(sql_gz, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)
    sql.unlink()

    manifest = Manifest(taken_at=ts.isoformat(), row_counts=rows, mongo_docs=docs,
                        mariadb_bytes=sql_gz.stat().st_size,
                        mongo_bytes=archive.stat().st_size,
                        git_commit=_git_commit())
    manifest_path = workdir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))

    token = _token()
    for generation in generations_for(ts.date()):
        prefix = backup_prefix(generation, ts)
        for path in (sql_gz, archive, manifest_path):
            upload(bucket, f"{prefix}/{path.name}", path, token)
    # 올린 뒤 남기지 않는다 — 운영 데이터 사본이 VM 의 /tmp 에 계속 누워 있을 이유가 없다.
    shutil.rmtree(workdir, ignore_errors=True)
    log.info("백업 완료 — 세대 %s · 기사 %s행 · 원본 %s건",
             " · ".join(generations_for(ts.date())), f"{rows['articles']:,}", f"{docs:,}")


def run_list(generation: str) -> None:
    bucket = _require_env("GCS_BACKUP_BUCKET")
    prefixes = list_prefixes(bucket, generation, _token())
    if not prefixes:
        print(f"{generation} 세대에 백업이 없다")
        return
    for p in prefixes:
        print(p)
    print(f"— {len(prefixes)}벌 · 보관 {RETENTION_DAYS[generation]}일")


def run_restore(prefix: str, target_db: str, workdir: Path) -> None:
    """백업 하나를 `target_db` 로 되살리고 매니페스트와 대조한다.

    운영 DB 이름을 기본값으로 두지 않는다 — 연습이 실수로 운영을 덮는 일을 막는다.
    되살릴 자리를 손으로 적어야 한다.
    """
    bucket = _require_env("GCS_BACKUP_BUCKET")
    user, password, _ = mariadb_credentials()
    token = _token()
    workdir.mkdir(parents=True, exist_ok=True)

    for name in ("manifest.json", "mariadb.sql.gz", "mongo.archive.gz"):
        download(bucket, f"{prefix}/{name}", workdir / name, token)
    manifest = Manifest.from_json((workdir / "manifest.json").read_text())
    log.info("되살릴 백업 — %s · 기사 %s행", manifest.taken_at,
             f"{manifest.row_counts.get('articles', 0):,}")

    sql = gzip.decompress((workdir / "mariadb.sql.gz").read_bytes())
    _mariadb_query(f"DROP DATABASE IF EXISTS `{target_db}`; "
                   f"CREATE DATABASE `{target_db}`")
    _docker(MARIADB_CONTAINER, "mariadb", f"-u{user}", f"-p{password}", target_db,
            stdin=sql)

    # 몽고는 아카이브 안의 이름공간을 바꿔 넣는다 — 운영 DB 를 안 건드리기 위해서다.
    _docker(MONGO_CONTAINER, "mongorestore", "--archive", "--gzip", "--drop",
            f"--nsFrom={MONGO_DB}.*", f"--nsTo={target_db}.*",
            stdin=(workdir / "mongo.archive.gz").read_bytes())

    restored_rows = {}
    for table in manifest.row_counts:
        # 표가 아예 안 되살아났으면 세는 명령이 실패한다 — 그것을 예외가 아니라
        # 「없다」 로 받아 대조 결과에 담는다.
        out = _docker(MARIADB_CONTAINER, "mariadb", f"-u{user}", f"-p{password}",
                      "-N", "-B", target_db, "-e", f"SELECT COUNT(*) FROM `{table}`",
                      stdout=subprocess.PIPE, check=False)
        if out.returncode == 0:
            restored_rows[table] = int(out.stdout.decode().strip() or 0)
    out = _docker(MONGO_CONTAINER, "mongosh", "--quiet", "--eval",
                  f'db.getSiblingDB("{target_db}").{MONGO_COLLECTION}.countDocuments({{}})',
                  stdout=subprocess.PIPE)
    restored_docs = int(out.stdout.decode().strip() or 0)

    mismatches = restore_mismatches(manifest, restored_rows, restored_docs)
    for table, expected in sorted(manifest.row_counts.items()):
        print(f"{table:20} 기대 {expected:>8,}  복구 {restored_rows.get(table, 0):>8,}")
    print(f"{'raw_items':20} 기대 {manifest.mongo_docs:>8,}  복구 {restored_docs:>8,}")
    if mismatches:
        raise SystemExit("복구 대조 실패 — " + " · ".join(mismatches))
    print(f"복구 대조 통과 — {prefix} → {target_db}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="운영 DB 백업 · 복구")
    sub = ap.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="덤프 · 검사 · GCS 업로드")
    p_run.add_argument("--workdir", type=Path, default=Path("/tmp/bullet-in-backup"))

    p_list = sub.add_parser("list", help="쌓인 백업 목록")
    p_list.add_argument("--generation", choices=sorted(RETENTION_DAYS), default="daily")

    p_restore = sub.add_parser("restore", help="백업 하나를 되살리고 대조")
    p_restore.add_argument("--prefix", required=True,
                           help="예: daily/2026-09-01T05-30-00Z")
    p_restore.add_argument("--target-db", required=True,
                           help="되살릴 DB 이름 — 연습은 bulletin_restore_check")
    p_restore.add_argument("--workdir", type=Path, default=Path("/tmp/bullet-in-restore"))

    args = ap.parse_args()
    if args.command == "run":
        run_backup(args.workdir)
    elif args.command == "list":
        run_list(args.generation)
    else:
        run_restore(args.prefix, args.target_db, args.workdir)
    sys.exit(0)
