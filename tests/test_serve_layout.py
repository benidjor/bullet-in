from datetime import datetime
from bullet_in.serve.render import (
    humanize_when, fmt_date, outlet_display, tier_label,
    neighbor_window, facet_counts,
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

def test_tier_label():
    assert tier_label(2) == "tier 2"
    assert tier_label(2.0) == "tier 2"
    assert tier_label(None) == "tier ?"

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
