"""회차 본체의 단계 분리 (스펙 2026-09-04 §5) — 수집 값은 회차 행으로 단계 사이를 건넌다."""
import json
from datetime import datetime

import pytest

from bullet_in import run as run_mod
from bullet_in.run import FetchSummary, STAGES, run_stage


def _summary(**over):
    base = dict(run_id="r1", started_at_utc=datetime(2026, 9, 4, 3, 0, 0), fetch_sec=7.5,
                source_counts={"bbc_sport": 2}, candidate_counts={"bbc_sport": 4},
                new_count=2, dup_count=1, blocked_count=0,
                errors={"fmkorea": "HTTP 430"}, funnels={"fmkorea": {"found": 15}},
                success_rate=0.9)
    base.update(over)
    return FetchSummary(**base)


def test_fetch_summary_roundtrips_through_row_params():
    s = _summary()
    params = s.to_params(dag_run_id="manual")
    assert params["rid"] == "r1" and params["drid"] == "manual"
    assert json.loads(params["detail"]) == {"errors": {"fmkorea": "HTTP 430"},
                                            "funnels": {"fmkorea": {"found": 15}}}
    # DB 가 돌려주는 모양 — JSON 열은 문자열로 온다
    row = {"run_id": "r1", "started_at": s.started_at_utc, "fetch_duration_sec": 7.5,
           "source_counts": params["counts"], "candidate_counts": params["cands"],
           "new_count": 2, "dup_count": 1, "blocked_count": 0, "error_count": 1,
           "success_rate": 0.9, "fetch_detail": params["detail"]}
    assert FetchSummary.from_row(row) == s


def test_fetch_summary_tolerates_missing_detail():
    row = {"run_id": "r1", "started_at": datetime(2026, 9, 4), "fetch_duration_sec": 1.0,
           "source_counts": "{}", "candidate_counts": None, "new_count": 0, "dup_count": 0,
           "blocked_count": None, "error_count": 0, "success_rate": 1.0, "fetch_detail": None}
    s = FetchSummary.from_row(row)
    assert s.errors == {} and s.funnels == {} and s.candidate_counts == {} and s.blocked_count == 0


def test_stage_order_is_fixed():
    assert STAGES == ("collect", "enrich", "publish", "gate")


def test_run_stage_dispatches_one_stage_only(monkeypatch):
    calls = []
    async def fake_collect(run_id, concurrency):
        calls.append(("collect", run_id, concurrency))
    monkeypatch.setattr(run_mod, "collect", fake_collect)
    monkeypatch.setattr(run_mod, "enrich", lambda run_id: calls.append(("enrich", run_id)))
    monkeypatch.setattr(run_mod, "publish", lambda run_id: calls.append(("publish", run_id)))
    monkeypatch.setattr(run_mod, "gate", lambda run_id: calls.append(("gate", run_id)))
    run_stage("collect", "r1", 8)
    run_stage("gate", "r1", 8)
    assert calls == [("collect", "r1", 8), ("gate", "r1")]


def test_run_stage_rejects_unknown_stage():
    with pytest.raises(ValueError):
        run_stage("render", "r1", 8)


async def test_main_runs_the_four_stages_in_order_with_one_run_id(monkeypatch):
    seen = []
    async def fake_collect(run_id, concurrency):
        seen.append(("collect", run_id))
    monkeypatch.setattr(run_mod, "collect", fake_collect)
    for name in ("enrich", "publish", "gate"):
        monkeypatch.setattr(run_mod, name,
                            lambda run_id, _n=name: seen.append((_n, run_id)))
    await run_mod.main(concurrency=3)
    assert [s for s, _ in seen] == list(STAGES)
    assert len({r for _, r in seen}) == 1


def test_cli_requires_run_id_with_stage():
    with pytest.raises(SystemExit):
        run_mod.parse_args(["--stage", "collect"])
    ns = run_mod.parse_args(["--stage", "collect", "--run-id", "abc"])
    assert (ns.stage, ns.run_id, ns.concurrency) == ("collect", "abc", 8)
    assert run_mod.parse_args([]).stage is None
