from datetime import datetime
from bullet_in.credibility import _with_norm_keys
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

def test_outlet_display_x_fixed_tier_source_uses_journalist_mapping():
    # x_ornstein (고정 tier · credibility 미지정) 도 기자 소속 매핑을 탄다 (PR #137 후속)
    # — display_name 폴백이면 facet 이 The Athletic 과 분열되고 tier 조회도 실패한다
    sources = {"x_ornstein": {"display_name": "David Ornstein (X)", "medium": "x", "tier": 1}}
    directory = {"@david_ornstein": {"name": "David Ornstein", "outlet": "The Athletic"}}
    row = {"outlet": None, "source_id": "x_ornstein", "journalist": "@David_Ornstein"}
    assert outlet_display(row, sources, directory=directory) == "The Athletic"

def test_outlet_display_x_unregistered_handle_keeps_display_name_fallback():
    sources = {"x_other": {"display_name": "Some Account (X)", "medium": "x"}}
    row = {"outlet": None, "source_id": "x_other", "journalist": "@nobody"}
    assert outlet_display(row, sources, directory={}) == "Some Account (X)"

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
    # 사이드바 견출은 독자 라벨만 — 내부 Tier 문자열 노출 금지 (spec1 §7.1)
    assert [TIER_HEADINGS[t] for t in TIER_ORDER] == [
        "구단 공식", "공신력 최상", "공신력 상",
        "공신력 중", "공신력 하", "공신력 최하",
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
    """facet_counts 가 쓰는 최소 레지스트리 (Registry 의 .outlets · .journalists 만).
    조회가 공백 무시 키를 쓰므로 Registry 와 같게 정규화한다."""
    def __init__(self, outlets=None, journalists=None):
        self.outlets = _with_norm_keys(outlets or {})
        self.journalists = _with_norm_keys(journalists or {})

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
    assert t1["heading"] == "공신력 최상"

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
    assert last["label"] == "더보기 · 공신력 최하 · 미등재"
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
    assert [s["label"] for s in f["outlets"]["stages"]] == ["더보기 · 공신력 하"]

def test_facet_counts_tiers_include_one_point_five():
    arts = [
        {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal"},
        {"source_id": "a", "outlet": "Sky Sports", "tier": 1.5, "team": "arsenal"},
    ]
    f = facet_counts(arts, {"a": {}}, registry=_Reg())
    rows = {t["key"]: t["count"] for t in f["tiers"]}
    assert rows == {"0": 0, "1": 1, "1.5": 1, "2": 0, "3": 0, "4": 0}
    assert [t["reader"] for t in f["tiers"]][:3] == ["구단 공식", "공신력 최상", "공신력 상"]

def test_facet_counts_journalist_tier_from_registry():
    # 첫 화면은 2건 문턱을 함께 넘어야 하므로 (기자 축 설계 §3.2) 이름마다 2건씩 둔다
    arts = [{"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
             "journalist": j}
            for j in ["온스테인", "온스테인", "Kaya Kaynak", "Kaya Kaynak"]]
    directory = {"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"}}
    reg = _Reg(journalists={"온스테인": 1.0, "david ornstein": 1.0})
    f = facet_counts(arts, {"a": {}}, directory=directory, registry=reg)
    t1 = [g for g in f["journalists"]["initial"] if g["key"] == "1"][0]
    # 등재 기자는 레지스트리 tier, 비전담 (미등재) 은 기사 tier 로 같은 그룹에 분류.
    # 미등재 쪽 소속은 기사가 아는 매체에서 온다 (기자 축 설계 §2.2 — 소스 'a' 는 매체를
    # 모르는데 기사가 BBC 로 적어 뒀다).
    assert [i["label"] for i in t1["items"]] == ["David Ornstein (The Athletic)",
                                                 "Kaya Kaynak (BBC)"]
    assert f["journalists"]["stages"] == []   # 미등재 꼬리 · 추가 단계 없음

def test_facet_counts_includes_stage_excluding_other():
    # 단계 계수는 방향 in · out 한정 (단계 재정의 스펙 2026-08-10 §8) — none 은 분모 제외
    arts = [
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal",
         "transfer_stage": "rumour", "transfer_direction": "in"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal",
         "transfer_stage": "rumour", "transfer_direction": "out"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal",
         "transfer_stage": "rumour", "transfer_direction": "none"},   # 타 구단 딜 → 계수 제외
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal",
         "transfer_stage": "official", "transfer_direction": "in"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal", "transfer_stage": "other"},
        {"source_id": "s", "outlet": "BBC", "tier": 1, "team": "arsenal"},   # 미태깅(None)
    ]
    f = facet_counts(arts, {})
    assert f["stage"]["rumour"] == 2
    assert f["stage"]["official"] == 1
    assert "other" not in f["stage"]      # other는 집계 제외
    assert set(f["stage"]) == {"official", "done", "agreed", "medical", "personal_terms",
                               "negotiating", "interest", "rumour", "collapsed"}

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

