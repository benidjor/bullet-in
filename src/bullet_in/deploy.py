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
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, fields
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
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(DeployState)}
        return DeployState(**{k: v for k, v in data.items() if k in known})
    except (OSError, ValueError, TypeError, AttributeError):
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
    if not service_result:
        return Verdict("none", "SERVICE_RESULT 없음 — systemd 밖에서 부른 것 같다 · 아무것도 안 한다")
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

    def subjects(self, a: str, b: str, *, limit: int = 5) -> list[str]:
        """a 뒤 b 까지의 커밋을 「해시 7자리 제목」 으로 (최신 먼저 · 상한 limit)."""
        out = self._git("log", f"--max-count={limit}", "--format=%h %s", f"{a}..{b}",
                        check=False).stdout
        return [line for line in out.splitlines() if line.strip()]

    def shortstat(self, a: str, b: str) -> str:
        return self._git("diff", "--shortstat", f"{a}..{b}", check=False).stdout.strip()

    def remote_url(self) -> str:
        return self._git("remote", "get-url", "origin", check=False).stdout.strip()


# ── 알림 ──────────────────────────────────────────────────────────────────────

def _alert(title: str, description: str, *, incident: bool,
           fields: list[dict] | None = None, url: str | None = None) -> None:
    notify.send_alert(title=title, description=description,
                      color=notify.COLOR_FAILURE if incident else notify.COLOR_CANDIDATE,
                      fields=fields, url=url, footer="bullet-in deploy",
                      channel=notify.CHANNEL_INCIDENT if incident else notify.CHANNEL_REVIEW)


def _short(sha: str) -> str:
    return sha[:7]


_GITHUB_REMOTE = re.compile(r"^(?:https://github\.com/|git@github\.com:)([^/\s]+/[^/\s]+?)(?:\.git)?/?$")


def compare_url(remote: str, a: str, b: str) -> str | None:
    """GitHub 원격이면 두 커밋의 compare 링크 · 아니면 None (테스트의 로컬 원격 등)."""
    m = _GITHUB_REMOTE.match(remote.strip())
    return f"https://github.com/{m.group(1)}/compare/{_short(a)}...{_short(b)}" if m else None


def _change_fields(repo: Repo, a: str, b: str, *, label: str) -> tuple[str, list[dict], str | None]:
    """a 에서 b 로 바뀐 것의 제목 한 줄 · 필드 둘 (커밋 목록 · 변경 규모) · compare 링크.

    알림에 「무엇이 나갔나 · 되돌려졌나」 를 싣는 자리다 (2026-09-04). git 이 무엇으로 실패해도
    알림 자체는 나가야 하므로 그때는 빈 값으로 돌려준다.
    """
    if not a or not b:
        return "", [], None
    try:
        subjects = repo.subjects(a, b)
        stat = repo.shortstat(a, b)
        url = compare_url(repo.remote_url(), a, b)
    except (OSError, subprocess.SubprocessError) as e:  # 알림은 나가야 한다
        log.warning("변경 내역을 못 읽었다: %s", e)
        return "", [], None
    title = subjects[0].split(" ", 1)[1][:120] if subjects and " " in subjects[0] else ""
    fields = [{"name": label, "value": "\n".join(f"- {s}" for s in subjects)[:1024] or "-",
               "inline": False},
              {"name": "변경 규모", "value": stat or "-", "inline": True}]
    return title, fields, url


