import pytest
from pathlib import Path
from datetime import datetime, timezone
from bullet_in.credibility import (
    load_registry, resolve_tier, Registry, journalist_directory, outlet_directory,
    norm_alias,
)
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
    assert r.outlets["l'équipe"] == 3.0
    assert r.outlets["레키프"] == 3.0
    assert r.outlets["rmc"] == 1.0
    assert r.outlets["foot mercato"] == 4.0

def test_journalist_directory_maps_alias_and_name():
    from bullet_in.credibility import journalist_directory
    d = journalist_directory("config/credibility.yaml")
    # tier 는 공저 기사의 대표 선정 입력이다 (2026-08-27) — 등급이 없으면 None 이다.
    assert d["온스테인"] == {"name": "David Ornstein", "outlet": "The Athletic", "tier": 1}
    assert d["@fabrizioromano"]["name"] == "Fabrizio Romano"
    assert d["fabrizio romano"]["outlet"] is None      # 프리랜서
    assert d["sami mokbel"] == {"name": "Sami Mokbel", "outlet": "BBC", "tier": 1}
    assert d["mario cortegana"]["tier"] is None        # 등재됐지만 등급 없음
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


def test_sources_yaml_gossip_has_no_outlet():
    """bbc_gossip 에 outlet 을 되돌리면 가십 41건이 facet 에서 BBC (Tier 1) 로
    합쳐진다 (spec §3.4). 위 유닛 테스트는 합성 dict 를 써서 이 드리프트를
    못 잡으므로, 설정 파일 자체를 읽어 계약을 고정한다."""
    from bullet_in.score import load_sources
    s = load_sources(Path(__file__).parent.parent / "config" / "sources.yaml")
    assert "outlet" not in s["bbc_gossip"]
    assert s["bbc_sport"]["outlet"] == "BBC"

def test_tom_canton_registered_tier_4_is_neutral():
    """등재해도 기사 tier 는 안 바뀐다 — min(4, 4) = 4 (spec §3.6)."""
    registry = load_registry(REG)
    assert registry.journalists["tom canton"] == 4.0
    assert registry.journalist_outlets["tom canton"] == "football.london"

    sources = {"football_london": {"tier": 4, "outlet": "football.london"}}
    it = _item("football_london", {})
    assert resolve_tier(it, sources, registry, journalist="Tom Canton") == 4.0

    # 기자 facet 에서 미등재 구간을 벗어난다
    d = journalist_directory(REG)
    assert d["tom canton"]["name"] == "Tom Canton"

# B1: Gary Jacob tier 2 상향 · Ben Jacobs tier 3 등재 (2026-07-23)
def test_gary_jacob_raised_to_tier_two():
    r = load_registry(REG)
    assert r.journalists["@garyjacob"] == 2.0
    assert r.journalists["gary jacob"] == 2.0

def test_ben_jacobs_handle_beats_talksport_outlet_fallback():
    # afcstuff 가 [ @JacobsBen ] 로 인용하면 핸들 매칭(tier 3)이
    # talkSPORT outlet 폴백(tier 4)보다 우선한다.
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions"}}
    it = _item("x_afcstuff",
               {"text": "Arsenal in talks for target [ @JacobsBen ]",
                "outlet": "talkSPORT"})
    assert resolve_tier(it, sources, r) == 3.0

def test_ben_jacobs_korean_name_not_shadowed_by_gary_in_fmkorea():
    # fmkorea 부분 문자열 모드에서 Ben 한글명이 Gary 별칭에 가려지지 않는다.
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea",
               {"title": "아스날 이적 소식 [talkSPORT]",
                "body": "벤 제이콥스 기자에 따르면 협상이 진행 중이다."})
    assert resolve_tier(it, sources, r) == 3.0