DIR = _with_norm_keys({"온스테인": {"name": "David Ornstein", "outlet": "The Athletic"},
                       "david ornstein": {"name": "David Ornstein", "outlet": "The Athletic"},
                       "charles watts": {"name": "Charles Watts", "outlet": None}})
JSOURCES = {"bbc_sport": {"display_name": "BBC Sport", "outlet": "BBC"},
            "goal": {"display_name": "Goal.com", "outlet": "Goal.com"},
            "guardian": {"display_name": "The Guardian", "outlet": "The Guardian"},
            # 여러 매체를 실어 나르는 통로 소스 — 자기 outlet 이 없다 (설계 §2.2 D 갈래)
            "fmkorea": {"display_name": "에펨코리아"},
            "arsenal_official": {"display_name": "Arsenal.com", "outlet": "Arsenal.com",
                                 "journalist_label": "Arsenal Official"}}

def _journalist_items(f):
    """모든 자리 (첫 화면 · 더보기 단계) 의 기자 항목을 {이름: 건수} 로 모은다."""
    out = {}
    for g in f["journalists"]["initial"]:
        out.update({i["value"]: i["count"] for i in g["items"]})
    for st in f["journalists"]["stages"]:
        for g in st["groups"]:
            out.update({i["value"]: i["count"] for i in g["items"]})
        out.update({i["value"]: i["count"] for i in st["unregistered"]})
        out.update({i["value"]: i["count"] for i in st["items"]})
    return out


def _stage_named(f, label):
    return next(st for st in f["journalists"]["stages"] if st["label"] == label)


def test_journalist_entry_normalizes_alias_and_labels_outlet():
    e = journalist_entry({"journalist": "온스테인", "source_id": "bbc_sport"}, JSOURCES, DIR)
    assert e == {"name": "David Ornstein", "label": "David Ornstein (The Athletic)",
                 "registered": True, "outlet": "The Athletic"}

def test_journalist_entry_registered_without_outlet_shows_name_only():
    e = journalist_entry({"journalist": "Charles Watts", "source_id": "goal"}, JSOURCES, DIR)
    assert e["label"] == "Charles Watts" and e["registered"] is True

def test_journalist_entry_unregistered_uses_source_outlet():
    e = journalist_entry({"journalist": "Kaya Kaynak", "source_id": "goal"}, JSOURCES, DIR)
    assert e == {"name": "Kaya Kaynak", "label": "Kaya Kaynak (Goal.com)",
                 "registered": False, "outlet": "Goal.com"}

def test_journalist_entry_label_omits_parens_for_source_label():
    e = journalist_entry({"journalist": "Arsenal Official", "source_id": "arsenal_official"},
                         JSOURCES, DIR)
    assert e == {"name": "Arsenal Official", "label": "Arsenal Official",
                 "registered": False, "outlet": None}

def test_journalist_entry_none_when_missing():
    assert journalist_entry({"journalist": None, "source_id": "goal"}, JSOURCES, DIR) is None
    assert journalist_entry({"journalist": "  ", "source_id": "goal"}, JSOURCES, DIR) is None

