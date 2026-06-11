from pathlib import Path
import yaml

def load_sources(path: str | Path) -> dict[str, dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {s["source_id"]: s for s in data["sources"] if s.get("enabled", True)}

def confidence_from_tier(tier: float | None) -> float:
    """tier 0..4 를 confidence 1.0..0.0 로 선형 매핑. None 은 0.0."""
    if tier is None:
        return 0.0
    return round(max(0.0, 1.0 - float(tier) / 4.0), 3)

def confidence(source_id: str, sources: dict[str, dict]) -> float:
    """tier 0..4 를 confidence 1.0..0.0 로 선형 매핑. 미지의 소스·tier 미지정은 0.0."""
    src = sources.get(source_id) or {}
    return confidence_from_tier(src.get("tier"))