def test_ben_jacobs_english_name_not_shadowed_by_gary_jacob():
    # Gary 의 바 별칭 "Jacob" 이 "Jacobs" 를 부분 매칭해선 안 된다 (min 이 Gary 를 집으면 오귀속).
    r = load_registry(REG)
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    it = _item("fmkorea",
               {"title": "Arsenal transfer news",
                "body": "According to Ben Jacobs, talks are progressing."})
    assert resolve_tier(it, sources, r) == 3.0

def test_outlet_directory_maps_aliases_to_official_name(tmp_path):
    from bullet_in.credibility import outlet_directory
    p = tmp_path / "cred.yaml"
    p.write_text(
        'journalists: []\n'
        'outlets:\n'
        '  - {name: talkSPORT, tier: 4, aliases: ["talkSPORT"]}\n'
        "  - {name: L'Équipe, tier: 3, aliases: [\"레키프\", \"lequipe\"]}\n",
        encoding="utf-8")
    d = outlet_directory(p)
    assert d["talksport"] == "talkSPORT"
    assert d["lequipe"] == "L'Équipe"
    assert d["레키프"] == "L'Équipe"

def test_live_config_x_ornstein_fixed_tier_one():
    """spec 2026-07-25 §5.1 — 본인 트윗엔 @핸들이 없어 x_mentions 판정 불가, 고정 tier 1."""
    from datetime import datetime, timezone
    from bullet_in.models import RawItem
    from bullet_in.score import load_sources
    sources = load_sources("config/sources.yaml")
    assert sources["x_ornstein"]["tier"] == 1
    assert sources["x_ornstein"]["config"]["self_source"] is True
    registry = load_registry("config/credibility.yaml")
    it = RawItem(source_id="x_ornstein", source_type="x",
                 url="https://x.com/David_Ornstein/status/1",
                 fetched_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
                 raw_payload={"text": "Arsenal deal #AFC", "journalist": "@David_Ornstein"})
    assert resolve_tier(it, sources, registry, journalist="@David_Ornstein") == 1.0


# --- 별칭 조회의 공백 정규화 ---
# fmkorea 말머리 · 본문은 같은 이름을 붙여 쓰기도 하고 띄어 쓰기도 한다
# ("데이비드온스테인" · "데이비드 온스테인"). 등록된 쪽 표기만 맞으면 조회가 통해야 한다.

def _reg_with_spaced_variants(tmp_path):
    p = tmp_path / "reg.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: David Ornstein, tier: 1, outlet: The Athletic, '
        'aliases: ["데이비드온스테인"]}\n'
        '  - {name: Art de Roché, tier: 1.5, aliases: ["드 로셰", "드로셰"]}\n'
        "outlets:\n"
        '  - {name: Foot Mercato, tier: 4, aliases: ["Foot Mercato", "footmercato"]}\n',
        encoding="utf-8")
    return p


def test_norm_alias_ignores_whitespace_and_case():
    from bullet_in.credibility import norm_alias
    assert norm_alias("데이비드 온스테인") == norm_alias("데이비드온스테인")
    assert norm_alias("Art  de Roché") == norm_alias("art de roché")


def test_registry_resolves_alias_written_with_spaces(tmp_path):
    from bullet_in.credibility import norm_alias
    r = load_registry(_reg_with_spaced_variants(tmp_path))
    assert r.journalists[norm_alias("데이비드 온스테인")] == 1.0
    assert r.journalist_outlets[norm_alias("데이비드 온스테인")] == "The Athletic"


def test_registry_keeps_original_alias_keys(tmp_path):
    # 정규화 키는 덧붙이는 것 — 기존 조회 (풀네임 · 소문자) 는 그대로 통한다
    r = load_registry(_reg_with_spaced_variants(tmp_path))
    assert r.journalists["데이비드온스테인"] == 1.0
    assert r.journalists["david ornstein"] == 1.0


def test_load_registry_tolerates_whitespace_variants_in_one_entry(tmp_path):
    # "드 로셰" · "드로셰" 는 정규화하면 한 키가 된다 — 같은 항목이라 중복 오류가 아니다
    r = load_registry(_reg_with_spaced_variants(tmp_path))
    assert r.journalists["드로셰"] == 1.5
    assert r.outlets["footmercato"] == 4.0


