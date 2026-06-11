from __future__ import annotations
import re
from pathlib import Path
import yaml

_HANDLE_RE = re.compile(r"@(\w+)")  # used by resolve_tier in Task 2

class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float]):
        self.journalists = journalists  # alias(lower) -> tier
        self.outlets = outlets

def _build(entries: list[dict], dest: dict[str, float]) -> None:
    for e in entries or []:
        tier = float(e["tier"])
        for alias in e["aliases"]:
            key = alias.lower()  # registry keys are always lowercased for case-insensitive lookup
            if key in dest:
                raise ValueError(f"duplicate alias: {alias}")
            dest[key] = tier

def load_registry(path) -> Registry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jour: dict[str, float] = {}
    out: dict[str, float] = {}
    _build(data.get("journalists", []), jour)
    _build(data.get("outlets", []), out)
    return Registry(jour, out)

def resolve_tier(item, sources: dict, registry: "Registry | None") -> float | None:
    """항목 1건의 tier 를 산출. None 이면 호출측에서 그 항목을 버린다."""
    src = sources.get(item.source_id, {})
    mode = src.get("credibility")

    if mode == "x_mentions":
        if registry is None:
            return None
        text = item.raw_payload.get("text", "")
        handles = {("@" + h).lower() for h in _HANDLE_RE.findall(text)}
        tiers = [registry.journalists[k] for k in handles if k in registry.journalists]
        return min(tiers) if tiers else None

    if mode == "fmkorea":
        if registry is None:
            return 4.0
        title = (item.raw_payload.get("title") or "").lower()
        body = (item.raw_payload.get("body") or "").lower()
        text = title + " " + body
        jt = [t for a, t in registry.journalists.items() if a in text]
        if jt:
            return min(jt)
        ot = [t for a, t in registry.outlets.items() if a in title]
        if ot:
            return min(ot)
        return 4.0

    # 고정 소스: tier 미지정(설정 누락 등)이면 None → 항목 drop
    tier = src.get("tier")
    return float(tier) if tier is not None else None
