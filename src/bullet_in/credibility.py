from __future__ import annotations
import re
from pathlib import Path
import yaml

_HANDLE_RE = re.compile(r"@(\w+)")  # used by resolve_tier in Task 2
_WS_RE = re.compile(r"\s+")


def norm_alias(s: str) -> str:
    """별칭 조회 키 — 소문자 + 공백 제거.
    같은 이름을 fmkorea 말머리 · 본문이 붙여 쓰기도 하고 띄어 쓰기도 해서
    ("데이비드온스테인" · "데이비드 온스테인") 공백을 무시해야 등급 · 표기가 통한다."""
    return _WS_RE.sub("", s).lower()


def _with_norm_keys(m: dict) -> dict:
    """공백 무시 키를 덧붙인 사본 — 기존 키 (소문자 원형) 조회는 그대로 통한다.
    표기 변종 ("드 로셰" · "드로셰") 은 한 키가 되므로 먼저 들어온 값을 남긴다."""
    out = dict(m)
    for k, v in m.items():
        out.setdefault(norm_alias(k), v)
    return out

class Registry:
    def __init__(self, journalists: dict[str, float], outlets: dict[str, float],
                 journalist_outlets: dict[str, str] | None = None):
        self.journalists = _with_norm_keys(journalists)  # alias·정식명(lower) -> tier
        self.outlets = _with_norm_keys(outlets)
        # 소속 지정 기자만 (프리랜서 부재)
        self.journalist_outlets = _with_norm_keys(journalist_outlets or {})

def _build(entries: list[dict], dest: dict[str, float]) -> None:
    for e in entries or []:
        # tier 없는 항목은 표기 전용 — 표기만 통일하고 등급은 안 매긴다 (기자명 통일 설계 §4.1).
        # Registry 에 안 들어가므로 resolve_tier 의 세 경로가 모두 이 항목을 못 본다.
        if e.get("tier") is None:
            continue
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
        if e.get("tier") is not None:
            jour.setdefault(e["name"].lower(), float(e["tier"]))
        if e.get("outlet"):
            for key in [e["name"], *e["aliases"]]:
                j_outlets[key.lower()] = e["outlet"]
    return Registry(jour, out, j_outlets)

def journalist_directory(path) -> dict[str, dict]:
    """alias · 정식명(lower) -> {"name": 정식 영문명, "outlet": 소속 | None}.
    바이라인 표기 · facet 정규화 · 등재 판정을 한 번에 해결하는 서빙용 조회 맵."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for e in data.get("journalists", []) or []:
        entry = {"name": e["name"], "outlet": e.get("outlet")}
        for key in [e["name"], *e["aliases"]]:
            out.setdefault(key.lower(), entry)
            out.setdefault(norm_alias(key), entry)
    return out

def outlet_directory(path) -> dict[str, str]:
    """outlets alias · 정식명(lower) -> 정식명. 조직 계정 핸들 접기 등 표시 정규화용
    (journalist_directory 의 outlets 판 — Registry 는 tier 만 있어 정식명 복원 불가)."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for e in data.get("outlets", []) or []:
        for key in [e["name"], *e["aliases"]]:
            out.setdefault(key.lower(), e["name"])
            out.setdefault(norm_alias(key), e["name"])
    return out

def resolve_tier(item, sources: dict, registry: "Registry | None",
                 journalist: str | None = None) -> float | None:
    """항목 1건의 tier 를 산출. None 이면 호출측에서 그 항목을 버린다."""
    src = sources.get(item.source_id, {})
    mode = src.get("credibility")

    if mode == "x_mentions":
        if registry is None:
            return None
        text = item.raw_payload.get("text", "")
        handles = {norm_alias("@" + h) for h in _HANDLE_RE.findall(text)}
        tiers = [registry.journalists[k] for k in handles if k in registry.journalists]
        if tiers:
            return min(tiers)
        outlet = norm_alias(item.raw_payload.get("outlet") or "")
        if outlet and outlet in registry.outlets:   # 승격 항목 : 아웃렛 폴백
            return registry.outlets[outlet]
        fb = src.get("fallback_tier")
        return float(fb) if fb is not None else None

    if mode == "fmkorea":
        if registry is None:
            return 4.0
        # 공백 무시로 훑는다 — 같은 이름의 붙여 쓴 표기 · 띄어 쓴 표기를 함께 잡는다
        title = norm_alias(item.raw_payload.get("title") or "")
        body = norm_alias(item.raw_payload.get("body") or "")
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
    if tier is None:
        return None
    tier = float(tier)
    # 소속이 기사 소스와 일치하는 등재 기자만 min 가드로 승격 (spec §2).
    # 프리랜서 (outlet 미지정) · 미등재 기자는 표시 전용 — tier 무조정.
    if journalist and registry is not None:
        key = norm_alias(journalist)
        j_tier = registry.journalists.get(key)
        j_outlet = registry.journalist_outlets.get(key)
        if j_tier is not None and j_outlet and j_outlet == src.get("outlet"):
            return min(j_tier, tier)
    return tier
