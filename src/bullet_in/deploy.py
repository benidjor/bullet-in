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


# ── git ──────────────────────────────────────────────────────────────────────

class Repo:
    """VM 체크아웃에 대한 git 호출. 전부 subprocess 라 테스트는 임시 저장소로 돈다."""

    def __init__(self, root: Path = Path(".")):
        self.root = Path(root)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.root, check=check,
                              capture_output=True, text=True, timeout=120)

    def head(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def remote_main(self) -> str:
        return self._git("rev-parse", "origin/main").stdout.strip()

    def fetch(self) -> bool:
        return self._git("fetch", "origin", "--quiet", check=False).returncode == 0

    def ff_merge(self) -> bool:
        return self._git("merge", "--ff-only", "--quiet", "origin/main",
                         check=False).returncode == 0

    def reset_hard(self, sha: str) -> None:
        self._git("reset", "--hard", "--quiet", sha)

    def status_short(self) -> str:
        return self._git("status", "--short", "--branch", check=False).stdout.strip()[:800]


# ── 알림 ──────────────────────────────────────────────────────────────────────

def _alert(title: str, description: str, *, incident: bool,
           fields: list[dict] | None = None) -> None:
    notify.send_alert(title=title, description=description,
                      color=notify.COLOR_FAILURE if incident else notify.COLOR_CANDIDATE,
                      fields=fields, footer="bullet-in deploy",
                      channel=notify.CHANNEL_INCIDENT if incident else notify.CHANNEL_REVIEW)


def _short(sha: str) -> str:
    return sha[:7]


# ── 사전 점검 · 전진 ───────────────────────────────────────────────────────────

def preflight(environ=os.environ) -> list[str]:
    """새 코드가 돌 수 있는지 회차 전에 본다. 빈 목록이 통과다 (스펙 §5 5번)."""
    problems: list[str] = []
    try:
        importlib.import_module("bullet_in.run")
    except Exception as e:  # noqa: BLE001 — 어떤 import 오류든 한 줄로 실어 알린다
        problems.append(f"import 실패: {type(e).__name__}: {e}"[:300])
    missing = [k for k in REQUIRED_ENV if not environ.get(k)]
    if missing:
        problems.append("필수 키 없음: " + " · ".join(missing))
    return problems


def _uv() -> str:
    # 유닛의 PATH 에는 ~/.local/bin 이 없다 — 유닛 파일이 절대 경로로 부르는 것과 같은 자리.
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def run_preflight_subprocess() -> list[str]:
    """새 프로세스로 preflight 를 부른다.

    같은 프로세스에서 import 하면 옛 코드가 이미 올라와 있고 잠금 파일도 옛것이다.
    `uv run` 을 새로 타야 새 코드 · 새 의존으로 검사한다 (스펙 §5 5번).
    """
    proc = subprocess.run([_uv(), "run", "python", "-m", "bullet_in.deploy", "preflight"],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode == 0:
        return []
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-8:]
    return tail or [f"preflight 종료 코드 {proc.returncode}"]


def advance(repo: Repo, state: DeployState, *,
            run_preflight=run_preflight_subprocess) -> str:
    """회차 시작에 코드를 전진시킨다. 어느 경로로도 예외를 밖으로 내지 않는다 (스펙 §5)."""
    try:
        if not repo.fetch():
            return "fetch 실패 — 현재 코드로 계속 (다음 회차에 다시)"
        head, target = repo.head(), repo.remote_main()
        if target == head:
            return "변경 없음"
        if target in state.blocked:
            return f"{_short(target)} 은 차단 목록 — 새 커밋을 기다림"
        if not repo.ff_merge():
            _alert("🚧 코드 전진 — VM 트리가 갈라졌다",
                   f"`origin/main` {_short(target)} 을 ff 로 못 얹는다 · 현재 {_short(head)} 로 회차를 돌린다 · "
                   "자동으로 되돌리지 않는다 — 사람이 VM 에서 `git status` 를 본다",
                   incident=True, fields=[{"name": "git status", "value": repo.status_short() or "-"}])
            return "ff 거부 — 현재 코드로 계속"
        problems = run_preflight()
        if problems:
            state.blocked.append(target)
            repo.reset_hard(head)
            _alert("🚧 코드 전진 거부 — 사전 점검 실패",
                   f"{_short(target)} 을 내려받았다가 {_short(head)} 로 되돌렸다 · 이번 회차는 직전 코드로 돈다 · "
                   "고친 커밋이 main 에 오면 다시 전진한다",
                   incident=True, fields=[{"name": "사유", "value": "\n".join(f"- {p}" for p in problems)[:1024]}])
            return "사전 점검 실패 — 되돌림"
        state.previous, state.current, state.pending = head, target, True
        state.advanced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return f"전진 {_short(head)} → {_short(target)} · 회차 끝에 판정"
    except Exception as e:  # noqa: BLE001 — 전진 실패로 회차를 잃지 않는다
        log.exception("advance 예외")
        _alert("🚧 코드 전진 — 예외", f"{type(e).__name__}: {e}"[:1000], incident=True)
        return f"예외 — 현재 코드로 계속 ({type(e).__name__})"
