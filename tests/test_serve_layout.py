from datetime import datetime
from bullet_in.serve.render import (
    humanize_when, fmt_date, outlet_display, tier_label, tier_key,
    neighbor_window, facet_counts, TIER_ORDER, TIER_HEADINGS,
)

NOW = datetime(2026, 6, 29, 12, 0, 0)

def test_humanize_when_buckets():
    assert humanize_when(datetime(2026, 6, 29, 11, 59, 30), NOW) == "방금 전"
    assert humanize_when(datetime(2026, 6, 29, 11, 30, 0), NOW) == "30분 전"
    assert humanize_when(datetime(2026, 6, 29, 10, 0, 0), NOW) == "2시간 전"
    assert humanize_when(datetime(2026, 6, 27, 12, 0, 0), NOW) == "2일 전"
    # 7일 초과는 절대 날짜
    assert humanize_when(datetime(2026, 6, 1, 12, 0, 0), NOW) == "2026-06-01"

def test_fmt_date():
    assert fmt_date(datetime(2026, 6, 29, 9, 5)) == "2026-06-29"

def test_outlet_display_prefers_outlet_then_source_outlet_then_displayname_then_id():
    sources = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"},
               "bbc_gossip": {"display_name": "BBC Football Gossip"}}
    # 기사에 실린 귀속 outlet 이 최우선
    assert outlet_display({"outlet": "The Athletic", "source_id": "x"}, sources) == "The Athletic"
    # 설정의 소스 outlet 으로 폴백 — BBC Sport 를 레지스트리 정식명 BBC 로 모은다
    assert outlet_display({"outlet": None, "source_id": "bbc_sport"}, sources) == "BBC"
    # 소스 outlet 이 없으면 display_name — 가십은 BBC 와 합치지 않는다
    assert outlet_display({"outlet": None, "source_id": "bbc_gossip"}, sources) == "BBC Football Gossip"
    assert outlet_display({"outlet": None, "source_id": "unknown"}, sources) == "unknown"

def test_tier_key_is_shortest_exact_form():
    # data-tier 와 facet data-value 가 문자열로 비교되므로 표기가 한 가지여야 한다
    assert tier_key(0) == "0"
    assert tier_key(1.0) == "1"
    assert tier_key(1.5) == "1.5"
    assert tier_key(4.0) == "4"
    assert tier_key(None) == ""

def test_tier_label_uses_capital_tier():
    assert tier_label(2) == "Tier 2"
    assert tier_label(2.0) == "Tier 2"
    assert tier_label(1.5) == "Tier 1.5"
    assert tier_label(None) == "Tier ?"

def test_tier_headings_are_credibility_scale():
    assert [TIER_HEADINGS[t] for t in TIER_ORDER] == [
        "Tier 0 · 공식",
        "Tier 1 · 공신력 최상",
        "Tier 1.5 · 공신력 상",
        "Tier 2 · 공신력 중",
        "Tier 3 · 공신력 하",
        "Tier 4 · 공신력 최하",
    ]

def test_neighbor_window_centers_and_clamps():
    assert neighbor_window(10, 5) == (3, 8)   # 중앙: i-2..i+2
    assert neighbor_window(10, 0) == (0, 5)   # 최신 근처
    assert neighbor_window(10, 1) == (0, 5)
    assert neighbor_window(10, 9) == (5, 10)  # 과거 근처
    assert neighbor_window(10, 8) == (5, 10)
    assert neighbor_window(3, 1) == (0, 3)    # n<size: 전부
    assert neighbor_window(5, 2) == (0, 5)

class _Reg:
    """facet_counts 가 쓰는 최소 레지스트리 (Registry 의 .outlets · .journalists 만)."""
    def __init__(self, outlets=None, journalists=None):
        self.outlets = outlets or {}
        self.journalists = journalists or {}