def test_facet_counts_journalists_aggregate_by_name_without_registry():
    # registry 없음 → tier 조회가 전부 실패해 전원 미등재 단계로 흘러가지만
    # 별칭(온스테인 → David Ornstein) 은 이름 정규화로 여전히 합산돼야 한다
    arts = [
        {"journalist": "온스테인", "source_id": "bbc_sport"},          # alias → 정규화
        {"journalist": "David Ornstein", "source_id": "bbc_sport"},   # 같은 기자 — 합산돼야
        {"journalist": "Kaya Kaynak", "source_id": "guardian"},
        {"journalist": "Kaya Kaynak", "source_id": "guardian"},
        {"journalist": "Kaya Kaynak", "source_id": "guardian"},
        {"journalist": "Arsenal Official", "source_id": "arsenal_official"},
        {"journalist": None, "source_id": "guardian"},                # 집계 제외
    ]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert _journalist_items(f) == {"Arsenal Official": 1, "David Ornstein": 2,
                                    "Kaya Kaynak": 3}
    tail = [st for st in f["journalists"]["stages"] if st["unregistered"]][-1]
    assert [i["label"] for i in tail["unregistered"]] == [
        "David Ornstein (The Athletic)", "Kaya Kaynak (The Guardian)"]
    # 1건짜리는 새 단계로 내려간다 (기자 축 설계 §3.3)
    assert [i["value"] for i in _stage_named(f, "더보기 · 기사 1건인 기자")["items"]] == [
        "Arsenal Official"]

def test_facet_counts_journalists_empty_without_directory():
    f = facet_counts([{"journalist": None, "source_id": "goal"}], JSOURCES)
    assert f["journalists"] == {"initial": [], "stages": [], "total": 0}

def test_journalist_entry_co_byline_resolves_to_registered_representative():
    from bullet_in.serve.render import journalist_entry
    sources = {"skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports"}}
    directory = {"dharmesh sheth": {"name": "Dharmesh Sheth", "outlet": "Sky Sports"},
                 "@skysports_sheth": {"name": "Dharmesh Sheth", "outlet": "Sky Sports"}}
    row = {"journalist": "Zinny Boswell and Dharmesh Sheth", "source_id": "skysports"}
    e = journalist_entry(row, sources, directory)
    assert e["name"] == "Dharmesh Sheth"
    assert e["registered"] is True
    assert e["label"] == "Dharmesh Sheth (Sky Sports)"

def test_journalist_entry_co_byline_without_registered_stays_verbatim():
    from bullet_in.serve.render import journalist_entry
    sources = {"skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports"}}
    directory = {"dharmesh sheth": {"name": "Dharmesh Sheth", "outlet": "Sky Sports"}}
    row = {"journalist": "Sam Blitz and Nick Wright", "source_id": "skysports"}
    e = journalist_entry(row, sources, directory)
    assert e["name"] == "Sam Blitz and Nick Wright"
    assert e["registered"] is False

def test_journalist_entry_co_byline_two_registered_picks_first_in_byline():
    from bullet_in.serve.render import journalist_entry
    sources = {"skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports"}}
    directory = {"sam dean": {"name": "Sam Dean", "outlet": "The Telegraph"},
                 "dharmesh sheth": {"name": "Dharmesh Sheth", "outlet": "Sky Sports"}}
    row = {"journalist": "Dharmesh Sheth and Sam Dean", "source_id": "skysports"}
    e = journalist_entry(row, sources, directory)
    assert e["name"] == "Dharmesh Sheth"

def test_journalist_entry_no_false_partial_name_match():
    from bullet_in.serve.render import journalist_entry
    sources = {"skysports": {"display_name": "Sky Sports", "outlet": "Sky Sports"}}
    directory = {"sam dean": {"name": "Sam Dean", "outlet": "The Telegraph"}}
    # 'Sam Deanston' 은 Sam Dean 과 다른 인물 — 단어 경계 밖 부분 일치 금지
    row = {"journalist": "Sam Deanston and Kim Lee", "source_id": "skysports"}
    e = journalist_entry(row, sources, directory)
    assert e["registered"] is False
