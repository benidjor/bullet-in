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

def test_outlet_display_prefers_outlet_then_displayname_then_id():
    sources = {"bbc_sport": {"display_name": "BBC Sport"}}
    assert outlet_display({"outlet": "The Athletic", "source_id": "x"}, sources) == "The Athletic"
    assert outlet_display({"outlet": None, "source_id": "bbc_sport"}, sources) == "BBC Sport"
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

def test_facet_counts():
    arts = [
        {"source_id": "bbc_sport", "outlet": "BBC Sport", "tier": 2, "team": "arsenal"},
        {"source_id": "bbc_sport", "outlet": "BBC Sport", "tier": 2, "team": "arsenal"},
        {"source_id": "x", "outlet": None, "tier": 0, "team": "arsenal"},
    ]
    sources = {"x": {"display_name": "afcstuff"}}
    f = facet_counts(arts, sources)
    assert f["total"] == 3
    assert f["team"] == {"arsenal": 3}
    assert f["outlets"] == [("BBC Sport", 2), ("afcstuff", 1)]
    assert f["tiers"] == {0: 1, 1: 0, 2: 2, 3: 0, 4: 0}

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

def test_facet_counts_splits_registered_and_more():
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
    assert f["journalists"]["registered"] == [
        ("David Ornstein", "David Ornstein (The Athletic)", 2)]
    assert f["journalists"]["more"] == [
        ("Kaya Kaynak", "Kaya Kaynak (Goal.com)", 3),
        ("Arsenal Official", "Arsenal Official", 1)]

def test_facet_counts_journalists_empty_without_directory():
    f = facet_counts([{"journalist": None, "source_id": "goal"}], JSOURCES)
    assert f["journalists"] == {"registered": [], "more": []}
