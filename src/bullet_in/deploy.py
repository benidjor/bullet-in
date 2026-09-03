"""머지된 코드를 회차가 스스로 반영하고 판정한다.

설계 = docs/superpowers/specs/2026-09-03-deploy-automation-design.md

명령 넷 — advance (회차 시작 · ExecStartPre) · judge (회차 끝 · ExecStopPost) ·
rollback (사람이) · unblock (사람이). preflight 는 advance 가 새 코드로 부르는 내부 명령.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from bullet_in import notify
from bullet_in.dbt_gate import GATE_CRASH_EXIT

log = logging.getLogger(__name__)

STATE_PATH = Path("state/deploy.json")
BUILD_URL = "https://bullet-in.pages.dev/build.json"

# 없으면 유닛 다섯 중 하나가 조용히 반쯤 도는 키 (스펙 §9.1). 죽는 키는 OnFailure 가 잡으므로
# 이 목록의 값어치는 조용한 쪽에 있다. 새 기능이 키를 더하면 같은 PR 에서 여기에 올린다.
REQUIRED_ENV: tuple[str, ...] = (
    "MARIADB_URL", "MONGO_URI", "GEMINI_API_KEY",
    "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "DISCORD_WEBHOOK_INCIDENT", "DISCORD_WEBHOOK_REVIEW",
    "GA4_DATASET",
    "ICEBERG_CATALOG_URI", "ICEBERG_WAREHOUSE", "GCS_BACKUP_BUCKET",
)


@dataclass
class DeployState:
    current: str = ""
    previous: str = ""
    pending: bool = False
    blocked: list[str] = field(default_factory=list)
    advanced_at: str = ""


def load_state(path: Path = STATE_PATH) -> DeployState:
    try:
        return DeployState(**json.loads(Path(path).read_text()))
    except (OSError, ValueError, TypeError):
        return DeployState()


def save_state(state: DeployState, path: Path = STATE_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(asdict(state), ensure_ascii=False, indent=1))


@dataclass(frozen=True)
class Verdict:
    action: str    # none · confirm · hold · rollback
    reason: str


def decide(state: DeployState, service_result: str, exit_status: str) -> Verdict:
    """유닛 결과 하나와 종료 코드 하나로 판정한다 (스펙 §6 표).

    원인은 모른다 — 「무엇이 보이면」 으로만 적는다. 넓게 되돌리는 대신 알림이
    원인을 단정하지 않는다 (스펙 §3.2).
    """
    if not state.pending:
        return Verdict("none", "판정 대기 없음")
    if service_result == "success":
        return Verdict("confirm", "회차 · 게이트 · 배포 통과")
    if service_result == "exit-code" and exit_status == str(GATE_CRASH_EXIT):
        return Verdict("hold", "게이트 급사 (dbt 신호 종료) — 다음 회차에 다시 판정")
    return Verdict("rollback", f"유닛 결과 {service_result} · 종료 코드 {exit_status or '?'}")