def test_outlet_display_promotes_registered_journalist_affiliation():
    sources = {"x_afcstuff": {"credibility": "x_mentions",
                              "display_name": "afcstuff (aggregator)"}}
    directory = {"@samimokbel_bbc": {"name": "Sami Mokbel", "outlet": "BBC"}}
    row = {"outlet": None, "source_id": "x_afcstuff", "journalist": "@SamiMokbel_BBC"}
    assert outlet_display(row, sources, directory=directory) == "BBC"

def test_outlet_display_folds_org_account_to_official_name():
    sources = {"x_afcstuff": {"credibility": "x_mentions",
                              "display_name": "afcstuff (aggregator)"}}
    outlet_dir = {"talksport": "talkSPORT"}
    row = {"outlet": None, "source_id": "x_afcstuff", "journalist": "@talkSPORT"}
    assert outlet_display(row, sources, outlet_dir=outlet_dir) == "talkSPORT"

def test_outlet_display_unregistered_or_no_affiliation_falls_back():
    sources = {"x_afcstuff": {"credibility": "x_mentions",
                              "display_name": "afcstuff (aggregator)"}}
    # 미등재 핸들
    row = {"outlet": None, "source_id": "x_afcstuff", "journalist": "@tabuteauS"}
    assert outlet_display(row, sources, directory={}, outlet_dir={}) == "afcstuff (aggregator)"
    # 등재됐지만 소속 없음 (독립 ITK)
    directory = {"@fabrizioromano": {"name": "Fabrizio Romano", "outlet": None}}
    row = {"outlet": None, "source_id": "x_afcstuff", "journalist": "@FabrizioRomano"}
    assert outlet_display(row, sources, directory=directory) == "afcstuff (aggregator)"

def test_outlet_display_promoted_and_non_x_rows_unchanged():
    sources = {"x_afcstuff": {"credibility": "x_mentions",
                              "display_name": "afcstuff (aggregator)"},
               "bbc_sport": {"outlet": "BBC", "display_name": "BBC Sport"}}
    directory = {"@samimokbel_bbc": {"name": "Sami Mokbel", "outlet": "BBC"}}
    # 승격 항목 (outlet 저장값) 은 그대로
    row = {"outlet": "talkSPORT", "source_id": "x_afcstuff", "journalist": "@JacobsBen"}
    assert outlet_display(row, sources, directory=directory) == "talkSPORT"
    # 비 X 소스는 기존 폴백 유지
    row = {"outlet": None, "source_id": "bbc_sport", "journalist": "Sami Mokbel"}
    assert outlet_display(row, sources, directory=directory) == "BBC"


def test_facet_counts_collapsed_ignores_direction():
    # 무산은 방향 게이트 예외 (단계 재정의 스펙 §8 개정 2026-08-11) — 잔류 확정 ·
    # 재계약 체결은 방향 none 이라, 게이트를 걸면 무산 필터가 제 내용물을 잃는다.
    arts = [{"transfer_stage": "collapsed", "transfer_direction": "none"},
            {"transfer_stage": "collapsed", "transfer_direction": "in"},
            {"transfer_stage": "agreed", "transfer_direction": "none"}]
    f = facet_counts(arts, {})
    assert f["stage"]["collapsed"] == 2      # 방향 무관하게 전건
    assert f["stage"]["agreed"] == 0         # 다른 단계는 in · out 한정 유지


def test_facet_stage_counts_bbc_gossip_excluded_by_direction():
    # 가십은 규칙 (rule_stage) 으로 rumour · none 저장 — 단계 계수가 in · out 한정으로
    # 바뀌면서 (단계 재정의 스펙 §8) 방향 none 인 가십은 루머 계수에서 빠진다.
    # 가십 도달 경로는 가십 밴드 · 전체 목록으로 유지된다.
    arts = [{"source_id": "bbc_gossip", "outlet": None, "tier": 4, "team": "arsenal",
             "transfer_stage": "rumour", "transfer_direction": "none"}]
    f = facet_counts(arts, {"bbc_gossip": {"display_name": "BBC Football Gossip"}})
    assert f["stage"]["rumour"] == 0
    assert f["stage"]["interest"] == 0
    assert f["other"] == 0                # 단계가 있으므로 기타 분모로도 새지 않는다