def read_local_build(path: Path = Path("site/build.json")) -> dict | None:
    """이 회차가 렌더한 표지 (run.py 가 썼다). 라이브 표지는 전파 전이면 옛 것일 수 있어
    「이 회차의 run_id」 는 여기서 읽는다 (2026-09-03 실측 · 같은 커밋 재배포에서 드러났다)."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _hhmm(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return None


def _time_field(advanced_at: str) -> dict:
    now = datetime.now(timezone.utc).astimezone()
    then = _hhmm(advanced_at)
    if then is None:
        return {"name": "시간", "value": f"판정 {now:%H:%M}", "inline": True}
    secs = int((now - then).total_seconds())
    return {"name": "시간",
            "value": f"전진 {then:%H:%M} → 판정 {now:%H:%M} ({secs // 60}분 {secs % 60}초)",
            "inline": True}


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
    # uv 가 새 잠금 파일을 동기화하면 stderr 에 패키지 목록이 길게 남는다 — 사유는 stdout 에 있다.
    out = proc.stdout.strip().splitlines()
    tail = out[-8:] if out else proc.stderr.strip().splitlines()[-8:]
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
        # 보류 (pending) 중에 또 전진하면 previous 는 마지막으로 확인된 커밋을 지킨다 — 미판정 커밋으로 되돌리지 않는다.
        state.previous = state.previous if state.pending else head
        state.current, state.pending = target, True
        state.advanced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return f"전진 {_short(head)} → {_short(target)} · 회차 끝에 판정"
    except Exception as e:  # noqa: BLE001 — 전진 실패로 회차를 잃지 않는다
        log.exception("advance 예외")
        _alert("🚧 코드 전진 — 예외", f"{type(e).__name__}: {e}"[:1000], incident=True)
        return f"예외 — 현재 코드로 계속 ({type(e).__name__})"


# ── 롤백 · 표지 · 판정 ─────────────────────────────────────────────────────────

def rollback(repo: Repo, state: DeployState, *, reason: str) -> str:
    """직전 커밋으로 되돌리고 현재 커밋을 차단한다. 자동 · 수동이 같은 함수다 (스펙 §7)."""
    bad, good = state.current, state.previous
    repo.reset_hard(good)
    if bad and bad not in state.blocked:
        state.blocked.append(bad)
    state.pending = False
    subject, fields, url = _change_fields(repo, good, bad, label="되돌린 커밋")
    _alert(f"⏪ 코드 롤백 — {subject}" if subject else "⏪ 코드 롤백 — 직전 커밋으로 되돌렸다",
           f"{_short(bad)} → {_short(good)} · 사유: {reason}\n"
           "**코드 탓이 아닐 수 있다** — DB 다운 · 데이터 부채로 실패한 회차도 같은 모양이다 · "
           "새 커밋이 main 에 오면 다시 전진한다 · 같은 커밋을 다시 보려면 "
           f"`uv run python -m bullet_in.deploy unblock {_short(bad)}`",
           incident=True, url=url,
           fields=fields + [{"name": "저널",
                             "value": "`journalctl -u bullet-in.service -n 200 --no-pager`",
                             "inline": False}])
    return f"롤백 {_short(bad)} → {_short(good)}"


def unblock(state: DeployState, sha_prefix: str) -> int:
    before = len(state.blocked)
    state.blocked = [s for s in state.blocked if not s.startswith(sha_prefix)]
    return before - len(state.blocked)


def fetch_build(url: str = BUILD_URL) -> tuple[dict | None, str]:
    """라이브의 build.json 과 「무엇을 받았나」 한 줄.

    비 200 · 0바이트 · JSON 아님은 전부 (None, 사유) 다 (스펙 §6.1) — 알림이 상태 코드와
    바이트 수를 실어야 캐시인지 장애인지 사람이 가른다 (스펙 §10).
    """
    try:
        r = httpx.get(url, follow_redirects=True, timeout=20)
    except httpx.HTTPError as e:
        log.warning("build.json 수신 실패: %s", e)
        return None, f"수신 실패 {type(e).__name__}"
    detail = f"status {r.status_code} · {len(r.content)} bytes"
    if r.status_code != 200 or not r.content:
        return None, detail
    try:
        data = r.json()
    except ValueError:
        return None, f"{detail} · JSON 아님"
    if not isinstance(data, dict):
        return None, f"{detail} · JSON 이 객체가 아님"
    return data, detail


def build_matches(sha: str, *, fetch=fetch_build, tries: int = 3,
                  wait: float = 20.0) -> tuple[bool, str]:
    """최상위 도메인이 배포 직후 잠깐 옛 것을 돌려주므로 몇 번 다시 받는다."""
    got, fetch_detail = None, ""
    for i in range(tries):
        data, fetch_detail = fetch()
        got = data.get("commit") if data else None
        if got == sha:
            run_id = str(data.get("run_id") or "?")
            return True, f"{_short(sha)} · run {run_id[:8]}"
        if i < tries - 1:
            time.sleep(wait)
    if isinstance(got, str) and got:
        return False, f"commit {_short(got)} · {fetch_detail}"
    return False, fetch_detail or "비정상 응답"


# Airflow 에서 부를 때의 입력 (스펙 2026-09-04 §6.3). judge 의 재료 두 값은 그대로다 —
# 상태 일곱을 그 두 값으로 옮기는 얇은 층만 새로 둔다. warehouse_load 는 회차 결과와
# 무관하게 도는 것이라 판정 재료가 아니고 judge 자신은 아직 running 이다.
PIPELINE_TASKS = ("advance", "collect", "enrich", "publish", "gate", "deploy_site")


def parse_task_states(text: str) -> dict[str, str]:
    """`airflow tasks states-for-dag-run … -o json` 의 목록이나 {task_id: state} 사전을 받는다."""
    data = json.loads(text)
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    return {str(r["task_id"]): str(r.get("state")) for r in data if "task_id" in r}


def airflow_inputs(states: dict[str, str]) -> tuple[str, str]:
    """상태 일곱 → (service_result, exit_status). 스펙 §6.3 표의 세 갈래."""
    if states.get("gate") == "skipped":
        return "exit-code", str(GATE_CRASH_EXIT)
    for task in PIPELINE_TASKS:
        if states.get(task) != "success":
            return "exit-code", task
    return "success", "0"


def judge(repo: Repo, state: DeployState, *, service_result: str, exit_status: str,
          matches=None) -> str:
    """회차 끝에 systemd 가 준 결과로 판정한다 (스펙 §6 표)."""
    matches = matches or build_matches
    v = decide(state, service_result, exit_status)
    if v.action == "none":
        return v.reason
    if v.action == "rollback":
        return rollback(repo, state, reason=v.reason)
    if v.action == "hold":
        _alert("⏸ 코드 반영 판정 보류", f"{_short(state.current)} · {v.reason}", incident=False)
        return "판정 보류"
    ok, detail = matches(state.current)
    state.pending = False
    if ok:
        subject, fields, url = _change_fields(repo, state.previous, state.current, label="반영된 커밋")
        local_run = str((read_local_build() or {}).get("run_id") or "?")[:8]
        live_run = detail.rsplit("run ", 1)[1] if "run " in detail else "?"
        fields += [_time_field(state.advanced_at),
                   {"name": "회차", "value": f"run {local_run} · 라이브 표지 run {live_run}",
                    "inline": True}]
        _alert(f"✅ 코드 반영 완료 — {subject}" if subject else "✅ 코드 반영 완료",
               f"{_short(state.previous)} → {_short(state.current)} · 첫 회차 통과 · 라이브 표지 일치",
               incident=False, fields=fields, url=url)
        return "반영 완료"
    _alert("🚧 배포는 나갔는데 라이브 표지가 다르다",
           f"기대 {_short(state.current)} · 받은 것 {detail} · 코드는 되돌리지 않는다 (F7) · "
           "몇 분 뒤 `curl -sL https://bullet-in.pages.dev/build.json` 으로 다시 본다",
           incident=True)
    return "표지 불일치"


# ── 표지 · CLI ────────────────────────────────────────────────────────────────

def write_build_marker(site_dir: str | Path, *, run_id: str,
                       repo_root: Path = Path(".")) -> Path:
    """배포본에 커밋 표지를 싣는다 (스펙 §4.4). 판정기가 라이브에서 이것을 읽는다."""
    try:
        sha = Repo(repo_root).head()
    except (OSError, subprocess.SubprocessError):
        sha = "unknown"
    p = Path(site_dir) / "build.json"
    p.write_text(json.dumps({"commit": sha, "run_id": run_id,
                             "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    return p


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="머지된 코드의 자동 반영 · 판정 · 롤백")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("advance", help="회차 시작 — origin/main 을 내려받는다 (ExecStartPre)")
    jd = sub.add_parser("judge", help="회차 끝 — $SERVICE_RESULT · $EXIT_STATUS 로 판정 (ExecStopPost) "
                                      "· --from-airflow 면 태스크 상태 JSON 으로")
    jd.add_argument("--from-airflow", metavar="PATH",
                    help="airflow tasks states-for-dag-run -o json 의 출력 파일 (- 는 stdin)")
    sub.add_parser("preflight", help="새 코드가 돌 수 있는지 (advance 가 새 uv run 으로 부른다)")
    sub.add_parser("rollback", help="사람이 — 직전 커밋으로 되돌리고 현재 커밋을 차단")
    ub = sub.add_parser("unblock", help="사람이 — 차단 목록에서 뺀다")
    ub.add_argument("sha")
    args = ap.parse_args(argv)

    if args.command == "preflight":
        problems = preflight()
        for p in problems:
            print(p)
        return 1 if problems else 0

    state = load_state(STATE_PATH)
    repo = Repo(Path("."))
    try:
        if args.command == "advance":
            out = advance(repo, state)
        elif args.command == "judge":
            if args.from_airflow:
                raw = sys.stdin.read() if args.from_airflow == "-" else Path(args.from_airflow).read_text()
                service_result, exit_status = airflow_inputs(parse_task_states(raw))
            else:
                service_result = os.environ.get("SERVICE_RESULT", "")
                exit_status = os.environ.get("EXIT_STATUS", "")
            out = judge(repo, state, service_result=service_result, exit_status=exit_status)
        elif args.command == "rollback":
            out = rollback(repo, state, reason="수동 (사람이 rollback 을 쳤다)")
        else:
            n = unblock(state, args.sha)
            out = f"차단 해제 {n}건"
    except Exception as e:  # noqa: BLE001 — 판정기 · 전진기가 유닛 결과를 바꾸면 안 된다
        log.exception("%s 예외", args.command)
        _alert(f"🚧 deploy {args.command} — 예외", f"{type(e).__name__}: {e}"[:1000], incident=True)
        out = f"예외 ({type(e).__name__})"
    save_state(state, STATE_PATH)
    log.info("deploy %s — %s", args.command, out)
    print(out)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