def test_resolve_tier_fmkorea_matches_spaced_body_mention(tmp_path):
    # 본문이 "데이비드 온스테인" 이면 등록 별칭 (붙여 쓴 형태) 과 매칭돼 tier 1 이 나와야 한다
    r = load_registry(_reg_with_spaced_variants(tmp_path))
    sources = {"fmkorea": {"credibility": "fmkorea"}}
    item = RawItem(source_id="fmkorea", source_type="html", url="u",
                   fetched_at=datetime.now(timezone.utc),
                   raw_payload={"title": "[무명] 아스날 소식",
                                "body": "데이비드 온스테인 기자에 따르면 협상이 진행 중이다."})
    assert resolve_tier(item, sources, r) == 1.0


def test_journalist_directory_resolves_spaced_alias(tmp_path):
    from bullet_in.credibility import norm_alias
    d = journalist_directory(_reg_with_spaced_variants(tmp_path))
    assert d[norm_alias("데이비드 온스테인")]["name"] == "David Ornstein"


def test_outlet_directory_resolves_spaced_alias(tmp_path):
    from bullet_in.credibility import norm_alias, outlet_directory
    d = outlet_directory(_reg_with_spaced_variants(tmp_path))
    assert d[norm_alias("footmercato")] == "Foot Mercato"


def test_espn_brasil_handle_resolves_to_bruno_andrade():
    """Bruno Andrade 는 트위터 계정이 없어 afcstuff 가 소속사 계정으로 인용한다
    ('Bruno Andrade (@ESPNBrasil)' · '[ @ESPNBrasil ]'). 등재 전에는 fallback_tier 4
    로 떨어져, 같은 기사가 fmkorea 경로 (tier 2) 와 X 경로 (tier 4) 로 갈렸다."""
    r = load_registry(REG)
    assert r.journalists["@espnbrasil"] == 2.0
    assert r.journalists["브루노안드라데"] == 2.0
    assert r.journalist_outlets["@espnbrasil"] == "ESPN"


def test_espn_brasil_display_name_carries_outlet():
    d = journalist_directory(REG)
    assert d["@espnbrasil"]["name"] == "Bruno Andrade (ESPN)"
    assert d["@espnbrasil"]["outlet"] == "ESPN"


def test_espn_outlet_is_medium_credibility():
    # 공신력 중 = tier 2.0 (render._READER_TIER)
    assert load_registry(REG).outlets["espn"] == 2.0


def test_x_mention_of_espn_brasil_gets_medium_tier():
    """등재 전에는 fallback_tier 4 였다 — 이 경로가 실제로 tier 를 올리는지 고정."""
    r = load_registry(REG)
    sources = {"x_afcstuff": {"credibility": "x_mentions", "fallback_tier": 4}}
    it = _item("x_afcstuff", {"text": "Bruno Guimarães latest. [ @ESPNBrasil ]"})
    assert resolve_tier(it, sources, r, journalist="@ESPNBrasil") == 2.0


# ---- 표기 전용 항목 (tier 없는 등재) — 기자명 · 언론사 표기 통일 설계 §4.1 ----

def test_tierless_entry_stays_out_of_the_registry(tmp_path):
    """등급을 안 매긴 항목은 Registry 에 안 들어간다 — 공신력이 붙으면 안 되기 때문."""
    p = tmp_path / "spell.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: Spelling Only, aliases: ["표기만"]}\n'
        "outlets:\n"
        '  - {name: Outlet Only, aliases: ["표기만 매체"]}\n', encoding="utf-8")
    r = load_registry(p)
    assert r.journalists == {}
    assert r.outlets == {}