def test_journalist_entry_folds_spaced_korean_alias():
    # fmkorea 말머리는 "데이비드 온스테인" 처럼 띄어 쓴다 — 등재 판정 · 표기가 통해야 한다
    e = journalist_entry({"journalist": "데이비드 온스테인", "source_id": "bbc_sport"},
                         JSOURCES, {"데이비드온스테인": {"name": "David Ornstein",
                                                  "outlet": "The Athletic"}})
    assert e == {"name": "David Ornstein", "label": "David Ornstein (The Athletic)",
                 "registered": True, "outlet": "The Athletic"}


# --- 공저자 다중 귀속 (설계 2026-08-14 · 정책 C) ---

from bullet_in.serve.render import article_journalists, fold_alias_spellings


def _art(**kw):
    # tier 를 두지 않는다 — registry 없이 재는 테스트라 전원 미등재 꼬리로 모인다
    base = {"source_id": "bbc_sport", "team": "arsenal"}
    base.update(kw)
    return base


def test_article_journalists_reaches_every_author():
    row = _art(journalist="David Ornstein",
               authors_json='["David Ornstein", "James McNicholas"]')
    assert [e["name"] for e in article_journalists(row, JSOURCES, DIR)] == [
        "David Ornstein", "James McNicholas"]


def test_article_journalists_picks_registered_author_when_journalist_missing():
    row = _art(journalist=None, authors_json='["Kaya Kaynak", "\\uc628\\uc2a4\\ud14c\\uc778"]')
    entries = article_journalists(row, JSOURCES, DIR)
    assert entries[0]["name"] == "David Ornstein"     # 등재 기자가 대표
    assert [e["name"] for e in entries] == ["David Ornstein", "Kaya Kaynak"]


def test_article_journalists_decomposes_composite_stored_value():
    row = _art(source_id="goal", journalist="Sam Blitz and Nick Wright",
               authors_json='["Sam Blitz", "Nick Wright"]')
    assert [e["name"] for e in article_journalists(row, JSOURCES, DIR)] == [
        "Sam Blitz", "Nick Wright"]


def test_article_journalists_keeps_source_label_as_representative():
    # 통칭 라벨 우선 규칙을 우회하면 조직 바이라인이 사이드바 첫 화면으로 올라온다
    row = _art(source_id="arsenal_official", journalist="Arsenal Official",
               authors_json='["Some Writer", "Other Writer"]')
    entries = article_journalists(row, JSOURCES, DIR)
    assert entries[0]["name"] == "Arsenal Official"


def test_article_journalists_falls_back_to_single_journalist_without_authors():
    # 전환 규칙 — authors_json 이 비면 현행 규칙 그대로 판정한다
    row = _art(journalist="온스테인")
    assert [e["name"] for e in article_journalists(row, JSOURCES, DIR)] == ["David Ornstein"]


def test_article_journalists_empty_when_no_byline_at_all():
    assert article_journalists(_art(journalist=None), JSOURCES, DIR) == []


def test_facet_counts_makes_an_item_for_coauthor_only_name():
    # 옛 정책 C 는 대표가 된 적 있는 이름에만 항목을 만들어서, 공동 기사에만 나오는
    # 기자는 카드에 실린 채 사이드바에서 빠졌다 (기자 축 설계 §3.4).
    # 이제 항목을 만들고 대표 여부는 더보기 단계 배치로만 쓴다.
    arts = [_art(journalist="David Ornstein",
                 authors_json='["David Ornstein", "James McNicholas"]')]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert _journalist_items(f) == {"David Ornstein": 1, "James McNicholas": 1}
    co = _stage_named(f, "더보기 · 공동 기사에만 나오는 기자")
    assert [i["value"] for i in co["items"]] == ["David Ornstein", "James McNicholas"]


def test_facet_counts_counts_article_for_coauthor_that_leads_elsewhere():
    arts = [_art(journalist="David Ornstein",
                 authors_json='["David Ornstein", "Kaya Kaynak"]'),
            _art(source_id="guardian", journalist="Kaya Kaynak")]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert _journalist_items(f) == {"David Ornstein": 1, "Kaya Kaynak": 2}


