"""회차 끝에서 dbt 품질 검사를 돌리고 결과로 배포를 막는 게이트.

설계 = docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

# dbt 가 내는 테스트 상태 — fail 은 error_if 를 넘긴 것 · warn 은 warn_if 만 넘긴 것.
_BLOCKING = {"fail", "error"}


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
    except OSError as e:
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