def test_tierless_entry_still_folds_spellings(tmp_path):
    """조회 맵에는 들어간다 — 표기 통일에 필요한 것은 이름뿐이고 등급이 아니다."""
    p = tmp_path / "spell.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: Spelling Only, outlet: Daily Mail, aliases: ["표기만"]}\n'
        "outlets: []\n", encoding="utf-8")
    d = journalist_directory(p)
    assert d["표기만"]["name"] == "Spelling Only"
    assert d["표기만"]["outlet"] == "Daily Mail"


def test_tierless_journalist_does_not_promote_a_fixed_source_tier(tmp_path):
    """고정 소스 경로의 min 승격은 등재 기자만 탄다 — 표기 전용 항목은 tier 를 안 움직인다."""
    p = tmp_path / "spell.yaml"
    p.write_text(
        "journalists:\n"
        '  - {name: Spelling Only, outlet: The Sun, aliases: ["표기만"]}\n'
        "outlets: []\n", encoding="utf-8")
    r = load_registry(p)
    sources = {"sun": {"tier": 4, "outlet": "The Sun"}}
    it = _item("sun", {"title": "Saka"})
    assert resolve_tier(it, sources, r, journalist="Spelling Only") == 4.0


def test_split_korean_journalist_spellings_fold_to_one_name():
    """같은 기자가 두 항목으로 갈리던 자리 — 갈래 A 는 별칭 추가 · 갈래 B 는 표기 전용 항목."""
    d = journalist_directory(REG)
    assert d["제임스 맥니콜라스"]["name"] == "James McNicholas"
    assert d["맷로"]["name"] == "Matt Law"
    assert d["사이먼 존스"]["name"] == "Simon Jones"
    assert d["simon jones"]["name"] == "Simon Jones"
    assert d["이산 칸"]["name"] == "Isaan Khan"
    assert d["마리오 코르테가나"]["name"] == "Mario Cortegana"
    assert d["제임스 피어스"]["name"] == "James Pearce"
    assert d["@samwallacetel"]["name"] == "Sam Wallace"
    assert d["@dkingtelegraph"]["name"] == "Dominic King"


def test_korean_only_bylines_fold_to_their_latin_name():
    """한글 표기만 저장돼 있던 13명 — 로마자 이름을 원문 바이라인에서 확정해 등재했다."""
    d = journalist_directory(REG)
    pairs = {
        "크리스 워": "Chris Waugh",
        "세바스찬 스태포드-블루어": "Sebastian Stafford-Bloor",
        "세바스찬 스태포드-블로어": "Sebastian Stafford-Bloor",
        "폴 발루스": "Pol Ballús",
        "제임스 혼캐슬": "James Horncastle",
        "조지 콜킨": "George Caulkin",
        "마이크 맥그라스": "Mike McGrath",
        "존 퍼시": "John Percy",
        "잭 로서": "Jack Rosser",
        "니자르 킨셀라": "Nizaar Kinsella",
        "호펠디": "José Félix Díaz",
        "다니엘레 롱고": "Daniele Longo",
        "리 라이더": "Lee Ryder",
        "플로리안 플라텐버그": "Florian Plettenberg",
    }
    for ko, latin in pairs.items():
        assert d[ko]["name"] == latin
        # 저장값에 로마자로 실린 기사도 같은 항목으로 와야 두 표기가 한 항목이 된다
        assert d[latin.lower()]["name"] == latin


def test_two_spellings_of_the_same_person_share_one_entry():
    """「블루어」 · 「블로어」 는 norm_alias 가 공백 · 대소문자만 지워 저절로는 안 접힌다."""
    d = journalist_directory(REG)
    assert (d["세바스찬 스태포드-블루어"]["name"]
            == d["세바스찬 스태포드-블로어"]["name"] == "Sebastian Stafford-Bloor")