def test_fold_alias_spellings_merges_case_variants_of_unregistered_name():
    arts = [_art(source_id="guardian", journalist="JAMES SHARPE"),
            _art(source_id="guardian", journalist="James Sharpe")]
    folded = fold_alias_spellings(arts, DIR)
    f = facet_counts(arts, JSOURCES, directory=folded)
    assert _journalist_items(f) == {"James Sharpe": 2}


def test_fold_alias_spellings_leaves_registered_names_alone():
    arts = [_art(journalist="온스테인"), _art(journalist="David Ornstein")]
    folded = fold_alias_spellings(arts, DIR)
    f = facet_counts(arts, JSOURCES, directory=folded)
    assert _journalist_items(f) == {"David Ornstein": 2}


def test_article_journalists_adds_no_coauthor_for_a_source_label():
    # 라운드업의 저장된 저자는 사람이 아니라 매체 이름이라 「외 1명」 이 되면 안 된다
    row = _art(source_id="arsenal_official", journalist="Arsenal Official",
               authors_json='["Arsenal Media"]')
    assert [e["name"] for e in article_journalists(row, JSOURCES, DIR)] == ["Arsenal Official"]


def test_article_journalists_keeps_an_organisation_that_is_the_only_byline():
    # 원문이 저자로 적은 값은 그대로 남긴다 (기자 축 설계 §4.3) — 옛 규칙은 이 값을
    # 언론사 정식명 'BBC' 로 접었는데, 접어도 기자 항목은 그대로 남아 아무것도 못 고쳤다.
    row = _art(source_id="bbc_sport", journalist="BBC Sport",
               authors_json='["BBC Sport"]')
    assert [e["name"] for e in article_journalists(row, JSOURCES, DIR)] == ["BBC Sport"]


# ---- 표기 접기 · 기타 계수 (기자명 · 언론사 표기 통일 설계 §4.3 · 사이드바 계수 설계 §5.4) ----

def test_outlet_display_folds_stored_outlet_spelling():
    """저장된 언론사명이 사전을 안 거쳐 「더 선」 과 The Sun 이 두 항목으로 갈리던 자리."""
    odir = {"더선": "The Sun", "sky": "Sky Sports"}
    assert outlet_display({"outlet": "더 선", "source_id": "x"}, {}, outlet_dir=odir) == "The Sun"
    assert outlet_display({"outlet": "Sky", "source_id": "x"}, {}, outlet_dir=odir) == "Sky Sports"


def test_outlet_display_leaves_unknown_spellings_alone():
    """사전에 없는 표기는 그대로 통과한다 — 저장값을 고치는 것이 아니라 표시만 접는다."""
    odir = {"더선": "The Sun"}
    assert outlet_display({"outlet": "BeSoccer", "source_id": "x"}, {}, outlet_dir=odir) == "BeSoccer"
    assert outlet_display({"outlet": "더 선", "source_id": "x"}, {}) == "더 선"


def test_facet_counts_other_counts_every_hidden_card():
    """배지 예외를 걷어낸 뒤 (2026-08-27) 기타 계수와 숨는 카드 수가 같아야 한다.
    둘이 갈리면 사이드바 건수가 실제 숨김 수와 어긋난다 (2026-08-19 실측 88 대 80)."""
    base = {"source_id": "a", "outlet": "BBC", "tier": 1, "team": "arsenal",
            "transfer_stage": "other", "title_ko": "첼시 이적 소식"}
    arts = [dict(base, linked_players=None),
            dict(base, linked_players="에제")]
    f = facet_counts(arts, {"a": {}}, registry=_Reg(outlets={"bbc": 1.0}))
    assert f["other"] == 2


# ---- 사이드바 기자 축 (설계 2026-08-20 · δ 소속 표기 · ε 목록 길이 · ζ 비인물 항목) ----

def test_journalist_outlet_comes_from_the_article_when_the_source_has_none():
    """소속이 절반만 붙던 자리 (설계 §2.2) — 통로 소스는 매체를 모르고 기사는 안다."""
    row = _art(source_id="fmkorea", journalist="Jacob Tanswell", outlet="The Athletic")
    assert journalist_entry(row, JSOURCES, DIR)["label"] == "Jacob Tanswell (The Athletic)"


