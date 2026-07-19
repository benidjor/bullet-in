"""config/sources.yaml 의 차등 서빙 선언 계약 (spec §2.3 매핑표)."""
import yaml
from pathlib import Path

FULL_SOURCES = {"arsenal_official", "x_afcstuff", "fmkorea"}

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