def test_facet_counts_groups_outlets_by_tier_then_name():
    arts = [
        {"source_id": "bbc", "outlet": None, "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
        {"source_id": "ath", "outlet": "The Athletic", "tier": 1, "team": "arsenal"},
    ]
    sources = {"bbc": {"display_name": "BBC Sport", "outlet": "BBC", "tier": 1},
               "ath": {"display_name": "afcstuff"}}
    reg = _Reg(outlets={"bbc": 1.0, "the athletic": 1.0})
    f = facet_counts(arts, sources, registry=reg)

    t1 = [g for g in f["outlets"]["initial"] if g["key"] == "1"][0]
    # 건수는 BBC 1 < The Athletic 3 이지만 이름 오름차순이 이긴다
    assert [i["value"] for i in t1["items"]] == ["BBC", "The Athletic"]
    assert t1["heading"] == "Tier 1 · 공신력 최상"

def test_facet_counts_unregistered_goes_last_by_name():
    arts = [
        {"source_id": "af", "outlet": None, "tier": 4, "team": "arsenal"},
        {"source_id": "af", "outlet": None, "tier": 4, "team": "arsenal"},
        {"source_id": "sun", "outlet": "The Sun", "tier": 4, "team": "arsenal"},
    ]
    sources = {"af": {"display_name": "afcstuff (aggregator)"},   # tier 없음 → 미등재
               "sun": {"display_name": "The Sun", "tier": 4}}
    f = facet_counts(arts, sources, registry=_Reg(outlets={"the sun": 4.0}))
    last = f["outlets"]["stages"][-1]
    assert last["label"] == "더보기 · Tier 4 · 미등재"
    assert [i["value"] for i in last["unregistered"]] == ["afcstuff (aggregator)"]

def test_outlet_tier_falls_back_to_source_tier_when_unregistered():
    """BBC Football Gossip · Goal.com 이 Tier 4 에 서는 실제 경로 (spec §3.4 · §5.1).
    이 폴백이 없으면 둘 다 미등재로 떨어진다 — registry 에 그 문자열이 없다."""
    arts = [{"source_id": "g", "outlet": None, "tier": 4, "team": "arsenal"}]
    sources = {"g": {"display_name": "BBC Football Gossip", "tier": 4}}
    f = facet_counts(arts, sources, registry=_Reg(outlets={"bbc": 1.0}))
    last = f["outlets"]["stages"][-1]
    assert [i["value"] for i in last["groups"][0]["items"]] == ["BBC Football Gossip"]
    assert last["unregistered"] == []

def test_facet_counts_skips_empty_tier_stages():
    # Tier 1 과 Tier 3 만 존재 → 첫 더보기는 Tier 2 를 건너뛰고 Tier 3 을 연다
    arts = [
        {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal"},
        {"source_id": "b", "outlet": "The Times", "tier": 3, "team": "arsenal"},
    ]
    sources = {"a": {}, "b": {}}
    reg = _Reg(outlets={"bbc": 1.0, "the times": 3.0})
    f = facet_counts(arts, sources, registry=reg)
    assert [s["label"] for s in f["outlets"]["stages"]] == ["더보기 · Tier 3"]

def test_facet_counts_tiers_include_one_point_five():
    arts = [
        {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal"},
        {"source_id": "a", "outlet": "Sky Sports", "tier": 1.5, "team": "arsenal"},
    ]
    f = facet_counts(arts, {"a": {}}, registry=_Reg())
    rows = {t["key"]: t["count"] for t in f["tiers"]}
    assert rows == {"0": 0, "1": 1, "1.5": 1, "2": 0, "3": 0, "4": 0}
    assert [t["label"] for t in f["tiers"]][:3] == ["Tier 0", "Tier 1", "Tier 1.5"]

def test_facet_counts_journalist_tier_from_registry():
    arts = [{"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
             "journalist": "온스테인"},
            {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
             "journalist": "Kaya Kaynak"}]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    reg = _Reg(journalists={"온스테인": 1.0, "david ornstein": 1.0})
    f = facet_counts(arts, {"a": {}}, directory=directory, registry=reg)
    t1 = [g for g in f["journalists"]["initial"] if g["key"] == "1"][0]
    # 등재 기자는 레지스트리 tier, 비전담 (미등재) 은 기사 tier 로 같은 그룹에 분류
    assert [i["label"] for i in t1["items"]] == ["David Ornstein (The Athletic)", "Kaya Kaynak"]
    assert f["journalists"]["stages"] == []   # 미등재 꼬리 없음

def test_facet_counts_includes_stage_excluding_other():
    arts = [
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "rumour"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "rumour"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "official"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "other"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal"},   # 미태깅(None)
    ]
    f = facet_counts(arts, {})
    assert f["stage"]["rumour"] == 2
    assert f["stage"]["official"] == 1
    assert "other" not in f["stage"]      # other는 집계 제외
    assert set(f["stage"]) == {"official", "medical", "personal_terms",
                               "negotiating", "interest", "rumour"}

def test_facet_counts_other_bucket_counts_offmission():
    arts = [
        {"transfer_stage": "rumour"},
        {"transfer_stage": "official"},
        {"transfer_stage": "other"},
        {},  # 미태깅(None)
    ]
    f = facet_counts(arts, {})
    assert f["other"] == 2            # other + None (= 비-displayable)
    assert "other" not in f["stage"]  # 기존 계약: stage에는 미포함


from bullet_in.serve.render import journalist_entry

DIR = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"},
       "david ornstein": {"name": "David Ornstein", "outlet": "The Athletic"},
       "charles watts": {"name": "Charles Watts", "outlet": None}}
JSOURCES = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"},
            "goal": {"display_name": "Goal.com", "outlet": "Goal.com"},
            "arsenal_official": {"display_name": "Arsenal.com", "outlet": "Arsenal.com",
                                 "journalist_label": "Arsenal Official"}}

def test_journalist_entry_normalizes_alias_and_labels_outlet():
    e = journalist_entry({"journalist": "온스테인", "source_id": "bbc_sport"}, JSOURCES, DIR)
    assert e == {"name": "David Ornstein", "label": "David Ornstein (The Athletic)",
                 "registered": True}

def test_journalist_entry_registered_without_outlet_shows_name_only():
    e = journalist_entry({"journalist": "Charles Watts", "source_id": "goal"}, JSOURCES, DIR)
    assert e["label"] == "Charles Watts" and e["registered"] is True

def test_journalist_entry_unregistered_uses_source_outlet():
    e = journalist_entry({"journalist": "Kaya Kaynak", "source_id": "goal"}, JSOURCES, DIR)
    assert e == {"name": "Kaya Kaynak", "label": "Kaya Kaynak (Goal.com)", "registered": False}

def test_journalist_entry_label_omits_parens_for_source_label():
    e = journalist_entry({"journalist": "Arsenal Official", "source_id": "arsenal_official"},
                         JSOURCES, DIR)
    assert e == {"name": "Arsenal Official", "label": "Arsenal Official", "registered": False}

def test_journalist_entry_none_when_missing():
    assert journalist_entry({"journalist": None, "source_id": "goal"}, JSOURCES, DIR) is None
    assert journalist_entry({"journalist": "  ", "source_id": "goal"}, JSOURCES, DIR) is None

def test_facet_counts_journalists_aggregate_by_name_without_registry():
    # registry 없음 → tier 조회가 전부 실패해 전원 미등재 단계로 흘러가지만
    # 별칭(온스테인 → David Ornstein) 은 이름 정규화로 여전히 합산돼야 한다
    arts = [
        {"journalist": "온스테인", "source_id": "bbc_sport"},          # alias → 정규화
        {"journalist": "David Ornstein", "source_id": "bbc_sport"},   # 같은 기자 — 합산돼야
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Kaya Kaynak", "source_id": "goal"},
        {"journalist": "Arsenal Official", "source_id": "arsenal_official"},
        {"journalist": None, "source_id": "goal"},                    # 집계 제외
    ]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    last = f["journalists"]["stages"][-1]
    assert [i["value"] for i in last["unregistered"]] == [
        "Arsenal Official", "David Ornstein", "Kaya Kaynak"]
    assert [i["count"] for i in last["unregistered"]] == [1, 2, 3]
    assert [i["label"] for i in last["unregistered"]] == [
        "Arsenal Official", "David Ornstein (The Athletic)", "Kaya Kaynak (Goal.com)"]

def test_facet_counts_journalists_empty_without_directory():
    f = facet_counts([{"journalist": None, "source_id": "goal"}], JSOURCES)
    assert f["journalists"] == {"initial": [], "stages": []}