def test_journalist_outlet_prefers_the_article_over_the_source():
    """순서는 사전 → 기사 → 소스다 — 소스 매체는 기사가 모를 때만 쓴다."""
    row = _art(source_id="bbc_sport", journalist="Sam Blitz", outlet="Daily Mail")
    assert journalist_entry(row, JSOURCES, DIR)["label"] == "Sam Blitz (Daily Mail)"


def test_journalist_outlet_from_the_article_goes_through_the_outlet_directory():
    """기사 매체도 언론사 사전을 거친다 — γ 의 표기 통일 결과와 같은 이름이어야 한다."""
    row = _art(source_id="fmkorea", journalist="Alan Nixon", outlet="더 선")
    e = journalist_entry(row, JSOURCES, DIR, {"더선": "The Sun"})
    assert e["label"] == "Alan Nixon (The Sun)"


def test_registered_journalist_without_outlet_takes_it_from_the_article():
    """사전에 소속이 비어 있는 등재 기자도 같은 순서를 탄다 (설계 §2.4)."""
    row = _art(source_id="fmkorea", journalist="Charles Watts", outlet="Arsenal Insider")
    e = journalist_entry(row, JSOURCES, DIR)
    assert e["registered"] is True
    assert e["label"] == "Charles Watts (Arsenal Insider)"


def test_registered_outlet_goes_through_the_outlet_directory():
    """사전 소속의 표기도 한 번 접는다 (설계 §2.5 나 · ChronicleLive → Chronicle Live)."""
    directory = {"lee ryder": {"name": "Lee Ryder", "outlet": "ChronicleLive"}}
    e = journalist_entry(_art(journalist="Lee Ryder"), JSOURCES, directory,
                         {"chroniclelive": "Chronicle Live"})
    assert e["label"] == "Lee Ryder (Chronicle Live)"


def test_label_omits_the_outlet_when_the_name_already_ends_with_parentheses():
    """정식명에 괄호가 이미 있으면 또 붙이지 않는다 (설계 §2.5 가).

    실물은 'Bruno Andrade (ESPN) (ESPN)' 7건이었다 — 핸들이 개인이 아니라 매체 계정이라
    표시명에 소속을 넣어 둔 자리다."""
    directory = {"bruno andrade": {"name": "Bruno Andrade (ESPN)", "outlet": "ESPN"}}
    e = journalist_entry(_art(journalist="Bruno Andrade", outlet="ESPN"), JSOURCES, directory)
    assert e["label"] == "Bruno Andrade (ESPN)"


def test_label_omits_the_outlet_when_the_name_is_the_source_itself():
    """원문이 저자 자리에 매체 이름을 쓴 자리는 소속을 또 적지 않는다 (사용자 확정 2026-08-23).

    같은 목록의 'Arsenal Official' · 'BBC Gossip' 은 통칭 라벨이라 괄호가 없는데
    'BBC Sport' 만 '(BBC)' 가 붙어 어색했다. 이름은 원문이 쓴 값이라 그대로 남긴다."""
    row = _art(source_id="bbc_sport", journalist="BBC Sport")
    e = journalist_entry(row, JSOURCES, DIR)
    assert e["name"] == "BBC Sport" and e["label"] == "BBC Sport"


def test_country_edition_domain_folds_into_the_outlet_name():
    """나라판 도메인 표기는 매체명으로 접는다 (설계 §4.5) — 저장된 언론사가 이미 같다."""
    row = _art(source_id="fmkorea", journalist="ESPN.com.br", outlet="ESPN")
    e = journalist_entry(row, JSOURCES, DIR)
    assert e["name"] == "ESPN" and e["label"] == "ESPN"


def test_facet_counts_labels_a_name_with_its_most_common_outlet():
    """이름 하나에 라벨 하나 (설계 §2.3) — 매체가 갈리면 기사가 많은 쪽을 쓴다."""
    arts = [_art(content_hash=h, source_id="fmkorea", journalist="Isaan Khan", outlet=o)
            for h, o in [("h1", "Daily Mail"), ("h2", "Daily Mail"), ("h3", "The Sun")]]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    got = [it for st in f["journalists"]["stages"]
           for it in st["unregistered"] + st["items"] if it["value"] == "Isaan Khan"]
    assert got and got[0]["label"] == "Isaan Khan (Daily Mail)"
    assert got[0]["count"] == 3          # 소속은 라벨일 뿐 필터 키가 아니라 항목이 안 갈린다


