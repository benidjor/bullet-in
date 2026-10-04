"""공식 소스 사이트맵 실패 알림의 배선 — SLO-2 여유 셈과 어댑터 걷기 (설계 2026-10-05 §4.2)."""
from bullet_in.run import sitemap_alert_payloads, slo2_margin

RID = "scheduled__2026-10-04T18:00:00+00:00"


class _Adapter:
    def __init__(self, source_id, funnel=None):
        self.source_id = source_id
        if funnel is not None:
            self.funnel = funnel


SEVEN = [_Adapter(f"s{i}") for i in range(7)]          # funnel 없는 소스 일곱 + 공식 소스 = 8


def test_margin_counts_the_current_run_and_the_29_before_it():
    # 직전 29회 중 실패 2 (0.875) · 30번째 전 실패 1 은 창 밖 · 이번 실행도 실패
    prev = [0.875, 0.875] + [1.0] * 27 + [0.875]
    assert slo2_margin(prev, 0.875, 8) == (3, 2, 30)   # 한도 = floor(30 × 0.01 × 8) = 2


def test_margin_with_short_history():
    assert slo2_margin([1.0, 0.875], 0.875, 8) == (2, 0, 3)
    assert slo2_margin([], 1.0, 8) == (0, 0, 1)


def test_margin_counts_each_failed_source_not_each_failed_run():
    # 실행 둘이 각각 소스 둘을 잃음 (0.75) — 실패한 실행은 2회지만 소스 실패는 4 · 한도 2 를 넘는다
    assert slo2_margin([0.75] + [1.0] * 28, 0.75, 8) == (4, 2, 30)


def test_payload_when_official_sitemap_failed_after_retry():
    off = _Adapter("arsenal_official", {"sitemap_attempts": 2, "sitemap_sec": 50.1,
                                        "sitemap_first_error": "ReadTimeout"})
    out = sitemap_alert_payloads(SEVEN + [off], {"arsenal_official": "ReadTimeout"},
                                 previous_rates=[1.0] * 29, run_id=RID)
    assert len(out) == 1
    fields = {f["name"]: f["value"] for f in out[0]["fields"]}
    assert fields["SLO-2 여유"] == "최근 30회 중 소스 실패 1회 (2회까지 충족)"


def test_no_payload_when_retry_rescued():
    off = _Adapter("arsenal_official", {"sitemap_attempts": 2, "sitemap_first_error": "503"})
    assert sitemap_alert_payloads(SEVEN + [off], {}, previous_rates=[1.0] * 29, run_id=RID) == []


def test_other_sources_errors_do_not_make_a_sitemap_alert():
    """funnel 이 없거나 사이트맵 키가 없는 어댑터는 건너뛴다."""
    html = _Adapter("goal", {"selected": 3, "deduped": 3, "titled": 3, "passed": 1})
    assert sitemap_alert_payloads(SEVEN + [html], {"goal": "boom", "s0": "x"},
                                  previous_rates=[1.0] * 29, run_id=RID) == []
