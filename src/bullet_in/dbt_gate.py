"""회차 끝에서 dbt 품질 검사를 돌리고 결과로 배포를 막는 게이트.

설계 = docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import unquote, urlparse

from bullet_in import notify

log = logging.getLogger(__name__)

# dbt 가 내는 테스트 상태 — fail 은 error_if 를 넘긴 것 · warn 은 warn_if 만 넘긴 것.
_BLOCKING = {"fail", "error"}

# 게이트가 못 돈 것 중 dbt 가 신호로 죽은 경우 (세그폴트 · 강제 종료) 의 종료 코드.
# 판정기 (deploy.judge) 가 $EXIT_STATUS 하나로 「급사」 와 나머지를 가른다 (스펙 §8).
GATE_CRASH_EXIT = 3


@dataclass(frozen=True)
class TestOutcome:
    name: str
    failures: int


@dataclass(frozen=True)
class GateResult:
    blocked: list[TestOutcome] = field(default_factory=list)
    warned: list[TestOutcome] = field(default_factory=list)
    ran: bool = True
    error: str | None = None
    dbt_returncode: int | None = None


@dataclass(frozen=True)
class GateTally:
    """수집 현황 화면의 SLO-3 · 4 재료 — unique · not_null 테스트가 몇 종이고 무엇이 안 통과했나."""
    generated_at: str                       # dbt 가 적은 ISO 시각 (UTC · 없으면 빈 문자열)
    unique_total: int
    unique_failed: list[TestOutcome]
    not_null_total: int
    not_null_failed: list[TestOutcome]


def _short(unique_id: str) -> str:
    """`test.bullet_in.unique_stg_articles_url.abc` 에서 사람이 읽을 이름만 뽑는다."""
    parts = unique_id.split(".")
    return parts[2] if len(parts) > 2 else unique_id


def parse_results(path: Path) -> GateResult:
    """`dbt build` 가 남긴 결과 파일을 차단 · 경고로 가른다.

    모델 실패도 차단으로 센다 — 모델이 못 돌면 그 아래 테스트가 건너뛰어져
    아무것도 안 깨진 것처럼 보인다.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return GateResult(ran=False, error=f"run_results.json 을 못 읽었다: {e}")
    blocked, warned = [], []
    for r in data.get("results", []):
        status = r.get("status")
        outcome = TestOutcome(_short(r.get("unique_id", "")), int(r.get("failures") or 0))
        if status in _BLOCKING:
            blocked.append(outcome)
        elif status == "warn":
            warned.append(outcome)
    return GateResult(blocked=blocked, warned=warned)


