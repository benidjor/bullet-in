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


def run_gate(project_dir: Path, mariadb_url: str) -> GateResult:
    """`dbt build` 를 돌리고 결과 파일을 읽어 판정한다.

    dbt 자체가 못 돌면 데이터 결함이 아니라 게이트 고장이다 — 그것도 차단으로 낸다.
    조용히 통과시키면 게이트가 있다는 착각만 남는다.
    """
    results_path = Path(project_dir) / "target" / "run_results.json"
    # 2026-08-31 실측: profile 파싱 오류 · MariaDB 접속 실패 · extension 로드 실패처럼
    # dbt 가 무엇 하나 돌기도 전에 죽으면 run_results.json 을 새로 안 쓴다.
    # 지우지 않고 두면 운영 VM 에서는 지난 회차의 "전부 통과" 파일이 그대로 남아 있어서,
    # 두 번째 회차부터는 게이트가 매번 그 옛 파일을 읽고 통과로 보고한다 —
    # 죽은 포트로 dbt 를 겨눴을 때 종료 코드 2 가 나면서도 남은 파일 때문에 통과가 났다.
    try:
        results_path.unlink(missing_ok=True)
    except OSError as e:
        return GateResult(ran=False, error=f"이전 결과 파일을 못 지웠다: {e}")
    env = {**os.environ, **dbt_env(mariadb_url), "DBT_PROFILES_DIR": "."}
    try:
        proc = subprocess.run(["dbt", "build"], cwd=project_dir, env=env,
                              capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        return GateResult(ran=False, error=f"dbt 를 못 돌렸다: {e}")
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
