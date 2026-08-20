"""config/sources.yaml 의 신선도 임계 계약 (설계 2026-08-14 §3 · §5.1).

임계는 소스별 공백 95 백분위를 24h 배수로 올린 실측값이라, 빠지면 전역 48h 로
조용히 떨어져 정상 소스가 회차의 20~30% 에서 stale 로 찍힌다."""
import yaml
from pathlib import Path

# bbc_sport · skysports · guardian 은 마감 전 임시값이다 (2026-08-20 · 원본 수집
# 기준 재측정). 2026-09-02 마감 뒤 각각 96 · 120 · 192 로 원복하며, 그때 이 표도
# 함께 되돌린다 (안건 ι · 임계계절성 · 절차는 재측정 런북).
THRESHOLDS = {"fmkorea": 24, "x_afcstuff": 24, "bbc_gossip": 24,
              "bbc_sport": 72, "skysports": 96, "x_ornstein": 120,
              "guardian": 120}


def _sources():
    data = yaml.safe_load((Path(__file__).parent.parent / "config" / "sources.yaml")
                          .read_text(encoding="utf-8"))
    return {s["source_id"]: s for s in data["sources"]}


def test_watched_sources_carry_measured_thresholds():
    got = {sid: s.get("freshness_hours") for sid, s in _sources().items()
           if sid in THRESHOLDS}
    assert got == THRESHOLDS


def test_stopped_source_is_excluded_from_watch():
    """수집을 끊은 소스에는 freshness_hours: 0 을 함께 준다.

    collect: false 는 load_sources 가 안 보므로 감시 대상에 그대로 남는다.
    수집이 멈추면 경과가 무한히 자라 48시간마다 영원히 알린다."""
    stopped = [sid for sid, s in _sources().items()
               if s.get("collect") is False and s.get("enabled", True)]
    assert stopped, "수집 중단 소스가 없으면 이 계약을 검사할 대상도 없다"
    for sid in stopped:
        assert _sources()[sid].get("freshness_hours") == 0, sid
