from bullet_in.run import cliff_alert_payload


class _Adapter:
    def __init__(self, source_id, codes=None):
        self.source_id = source_id
        if codes is not None:
            self.search_failure_codes = codes


def test_payload_none_when_no_history():
    """첫 회차 — 직전 행이 없으면 판정하지 않는다."""
    assert cliff_alert_payload({"goal": 14}, [], adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_none_when_no_cliff():
    history = [{"goal": 13, "fmkorea": 10}]
    assert cliff_alert_payload({"goal": 14, "fmkorea": 9}, history,
                               adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None


def test_payload_built_for_cliff_with_adapter_codes():
    history = [{"fmkorea": 10, "goal": 13}]
    payload = cliff_alert_payload(
        {"goal": 14}, history,
        adapters=[_Adapter("fmkorea", {430: 4}), _Adapter("goal")],
        sources={"fmkorea": {"display_name": "fmkorea 축구 소식통"}},
        success_rate=1.0, run_id="3259230a")
    assert "후보 절벽" in payload["title"]
    assert "HTTP 430 4건" in payload["fields"][0]["value"]


def test_payload_ignores_source_already_at_zero():
    """arsenal_official 은 직전에도 0 — 전이가 아니므로 알림이 없다."""
    history = [{"arsenal_official": 0, "goal": 13}]
    assert cliff_alert_payload({"goal": 14}, history, adapters=[], sources={},
                               success_rate=1.0, run_id="r") is None
