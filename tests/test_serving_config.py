"""config/sources.yaml 의 서빙 선언 계약 (spec §2.3 개정 2026-07-20 — 전 소스 전문 서빙).

fmkorea 경로 ③ (퍼가기 금지 + 페이월) 은 수집 단계 헤드라인-온리라 serving 값과 무관."""
import yaml
from pathlib import Path

FULL_SOURCES = {"arsenal_official", "x_afcstuff", "x_ornstein", "fmkorea",
                "bbc_sport", "bbc_gossip", "skysports", "guardian",
                "goal", "football_london"}

def _modes():
    data = yaml.safe_load((Path(__file__).parent.parent / "config" / "sources.yaml").read_text(encoding="utf-8"))
    return {s["source_id"]: s.get("serving") for s in data["sources"]}

def test_every_source_declares_valid_serving_mode():
    modes = _modes()
    invalid = {k: v for k, v in modes.items() if v not in ("full", "excerpt")}
    assert not invalid, f"serving 미선언 · 미상 값: {invalid}"

def test_full_mode_matches_spec_mapping():
    modes = _modes()
    assert {sid for sid, m in modes.items() if m == "full"} == FULL_SOURCES

def test_football_london_collection_disabled():
    """저품질 기사 비중이 높아 소스를 내렸다 (스펙 2026-07-29 §4.6).
    항목 자체는 남긴다 — 지우면 serving 모드 계약 검사에서도 사라져 되살아난 것을 못 잡는다."""
    data = yaml.safe_load((Path(__file__).parent.parent / "config" / "sources.yaml")
                          .read_text(encoding="utf-8"))
    fl = next(s for s in data["sources"] if s["source_id"] == "football_london")
    assert fl.get("enabled") is False
