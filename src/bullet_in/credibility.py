from __future__ import annotations
import re
from pathlib import Path
import yaml

_HANDLE_RE = re.compile(r"@(\w+)")  # used by resolve_tier in Task 2

class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float],
                 journalist_outlets: dict[str, str] | None = None):
        self.journalists = journalists  # alias·정식명(lower) -> tier
        self.outlets = outlets
        self.journalist_outlets = journalist_outlets or {}  # 소속 지정 기자만 (프리랜서 부재)

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
    j_outlets: dict[str, str] = {}
    for e in data.get("journalists", []) or []:
        # 정식명 키 — html 추출 결과는 풀네임이라 alias 만으론 매치 불가.
        # aliases 에 이미 이름이 있는 항목 (Sam Dean 등) 이 있어 setdefault.
        jour.setdefault(e["name"].lower(), float(e["tier"]))
        if e.get("outlet"):
            for key in [e["name"], *e["aliases"]]:
                j_outlets[key.lower()] = e["outlet"]
    return Registry(jour, out, j_outlets)

def journalist_display_names(path) -> dict[str, str]:
    """alias(lower) -> 기자 정식 영문명. 바이라인 표기용 (fmkorea 한글 말머리 → 영문)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for e in data.get("journalists", []) or []:
        for alias in e["aliases"]:
            out[alias.lower()] = e["name"]
    return out

def journalist_directory(path) -> dict[str, dict]:
    """alias · 정식명(lower) -> {"name": 정식 영문명, "outlet": 소속 | None}.
    바이라인 표기 · facet 정규화 · 등재 판정을 한 번에 해결하는 서빙용 조회 맵."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for e in data.get("journalists", []) or []:
        entry = {"name": e["name"], "outlet": e.get("outlet")}
        for key in [e["name"], *e["aliases"]]:
            out.setdefault(key.lower(), entry)
    return out

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
        if tiers:
            return min(tiers)
        outlet = (item.raw_payload.get("outlet") or "").lower()
        if outlet and outlet in registry.outlets:   # 승격 항목 : 아웃렛 폴백
            return registry.outlets[outlet]
        fb = src.get("fallback_tier")
        return float(fb) if fb is not None else None

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
