"""배포 자동화 (스펙 2026-09-03) — 상태 · 판정 · 전진 · 롤백 · 표지."""
import json
from pathlib import Path

import pytest

from bullet_in.deploy import DeployState, Verdict, decide, load_state, save_state


def test_state_roundtrip_and_defaults(tmp_path):
    p = tmp_path / "deploy.json"
    assert load_state(p) == DeployState()          # 파일이 없으면 기본값
    s = DeployState(current="n" * 40, previous="p" * 40, pending=True,
                    blocked=["b" * 40], advanced_at="2026-09-04T00:03:12+00:00")
    save_state(s, p)
    assert load_state(p) == s
    assert json.loads(p.read_text())["pending"] is True


def test_decide_does_nothing_without_pending():
    assert decide(DeployState(pending=False), "exit-code", "1").action == "none"


@pytest.mark.parametrize("service_result,exit_status,action", [
    ("success", "0", "confirm"),
    ("exit-code", "3", "hold"),        # 게이트 급사 (dbt 세그폴트) — 되돌리지 않는다
    ("exit-code", "1", "rollback"),    # 예외 · 게이트 위반 · dbt 자체 실패
    ("timeout", "", "rollback"),
    ("signal", "9", "rollback"),
])
def test_decide_follows_the_spec_table(service_result, exit_status, action):
    v = decide(DeployState(pending=True), service_result, exit_status)
    assert isinstance(v, Verdict)
    assert v.action == action
