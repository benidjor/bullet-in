from pathlib import Path
from bullet_in.score import load_sources, confidence

FIX = Path(__file__).parent / "fixtures" / "sources_min.yaml"

def test_load_only_enabled_sources():
    s = load_sources(FIX)
    assert set(s) == {"arsenal_official", "football_london"}

def test_confidence_is_higher_for_lower_tier():
    s = load_sources(FIX)
    assert confidence("arsenal_official", s) > confidence("football_london", s)

def test_unknown_source_gets_floor_confidence():
    s = load_sources(FIX)
    assert confidence("who_dis", s) == 0.0
