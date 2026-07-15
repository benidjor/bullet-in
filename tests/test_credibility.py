import pytest
from pathlib import Path
from datetime import datetime, timezone
from bullet_in.credibility import load_registry, resolve_tier, Registry
from bullet_in.models import RawItem

REG = Path(__file__).parent.parent / "config" / "credibility.yaml"

def test_load_registry_maps_aliases_lowercased():
    r = load_registry(REG)
    assert r.journalists["@david_ornstein"] == 1.0
    assert r.journalists["온스테인"] == 1.0
    assert r.outlets["디 애슬레틱"] == 1.0
    assert r.outlets["데일리 메일"] == 3.0

def test_load_registry_rejects_duplicate_alias(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: A, tier: 1, aliases: ["dup"]}\n'
        '  - {name: B, tier: 2, aliases: ["dup"]}\n'
        "outlets: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate alias"):
        load_registry(p)

def _item(source_id, payload):
    return RawItem(source_id=source_id, source_type="x", url="u",
                   fetched_at=datetime.now(timezone.utc), raw_payload=payload)

def test_resolve_fixed_source_returns_static_tier():
    sources = {"bbc_sport": {"tier": 1}}
    it = _item("bbc_sport", {"title": "Saka"})
    assert resolve_tier(it, sources, registry=None) == 1.0

def test_resolve_x_mentions_picks_highest_credibility():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "Per @David_Ornstein and @FabrizioRomano, deal close"})
    assert resolve_tier(it, sources, r) == 1.0  # min(1, 1.5)

def test_resolve_x_mentions_drops_when_no_journalist():
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "huge news coming soon @nobody_here"})
    assert resolve_tier(it, sources, r) is None

def test_resolve_fmkorea_journalist_beats_outlet():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[데일리 메일] 루머", "body": "온스테인에 따르면 사실이다"})
    assert resolve_tier(it, sources, r) == 1.0  # 기자(1) > 매체 데일리메일(3)

def test_resolve_fmkorea_outlet_bracket():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[디 애슬레틱] 사카 재계약", "body": "내용"})
    assert resolve_tier(it, sources, r) == 1.0

def test_resolve_fmkorea_fallback_tier_four():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[무명 블로그] 카더라", "body": "출처 불명"})
    assert resolve_tier(it, sources, r) == 4.0

def test_resolve_fmkorea_de_roche_journalist_tier():
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea", {"title": "[디 애슬레틱] 아스날 공격진 분석",
                           "body": "By 드 로셰. 아스날의 하베르츠 복귀."})
    assert resolve_tier(it, sources, r) == 1.5

def test_resolve_x_mentions_no_registry_drops():
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff", {"text": "Per @David_Ornstein, deal close"})
    assert resolve_tier(it, sources, registry=None) is None

def test_resolve_x_mentions_fallback_tier_when_unregistered():
    r = load_registry(REG)
    it = _item("x_afcstuff", {"text": "[@NobodyKnows] 루머"})
    # fallback_tier 있으면 그 값으로 생존
    src_fb = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}
    assert resolve_tier(it, src_fb, r) == 4.0
    # fallback_tier 없으면 종전대로 None (drop)
    src_no = {"x_afcstuff": {"credibility": "x_mentions"}}
    assert resolve_tier(it, src_no, r) is None

def test_registry_has_afcstuff_cited_handles():
    r = load_registry(REG)
    assert r.journalists["@samimokbel_bbc"] == 1.0      # BBC 현행 핸들
    assert "@gunnerblog" in r.journalists
    assert "@matt_law_dt" in r.journalists
    assert "@lattefirm" in r.journalists                 # 팟캐스트 (2순위)

# Task 5: x_mentions 아웃렛 폴백 테스트

def _reg():
    from bullet_in.credibility import Registry
    return Registry(journalists={"@samimokbel_bbc": 1.0}, outlets={"bbc": 1.0, "the sun": 4.0})

_SOURCES = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}

class _Item:
    def __init__(self, payload):
        self.source_id = "x_afcstuff"
        self.raw_payload = payload

def test_tier_journalist_first():
    it = _Item({"text": "[ @SamiMokbel_BBC ] news", "outlet": "BBC"})
    assert resolve_tier(it, _SOURCES, _reg()) == 1.0

def test_tier_outlet_fallback_for_unregistered_journalist():
    # 미등록 기자 + known 아웃렛(BBC=1) → 아웃렛 tier(1), fallback(4) 아님
    it = _Item({"text": "[ @UnknownGuy ] news", "outlet": "BBC"})
    assert resolve_tier(it, _SOURCES, _reg()) == 1.0

def test_tier_fallback_when_neither():
    it = _Item({"text": "[ @UnknownGuy ] news"})
    assert resolve_tier(it, _SOURCES, _reg()) == 4.0

