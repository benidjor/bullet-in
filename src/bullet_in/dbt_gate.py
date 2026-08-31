"""회차 끝에서 dbt 품질 검사를 돌리고 결과로 배포를 막는 게이트.

설계 = docs/superpowers/specs/2026-08-31-dbt-quality-gate-design.md
"""
from __future__ import annotations

from urllib.parse import unquote, urlparse


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