def test_facet_counts_first_screen_needs_two_articles():
    """첫 화면 문턱 (설계 §3.2) — 1건짜리는 사라지지 않고 새 단계로 내려간다."""
    reg = _Reg(journalists={"온스테인": 1.0, "david ornstein": 1.0})
    arts = [_art(content_hash="h1", journalist="온스테인"),
            _art(content_hash="h2", journalist="Sami Mokbel", tier=1.5)]
    f = facet_counts(arts, JSOURCES, directory=DIR, registry=reg)
    assert f["journalists"]["initial"] == []
    single = _stage_named(f, "더보기 · 기사 1건인 기자")
    assert [i["value"] for i in single["items"]] == ["David Ornstein", "Sami Mokbel"]

    arts.append(_art(content_hash="h3", journalist="온스테인"))
    f = facet_counts(arts, JSOURCES, directory=DIR, registry=reg)
    assert [i["value"] for g in f["journalists"]["initial"] for i in g["items"]] == [
        "David Ornstein"]


def test_facet_counts_coauthor_stage_is_judged_before_the_single_article_stage():
    """둘에 함께 걸리는 항목이 있어 순서가 결과를 가른다 (설계 §3.3)."""
    arts = [_art(journalist="David Ornstein",
                 authors_json='["David Ornstein", "James McNicholas"]')]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    co = _stage_named(f, "더보기 · 공동 기사에만 나오는 기자")
    assert [i["value"] for i in co["items"]] == ["David Ornstein", "James McNicholas"]
    assert not any(st["label"] == "더보기 · 기사 1건인 기자"
                   for st in f["journalists"]["stages"])


def test_facet_counts_first_screen_is_judged_before_the_coauthor_stage():
    """공동 기사에만 나와도 공신력 상한 안에 2건 이상이면 첫 화면에 남는다 (설계 §3.3)."""
    reg = _Reg(journalists={"온스테인": 1.0, "david ornstein": 1.0})
    arts = [_art(content_hash=h, journalist="온스테인",
                 authors_json='["\uc628\uc2a4\ud14c\uc778", "James McNicholas"]')
            for h in ("h1", "h2")]
    f = facet_counts(arts, JSOURCES, directory=DIR, registry=reg)
    assert [i["value"] for g in f["journalists"]["initial"] for i in g["items"]] == [
        "David Ornstein"]
    co = _stage_named(f, "더보기 · 공동 기사에만 나오는 기자")
    assert [i["value"] for i in co["items"]] == ["James McNicholas"]


def test_facet_counts_makes_no_item_for_a_goal_com_journalist():
    """Goal.com 소속 기자는 항목을 만들지 않는다 (설계 §5.1).

    도달 경로는 언론사 facet 의 Goal.com 항목이 유지한다 — 그 항목이 사라지면 이 결정을
    다시 봐야 한다."""
    arts = [_art(source_id="goal", journalist="Kaya Kaynak"),
            _art(content_hash="h2", journalist="온스테인")]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert _journalist_items(f) == {"David Ornstein": 1}
    outlets = [i["value"] for st in f["journalists"]["stages"] for i in st["items"]]
    assert "Kaya Kaynak" not in outlets
    # 카드 · 필터 키는 그대로다 (항목만 안 만든다)
    assert [e["name"] for e in article_journalists(arts[0], JSOURCES, DIR)] == ["Kaya Kaynak"]


def test_facet_view_carries_the_item_total_for_the_search_box():
    """검색칸 placeholder 의 인원수 — 접힌 단계까지 합친 값이다 (설계 §3.3 가)."""
    arts = [_art(content_hash="h1", journalist="온스테인"),
            _art(content_hash="h2", journalist="Sami Mokbel")]
    f = facet_counts(arts, JSOURCES, directory=DIR)
    assert f["journalists"]["total"] == 2