def test_spelling_only_journalists_carry_no_tier():
    """표기를 합치면서 공신력은 한 칸도 안 준다 (설계 §4.2)."""
    r = load_registry(REG)
    for key in ["simon jones", "사이먼 존스", "isaan khan", "mario cortegana",
                "james pearce", "sam wallace", "dominic king",
                "크리스 워", "chris waugh", "호펠디", "josé félix díaz",
                "니자르 킨셀라", "nizaar kinsella"]:
        assert key not in r.journalists


def test_split_outlet_spellings_fold_to_one_name():
    """도메인이 같아 짝이 확정된 표기들 (언론사 표기 통일 설계 §2.1)."""
    d = outlet_directory(REG)
    assert d[norm_alias("The Athletics")] == "The Athletic"
    assert d[norm_alias("Telegraph")] == "The Telegraph"
    assert d[norm_alias("Sky")] == "Sky Sports"
    assert d[norm_alias("스카이스포츠")] == "Sky Sports"
    assert d[norm_alias("DM+")] == "Daily Mail"
    assert d[norm_alias("메일")] == "Daily Mail"
    for s in ["더 선", "더선", "더 썬", "더썬"]:
        assert d[norm_alias(s)] == "The Sun"
    assert d[norm_alias("아스")] == "AS"
    assert d[norm_alias("더 타임스")] == "The Times"
    assert d[norm_alias("스탠더드")] == "Evening Standard"


def test_unregistered_outlet_keeps_no_tier():
    """AS 는 등재 이력이 없어 표기 전용으로 넣었다 — 등급이 붙으면 안 된다."""
    r = load_registry(REG)
    assert "as" not in r.outlets
    assert "아스" not in r.outlets


def test_standalone_outlets_fold_to_formal_names():
    """합칠 짝이 없던 단독 매체의 약칭 · 한글 표기 (안건 γ 잔여 · 2026-08-20)."""
    d = outlet_directory(REG)
    for stored, name in [("Globo", "Globo"), ("O Jogo", "O Jogo"), ("마르카", "Marca"),
                         ("가제타", "La Gazzetta dello Sport"), ("CDS", "Corriere dello Sport"),
                         ("크로니클", "Chronicle Live"), ("MD", "Mundo Deportivo"),
                         ("CM", "Calciomercato"), ("CN", "CalcioNapoli24"),
                         ("BB", "BarcaBuzz"), ("NA", "Now Arsenal"),
                         ("TIA", "This Is Anfield"), ("FM", "Foot Mercato")]:
        assert d[norm_alias(stored)] == name


def test_display_only_standalone_outlets_stay_out_of_tier_lookup():
    """팬 · 집계 사이트는 표기만 정상화하고 등급은 폴백 4 를 유지한다.

    등급 사전에 들어가면 짧은 별칭 (MD · BB · NA · CN · TIA) 이 제목 부분 문자열로
    걸린다 — tier 4 는 min 때문에 무해하지만 애초에 그 경로를 안 타게 둔다."""
    r = load_registry(REG)
    for alias in ["besoccer", "스포르트", "md", "cm", "cn", "bb", "na", "tia",
                  "sport24", "relevo", "cope"]:
        assert alias not in r.outlets


def test_mismatched_stored_outlets_are_not_registered():
    """저장값이 원문 도메인과 어긋나는 매체는 표기 전용으로도 넣지 않는다 (안건 η).

    접기는 저장값 정확 일치라, 등급을 안 매겨도 틀린 값이 엉뚱한 항목으로 간다."""
    d = outlet_directory(REG)
    for stored in ["A BOLA", "빌트"]:
        assert norm_alias(stored) not in d


def test_two_letter_ge_alias_is_gone():
    """저장값을 Globo 로 고쳐 두 글자 별칭 "ge" 를 없앴다 (2026-08-20).

    등급 사전에 두 글자가 들어가면 제목 부분 문자열로 걸리고, Globo 는 tier 2 라
    잘못 걸리면 min 이 그 등급을 채택한다 — 별칭을 다시 넣지 않게 막는다."""
    r = load_registry(REG)
    assert "ge" not in r.outlets
    assert r.outlets["globo"] == 2.0