def gate_tally(path: Path) -> GateTally | None:
    """SLO-3 (중복 적재율) · SLO-4 (필수 필드 완전성) 용 집계.

    `parse_results` 는 차단 · 경고만 남기고 통과를 버린다 — 「unique 5종 전부 통과」 라고
    말하려면 통과한 것도 세야 해서 같은 파일을 따로 읽는다. 경고 (`warn`) 도 결측 행이
    있다는 뜻이라 실패로 센다. 파일이 없거나 못 읽으면 None 이고 화면은 「게이트 결과 없음」
    으로 그린다 (스펙 2026-09-05 §3.4).
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    total = {"unique": 0, "not_null": 0}
    failed: dict[str, list[TestOutcome]] = {"unique": [], "not_null": []}
    for r in data.get("results", []):
        name = _short(r.get("unique_id", ""))
        kind = next((k for k in total if name.startswith(k + "_")), None)
        if kind is None:
            continue
        total[kind] += 1
        if r.get("status") in _BLOCKING or r.get("status") == "warn":
            failed[kind].append(TestOutcome(name, int(r.get("failures") or 0)))
    return GateTally(generated_at=(data.get("metadata") or {}).get("generated_at", ""),
                     unique_total=total["unique"], unique_failed=failed["unique"],
                     not_null_total=total["not_null"], not_null_failed=failed["not_null"])


def dbt_env(mariadb_url: str) -> dict[str, str]:
    """`MARIADB_URL` 을 dbt profiles 가 읽는 다섯 변수로 푼다.

    접속 정보의 단일 출처를 `MARIADB_URL` 하나로 두려는 것이다 — profiles.yml 에
    값을 박아 두면 공개 저장소에 비밀번호가 실리고 운영과도 갈린다.
    """
    p = urlparse(mariadb_url)
    return {
        "DBT_MARIA_HOST": p.hostname or "localhost",
        "DBT_MARIA_PORT": str(p.port or 3306),
        "DBT_MARIA_USER": unquote(p.username or "root"),
        "DBT_MARIA_PASSWORD": unquote(p.password or ""),
        "DBT_MARIA_DB": (p.path or "").lstrip("/") or "bulletin",
    }


def _diagnosis(proc, project_dir: Path) -> str:
    """dbt 가 남긴 출력을 진단 한 줄로 압축한다.

    stdout 과 stderr 을 **둘 다** 싣는다 — dbt 는 오류를 stdout 에 쓰는데, 종전 구현은
    `stderr or stdout` 이라 stderr 에 무해한 경고 한 줄만 있어도 stdout 이 통째로 버려졌다.
    2026-08-31 21:05 회차가 그렇게 끊겼고, 저널에 남은 것이 세마포어 누수 경고뿐이라
    원인을 저널로 좇을 수 없었다.

    종료 코드도 함께 남긴다 — 신호로 죽은 것 (음수) 과 dbt 자체 실패 (1 · 2) 는
    다른 고장이고, 그 둘을 가르지 못하면 다음 사람이 같은 자리에서 다시 막힌다.
    """
    parts = [f"종료코드 {proc.returncode}"]
    for label, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        lines = (stream or "").strip().splitlines()[-6:]
        if lines:
            parts.append(f"{label}: {' / '.join(lines)}")
    parts.append(f"전체 로그는 {project_dir}/logs/dbt.log")
    return " · ".join(parts)


def run_gate(project_dir: Path, mariadb_url: str, *, crash_retries: int = 1) -> GateResult:
    """`dbt build` 를 돌리고 결과 파일을 읽어 판정한다.

    dbt 자체가 못 돌면 데이터 결함이 아니라 게이트 고장이다 — 그것도 차단으로 낸다.
    조용히 통과시키면 게이트가 있다는 착각만 남는다.

    신호로 죽은 것 (세그폴트 · 안건 2ν · 비결정적) 만 crash_retries 번 더 돌린다.
    위반 · 설정 오류는 다시 돌려도 같은 답이라 한 번에 끝낸다 (스펙 2026-09-04 §6.2).
    Airflow 의 태스크 재시도로는 이 구분을 못 한다 — 건너뜀은 재시도되지 않고
    retries 는 실패 전부에 붙는다.
    """
    results_path = Path(project_dir) / "target" / "run_results.json"
    env = {**os.environ, **dbt_env(mariadb_url), "DBT_PROFILES_DIR": "."}
    proc = None
    for attempt in range(1 + crash_retries):
        # 2026-08-31 실측: dbt 가 시작도 못 하면 run_results.json 을 새로 안 쓴다 —
        # 지난 회차의 "전부 통과" 파일이 남아 통과로 읽힌다. 시도마다 지운다.
        try:
            results_path.unlink(missing_ok=True)
        except OSError as e:
            return GateResult(ran=False, error=f"이전 결과 파일을 못 지웠다: {e}")
        try:
            proc = subprocess.run(["dbt", "build"], cwd=project_dir, env=env,
                                  capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as e:
            return GateResult(ran=False, error=f"dbt 를 못 돌렸다: {e}")
        if proc.returncode >= 0:
            break
        log.warning("dbt 가 신호로 죽었다 (종료코드 %d · 시도 %d/%d)",
                    proc.returncode, attempt + 1, 1 + crash_retries)
    result = parse_results(results_path)
    diag = _diagnosis(proc, Path(project_dir))
    if not result.ran:
        # 결과 파일이 없다 = dbt 가 판정을 안 남겼다는 뜻이지 "시작도 못 했다" 는 뜻이 아니다.
        # 2026-08-31 21:05 에는 노드 29개 중 22개를 통과시키고 중간에 끊겼다.
        # 어느 쪽인지는 종료 코드와 dbt.log 로만 갈린다 — 그래서 둘 다 가리킨다.
        return GateResult(ran=False, error=f"{result.error} · {diag}",
                          dbt_returncode=proc.returncode)
    if proc.returncode != 0 and not result.blocked:
        # 종료 코드는 실패인데 파싱된 결과에 차단 항목이 없다 — 그 결과 파일은
        # 이번 회차를 설명하지 못한다는 뜻이라 통과로 볼 수 없다.
        return GateResult(ran=False,
                          error=f"결과 파일엔 차단 항목이 없는데 dbt 가 실패로 끝났다 · {diag}",
                          dbt_returncode=proc.returncode)
    return replace(result, dbt_returncode=proc.returncode)


def enforce_gate(result: GateResult, *, run_id: str) -> None:
    """경고는 저널에 남기고, 차단 사유가 있으면 알린 뒤 회차를 실패로 끝낸다.

    회차가 0 아닌 코드로 끝나면 systemd 가 ExecStartPost (배포) 를 안 돌린다.
    """
    if result.warned:
        log.warning("dbt 게이트 경고 %d건 — %s", len(result.warned),
                    " · ".join(f"{t.name} {t.failures}행" for t in result.warned))
    if not result.blocked and result.ran:
        log.info("dbt 게이트 통과 — 차단 0 · 경고 %d", len(result.warned))
        return
    notify.send_alert(**notify.build_dbt_gate_alert(result, run_id=run_id))
    log.error("dbt 게이트가 배포를 세웠다 — %s",
              result.error or " · ".join(f"{t.name} {t.failures}행"
                                         for t in result.blocked))
    # 신호로 죽은 것 (음수) 만 3 — 코드 탓이 아닌 유일한 실패라 판정기가 되돌리지 않는다.
    crashed = not result.ran and (result.dbt_returncode or 0) < 0
    raise SystemExit(GATE_CRASH_EXIT if crashed else 1)