def test_load_registry_includes_canonical_name_key():
    # html 추출 결과는 풀네임 — alias 키만으론 매치 불가 (spec §2)
    r = load_registry(REG)
    assert r.journalists["sami mokbel"] == 1.0
    assert r.journalists["david ornstein"] == 1.0

def test_registry_journalist_outlets_only_for_affiliated():
    r = load_registry(REG)
    assert r.journalist_outlets["sami mokbel"] == "BBC"
    assert r.journalist_outlets["@skysports_sheth"] == "Sky Sports"
    # 프리랜서 (여러 매체 기고) 는 소속 미지정 → 조회 부재
    assert "charles watts" not in r.journalist_outlets
    assert "fabrizio romano" not in r.journalist_outlets

def test_registry_registers_french_outlets():
    r = load_registry(REG)
    assert r.outlets["l'équipe"] == 2.0
    assert r.outlets["레키프"] == 2.0
    assert r.outlets["rmc"] == 1.0
    assert r.outlets["foot mercato"] == 4.0

def test_journalist_directory_maps_alias_and_name():
    from bullet_in.credibility import journalist_directory
    d = journalist_directory("config/credibility.yaml")
    assert d["온스테인"] == {"name": "David Ornstein", "outlet": "The Athletic"}
    assert d["@fabrizioromano"]["name"] == "Fabrizio Romano"
    assert d["fabrizio romano"]["outlet"] is None      # 프리랜서
    assert d["sami mokbel"] == {"name": "Sami Mokbel", "outlet": "BBC"}
    assert "kaya kaynak" not in d                       # 미등재

def test_fixed_source_promotes_tier_for_affiliated_journalist():
    # Sheth (1.5, Sky Sports) @ skysports (1.5) → min(1.5, 1.5)
    r = load_registry(REG)
    sources = {"skysports": {"tier": 1.5, "outlet": "Sky Sports"}}
    it = _item("skysports", {"title": "Alvarez latest"})
    assert resolve_tier(it, sources, r, journalist="Dharmesh Sheth") == 1.5
    # 가상의 승격: 같은 기자가 tier 4 소스에 실렸다면 1.5 로 승격
    sources4 = {"skysports": {"tier": 4, "outlet": "Sky Sports"}}
    assert resolve_tier(it, sources4, r, journalist="Dharmesh Sheth") == 1.5

def test_fixed_source_min_guard_never_demotes():
    # 레지스트리 실수로 기자 tier 가 소스보다 낮아도 (Delaney 3 @ tier 1 소스) 강등 없음
    r = load_registry(REG)
    sources = {"indep": {"tier": 1, "outlet": "The Independent"}}
    it = _item("indep", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Miguel Delaney") == 1.0

def test_fixed_source_freelancer_does_not_adjust_tier():
    # Watts (3) 는 여러 매체 기고 — 소속 미지정 → 표시 전용, tier 무조정 (사용자 결정)
    r = load_registry(REG)
    sources = {"goal": {"tier": 4, "outlet": "Goal.com"}}
    it = _item("goal", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Charles Watts") == 4.0

def test_fixed_source_mismatched_outlet_does_not_adjust_tier():
    # 등재 기자라도 소속이 기사 소스와 다르면 보정하지 않는다
    r = load_registry(REG)
    sources = {"goal": {"tier": 4, "outlet": "Goal.com"}}
    it = _item("goal", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Sami Mokbel") == 4.0

def test_fixed_source_unregistered_journalist_keeps_source_tier():
    r = load_registry(REG)
    sources = {"football_london": {"tier": 4, "outlet": "football.london"}}
    it = _item("football_london", {"title": "x"})
    assert resolve_tier(it, sources, r, journalist="Raff Tindale") == 4.0

def test_fixed_source_without_journalist_keeps_legacy_behavior():
    r = load_registry(REG)
    sources = {"bbc_sport": {"tier": 1, "outlet": "BBC"}}
    assert resolve_tier(_item("bbc_sport", {"title": "x"}), sources, r) == 1.0

def test_gossip_without_source_outlet_keeps_tier_4():
    """bbc_gossip 의 outlet 제거로 소속 일치 보정 경로가 막힌다 (spec §3.4).
    통칭 라벨만 오는 현재 데이터에서는 결과가 중립임을 고정한다."""
    registry = Registry(journalists={"sami mokbel": 1.0},
                        outlets={"bbc": 1.0},
                        journalist_outlets={"sami mokbel": "BBC"})
    sources = {"bbc_gossip": {"tier": 4}}          # outlet 키 없음
    it = _item("bbc_gossip", {})

    # 통칭 라벨 — 등재 기자가 아니므로 보정이 걸리지 않는다
    assert resolve_tier(it, sources, registry, journalist="BBC Gossip") == 4.0
    # 등재 기자가 와도 소스 outlet 이 없으면 승격되지 않는다 (제거의 실제 효과)
    assert resolve_tier(it, sources, registry, journalist="Sami Mokbel") == 4.0
